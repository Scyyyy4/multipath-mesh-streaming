import socket
import sys
import os
import time
import math
import struct

CHUNK_SIZE = 1200
SEND_BUF_SIZE = 4 * 1024 * 1024
PACE_EVERY = 64
PACE_SLEEP = 0.0005
TAIL_GUARD_SLEEP = 0.05

PKT_START = 1
PKT_DATA = 2
PKT_END = 3

START_FMT = "!BQIHH"
DATA_HDR_FMT = "!BIQHH"
END_FMT = "!BH"

def make_sockets(ip, ports):
    socks = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUF_SIZE)
        socks.append((sock, (ip, port)))
    return socks

def build_packets(filename):
    filesize = os.path.getsize(filename)
    total_packets = math.ceil(filesize / CHUNK_SIZE)
    packets = []
    with open(filename, "rb") as f:
        seq = 0
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            packets.append({"seq": seq, "offset": seq * CHUNK_SIZE, "payload": chunk, "payload_len": len(chunk)})
            seq += 1
    return filesize, total_packets, packets

def send_file(filename, ip, ports, mode):
    filesize, total_packets, packets = build_packets(filename)
    socks = make_sockets(ip, ports)
    sent_wire_packets = sent_wire_bytes = sent_source_packets = sent_source_bytes = 0
    print(f"[Sender UDP][{mode}] Sending {filename} via ports {ports}")
    print(f"[Sender UDP][{mode}] filesize={filesize}, total_packets={total_packets}, chunk_size={CHUNK_SIZE}")
    start_pkt = struct.pack(START_FMT, PKT_START, filesize, total_packets, len(ports), CHUNK_SIZE)
    for sock, addr in socks:
        sock.sendto(start_pkt, addr)
        sent_wire_packets += 1
        sent_wire_bytes += len(start_pkt)
    start_time = time.time()
    for idx, pkt in enumerate(packets):
        path_id = 0 if len(socks) == 1 else (idx % len(socks))
        sock, addr = socks[path_id]
        wire = struct.pack(DATA_HDR_FMT, PKT_DATA, pkt["seq"], pkt["offset"], path_id, pkt["payload_len"]) + pkt["payload"]
        sock.sendto(wire, addr)
        sent_wire_packets += 1
        sent_wire_bytes += len(wire)
        sent_source_packets += 1
        sent_source_bytes += pkt["payload_len"]
        if (idx + 1) % PACE_EVERY == 0:
            time.sleep(PACE_SLEEP)
    time.sleep(TAIL_GUARD_SLEEP)
    for path_id, (sock, addr) in enumerate(socks):
        end_pkt = struct.pack(END_FMT, PKT_END, path_id)
        for _ in range(3):
            sock.sendto(end_pkt, addr)
            sent_wire_packets += 1
            sent_wire_bytes += len(end_pkt)
            time.sleep(0.01)
    end_time = time.time()
    duration = end_time - start_time
    for sock, _ in socks:
        sock.close()
    wire_mbps = (sent_wire_bytes * 8 / duration / 1_000_000) if duration > 0 else 0
    goodput_mbps = (sent_source_bytes * 8 / duration / 1_000_000) if duration > 0 else 0
    print(f"[Sender UDP][{mode}] Duration: {duration:.2f} seconds")
    print(f"[Sender UDP][{mode}] Sent wire bytes: {sent_wire_bytes}")
    print(f"[Sender UDP][{mode}] Sent source bytes: {sent_source_bytes}")
    print(f"[Sender UDP][{mode}] Wire throughput: {wire_mbps:.2f} Mbps")
    print(f"[Sender UDP][{mode}] Application goodput: {goodput_mbps:.2f} Mbps")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 sender_udp.py <filename> <single|multi>")
        sys.exit(1)
    filename = sys.argv[1]
    mode = sys.argv[2]
    ip = "10.0.0.5"
    all_ports = [5301, 5302, 5303]
    if mode == "single":
        ports = [all_ports[0]]
    elif mode == "multi":
        ports = all_ports
    else:
        print("Invalid mode. Use 'single' or 'multi'.")
        sys.exit(1)
    send_file(filename, ip, ports, mode)
