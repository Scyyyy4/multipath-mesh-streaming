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

START_FMT = "!BQIHH"
DATA_HDR_FMT = "!BIQHH"
END_FMT = "!BH"

lock = threading.Lock()
meta_lock = threading.Lock()

global_meta = {"total_filesize": None, "total_packets": None, "path_count": None, "chunk_size": None}
pkt_buffer = {}
results = {}
end_flags = {}
global_stats = {"received_wire_packets": 0, "received_wire_bytes": 0,
                "received_source_packets": 0, "received_source_bytes": 0}
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
    print(f"[Receiver UDP] Listening on port {port}")
    start_time = None
    recv_packets = recv_bytes = 0
    while True:
        try:
            data, addr = sock.recvfrom(CHUNK_RECV_SIZE)
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
            _, total_filesize, total_packets, path_count, chunk_size = struct.unpack(START_FMT, data[:fs])
            with meta_lock:
                if global_meta["total_filesize"] is None:
                    global_meta.update({"total_filesize": total_filesize, "total_packets": total_packets,
                                        "path_count": path_count, "chunk_size": chunk_size})
            with lock:
                if first_start_time is None:
                    first_start_time = time.time()
            if start_time is None:
                start_time = time.time()
        elif pkt_type == PKT_DATA:
            hs = struct.calcsize(DATA_HDR_FMT)
            if len(data) < hs:
                continue
            _, seq, offset, path_id, payload_len = struct.unpack(DATA_HDR_FMT, data[:hs])
            payload = data[hs:hs + payload_len]
            with lock:
                if seq not in pkt_buffer:
                    pkt_buffer[seq] = {"offset": offset, "payload": payload, "path_id": path_id}
                    global_stats["received_source_packets"] += 1
                    global_stats["received_source_bytes"] += len(payload)
                    recv_packets += 1
                    recv_bytes += len(payload)
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
    duration = (time.time() - start_time) if start_time else 0.0
    with lock:
        results[port] = {"duration": duration, "packets": recv_packets, "bytes": recv_bytes}
    sock.close()
    print(f"[Receiver UDP] Port {port}: {recv_packets} pkts, {recv_bytes} bytes, {duration:.2f}s")

def reconstruct(output_file):
    global global_meta, pkt_buffer
    total_filesize = global_meta["total_filesize"]
    total_packets = global_meta["total_packets"]
    chunk_size = global_meta["chunk_size"]
    if total_filesize is None:
        print("[Receiver UDP] ERROR: No metadata received.")
        return 0
    out = bytearray(total_filesize)
    received = 0
    for seq, pkt in pkt_buffer.items():
        offset = pkt["offset"]
        data = pkt["payload"]
        out[offset:offset + len(data)] = data
        received += 1
    with open(output_file, "wb") as f:
        f.write(out)
    missing = total_packets - received
    print(f"[Receiver UDP] Packets received: {received}/{total_packets}, missing: {missing}")
    continuity = "continuous" if missing == 0 else f"{missing} packets missing"
    print(f"[Receiver UDP] Continuity check: {continuity}")
    print(f"[Receiver UDP] File complete: {'Yes' if missing == 0 else 'No'}")
    return received * chunk_size  # approx

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 receiver_udp.py <single|multi>")
        sys.exit(1)
    mode = sys.argv[1]
    all_ports = [5301, 5302, 5303]
    ports = [all_ports[0]] if mode == "single" else all_ports
    threads = [threading.Thread(target=recv_part, args=(p,)) for p in ports]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    reconstruct("reconstructed_udp.bin")
