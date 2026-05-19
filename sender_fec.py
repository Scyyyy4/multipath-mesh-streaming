import socket
import sys
import os
import time
import math
import struct

CHUNK_SIZE = 1200
DEFAULT_BLOCK_K = 4
SEND_BUF_SIZE = 4 * 1024 * 1024
PACE_EVERY = 64
PACE_SLEEP = 0.0005
START_REPEAT = 5
END_REPEAT = 5
CONTROL_GAP = 0.01
TAIL_GUARD_SLEEP = 0.05

PKT_START = 1
PKT_DATA = 2
PKT_END = 3
SYMBOL_SOURCE = 0
SYMBOL_REPAIR = 1

START_FMT = "!BQIIHHH"
DATA_HDR_FMT = "!BIQIIBHHH"
END_FMT = "!BH"

def make_sockets(ip, ports):
    socks = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUF_SIZE)
        socks.append((sock, (ip, port)))
    return socks

def xor_bytes(byte_list):
    if not byte_list:
        return b"", 0
    max_len = max(len(x) for x in byte_list)
    out = bytearray(max_len)
    for b in byte_list:
        padded = b + b"\x00" * (max_len - len(b))
        for i in range(max_len):
            out[i] ^= padded[i]
    return bytes(out), max_len

def build_source_packets(filename, block_k):
    filesize = os.path.getsize(filename)
    total_packets = math.ceil(filesize / CHUNK_SIZE)
    total_blocks = math.ceil(total_packets / block_k)
    packets = []
    with open(filename, "rb") as f:
        seq = 0
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            packets.append({"seq": seq, "offset": seq * CHUNK_SIZE, "block_id": seq // block_k,
                            "symbol_id": seq % block_k, "symbol_type": SYMBOL_SOURCE,
                            "payload": chunk, "orig_len": len(chunk)})
            seq += 1
    return filesize, total_packets, total_blocks, packets

def build_wire_packets(source_packets, block_k):
    blocks = {}
    for pkt in source_packets:
        blocks.setdefault(pkt["block_id"], []).append(pkt)
    wire_packets = []
    for block_id in sorted(blocks.keys()):
        srcs = sorted(blocks[block_id], key=lambda x: x["symbol_id"])
        for s in srcs:
            wire_packets.append(s)
        repair_payload, repair_len = xor_bytes([s["payload"] for s in srcs])
        wire_packets.append({"seq": srcs[0]["seq"], "offset": srcs[0]["offset"], "block_id": block_id,
                             "symbol_id": block_k, "symbol_type": SYMBOL_REPAIR,
                             "payload": repair_payload, "orig_len": repair_len})
    return wire_packets

def send_file(filename, ip, ports, mode, block_k):
    filesize, total_packets, total_blocks, source_packets = build_source_packets(filename, block_k)
    wire_packets = build_wire_packets(source_packets, block_k)
    socks = make_sockets(ip, ports)
    sent_wire_bytes = sent_source_bytes = sent_repair_bytes = 0
    print(f"[Sender FEC][{mode}] filesize={filesize}, total_packets={total_packets}, block_k={block_k}")
    start_pkt = struct.pack(START_FMT, PKT_START, filesize, total_packets, total_blocks, len(ports), block_k, CHUNK_SIZE)
    for path_id, (sock, addr) in enumerate(socks):
        for _ in range(START_REPEAT):
            sock.sendto(start_pkt, addr)
            sent_wire_bytes += len(start_pkt)
            time.sleep(CONTROL_GAP)
    start_time = time.time()
    for idx, pkt in enumerate(wire_packets):
        path_id = idx % len(socks)
        sock, addr = socks[path_id]
        wire = struct.pack(DATA_HDR_FMT, PKT_DATA, pkt["seq"], pkt["offset"], pkt["block_id"],
                           pkt["symbol_id"], pkt["symbol_type"], path_id, len(pkt["payload"]), pkt["orig_len"]) + pkt["payload"]
        sock.sendto(wire, addr)
        sent_wire_bytes += len(wire)
        if pkt["symbol_type"] == SYMBOL_SOURCE:
            sent_source_bytes += pkt["orig_len"]
        else:
            sent_repair_bytes += pkt["orig_len"]
        if (idx + 1) % PACE_EVERY == 0:
            time.sleep(PACE_SLEEP)
    time.sleep(TAIL_GUARD_SLEEP)
    for path_id, (sock, addr) in enumerate(socks):
        end_pkt = struct.pack(END_FMT, PKT_END, path_id)
        for _ in range(END_REPEAT):
            sock.sendto(end_pkt, addr)
            sent_wire_bytes += len(end_pkt)
            time.sleep(CONTROL_GAP)
    duration = time.time() - start_time
    for sock, _ in socks:
        sock.close()
    tp = (sent_wire_bytes * 8 / duration / 1_000_000) if duration > 0 else 0
    gp = (sent_source_bytes * 8 / duration / 1_000_000) if duration > 0 else 0
    print(f"[Sender FEC][{mode}] Duration: {duration:.2f}s  Wire: {tp:.2f} Mbps  Goodput: {gp:.2f} Mbps")
    print(f"[Sender FEC][{mode}] FEC redundancy: {sent_repair_bytes / sent_source_bytes * 100:.1f}%" if sent_source_bytes else "")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 sender_fec.py <filename> <single|multi> [block_k]")
        sys.exit(1)
    filename = sys.argv[1]
    mode = sys.argv[2]
    block_k = int(sys.argv[3]) if len(sys.argv) >= 4 else DEFAULT_BLOCK_K
    ip = "10.0.0.5"
    all_ports = [5301, 5302, 5303]
    ports = [all_ports[0]] if mode == "single" else all_ports
    send_file(filename, ip, ports, mode, block_k)
