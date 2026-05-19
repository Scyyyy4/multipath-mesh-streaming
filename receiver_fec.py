# receiver_fec.py — UDP FEC receiver with XOR-based single-loss recovery
# See final_report.pdf (Section 3.5) for protocol design details.
import socket
import threading
import time
import sys
import struct
import os

RECV_BUF_SIZE = 8 * 1024 * 1024
CHUNK_RECV_SIZE = 4096
IDLE_TIMEOUT = 0.5
TAIL_WAIT_AFTER_END = 1.5

PKT_START = 1
PKT_DATA = 2
PKT_END = 3
SYMBOL_SOURCE = 0
SYMBOL_REPAIR = 1

START_FMT = "!BQIIHHH"
DATA_HDR_FMT = "!BIQIIBHHH"
END_FMT = "!BH"

lock = threading.Lock()
meta_lock = threading.Lock()
global_meta = {"total_filesize": None, "total_packets": None, "total_blocks": None,
               "path_count": None, "block_k": None, "chunk_size": None}
blocks = {}
results = {}
end_flags = {}
global_stats = {"received_wire_packets": 0, "received_wire_bytes": 0,
                "received_source_packets": 0, "received_source_bytes": 0,
                "received_repair_packets": 0, "received_repair_bytes": 0}
first_start_time = None
last_data_time = None
all_end_seen_time = None

def make_socket(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, RECV_BUF_SIZE)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(IDLE_TIMEOUT)
    return sock

def recv_part(port):
    global first_start_time, last_data_time, all_end_seen_time
    sock = make_socket(port)
    print(f"[Receiver FEC] Listening on port {port}")
    start_time = recv_packets = recv_bytes = None, 0, 0
    while True:
        try:
            data, _ = sock.recvfrom(CHUNK_RECV_SIZE)
        except socket.timeout:
            with lock:
                done = global_meta["path_count"] is not None and len(end_flags) >= global_meta["path_count"]
                waited = all_end_seen_time is not None and time.time() - all_end_seen_time >= TAIL_WAIT_AFTER_END
            if done and waited:
                break
            continue
        if not data:
            continue
        pkt_type = data[0]
        with lock:
            global_stats["received_wire_packets"] += 1
            global_stats["received_wire_bytes"] += len(data)
        if pkt_type == PKT_START:
            fs = struct.calcsize(START_FMT)
            if len(data) < fs:
                continue
            _, total_filesize, total_packets, total_blocks, path_count, block_k, chunk_size = struct.unpack(START_FMT, data[:fs])
            with meta_lock:
                if global_meta["total_filesize"] is None:
                    global_meta.update({"total_filesize": total_filesize, "total_packets": total_packets,
                                        "total_blocks": total_blocks, "path_count": path_count,
                                        "block_k": block_k, "chunk_size": chunk_size})
            with lock:
                if first_start_time is None:
                    first_start_time = time.time()
            if start_time is None:
                start_time = time.time()
        elif pkt_type == PKT_DATA:
            hs = struct.calcsize(DATA_HDR_FMT)
            if len(data) < hs:
                continue
            _, seq, offset, block_id, symbol_id, symbol_type, path_id, payload_len, orig_len = struct.unpack(DATA_HDR_FMT, data[:hs])
            payload = data[hs:hs + payload_len]
            with lock:
                block = blocks.setdefault(block_id, {"sources": {}, "repairs": {}})
                if symbol_type == SYMBOL_SOURCE and symbol_id not in block["sources"]:
                    block["sources"][symbol_id] = {"seq": seq, "offset": offset, "payload": payload, "orig_len": orig_len}
                    global_stats["received_source_packets"] += 1
                    global_stats["received_source_bytes"] += len(payload)
                    last_data_time = time.time()
                elif symbol_type == SYMBOL_REPAIR and symbol_id not in block["repairs"]:
                    block["repairs"][symbol_id] = {"seq": seq, "offset": offset, "payload": payload, "orig_len": orig_len}
                    global_stats["received_repair_packets"] += 1
                    global_stats["received_repair_bytes"] += len(payload)
                    last_data_time = time.time()
        elif pkt_type == PKT_END:
            fs = struct.calcsize(END_FMT)
            if len(data) < fs:
                continue
            _, path_id = struct.unpack(END_FMT, data[:fs])
            with lock:
                end_flags[port] = True
                if global_meta["path_count"] is not None and len(end_flags) >= global_meta["path_count"]:
                    if all_end_seen_time is None:
                        all_end_seen_time = time.time()
    sock.close()

def recover_one_block(block_id, block):
    block_k = global_meta["block_k"]
    chunk_size = global_meta["chunk_size"]
    total_packets = global_meta["total_packets"]
    total_filesize = global_meta["total_filesize"]
    expected_sids = [sid for sid in range(block_k) if block_id * block_k + sid < total_packets]
    missing = [sid for sid in expected_sids if sid not in block["sources"]]
    if len(missing) != 1 or block_k not in block["repairs"]:
        return 0
    repair = block["repairs"][block_k]
    recovered = bytearray(repair["payload"])
    for sid in expected_sids:
        if sid == missing[0]:
            continue
        src = block["sources"][sid]["payload"]
        padded = src + b"\x00" * (len(recovered) - len(src))
        for i in range(len(recovered)):
            recovered[i] ^= padded[i]
    seq = block_id * block_k + missing[0]
    offset = seq * chunk_size
    orig_len = (total_filesize - offset) if seq == total_packets - 1 else chunk_size
    block["sources"][missing[0]] = {"seq": seq, "offset": offset,
                                     "payload": bytes(recovered[:orig_len]), "orig_len": orig_len}
    return 1

def reconstruct_and_print(output_file, mode):
    if global_meta["total_filesize"] is None:
        print("[Receiver FEC] ERROR: No metadata."); return
    total_filesize = global_meta["total_filesize"]
    total_packets = global_meta["total_packets"]
    total_blocks = global_meta["total_blocks"]
    block_k = global_meta["block_k"]
    chunk_size = global_meta["chunk_size"]
    # Run FEC recovery
    recovered_count = sum(recover_one_block(bid, blk) for bid, blk in blocks.items())
    # Assemble
    out = bytearray(total_filesize)
    received_source = 0
    for block_id, block in blocks.items():
        for sid, pkt in block["sources"].items():
            offset = pkt["offset"]
            data = pkt["payload"]
            if offset + len(data) <= total_filesize:
                out[offset:offset + len(data)] = data
                received_source += 1
    with open(output_file, "wb") as f:
        f.write(out)
    missing_after = total_packets - received_source
    print(f"[Receiver FEC][{mode}] Source packets received: {received_source}/{total_packets}")
    print(f"[Receiver FEC][{mode}] Recovered by FEC: {recovered_count}")
    print(f"[Receiver FEC][{mode}] Residual missing: {missing_after}")
    print(f"[Receiver FEC][{mode}] File complete: {'Yes' if missing_after == 0 else 'No'}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 receiver_fec.py <single|multi>")
        sys.exit(1)
    mode = sys.argv[1]
    ports = [5301] if mode == "single" else [5301, 5302, 5303]
    threads = [threading.Thread(target=recv_part, args=(p,)) for p in ports]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    reconstruct_and_print("reconstructed_fec.bin", mode)
