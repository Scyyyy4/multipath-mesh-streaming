import socket
import threading
import time
import sys
import os
import struct
import shutil

CHUNK_SIZE = 4096
BIND_IP = "10.0.0.5"

lock = threading.Lock()
results = {}
global_stats = {"received_wire_connections": 0, "received_wire_bytes": 0, "expected_total_bytes": 0}
first_start_time = None
last_end_time = None

def recv_exact(conn, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)

def recv_part(port, output_dir):
    global first_start_time, last_end_time
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((BIND_IP, port))
    sock.listen(1)
    print(f"[Receiver TCP] Listening on port {port}")
    conn, addr = sock.accept()
    start_flag = recv_exact(conn, 5)
    if start_flag != b"START":
        conn.close(); sock.close(); return
    size_data = recv_exact(conn, 8)
    part_size = struct.unpack("!Q", size_data)[0]
    start_time = time.time()
    with lock:
        global_stats["received_wire_connections"] += 1
        global_stats["expected_total_bytes"] += part_size
        if first_start_time is None or start_time < first_start_time:
            first_start_time = start_time
    local_buffer = bytearray()
    while len(local_buffer) < part_size:
        chunk = conn.recv(min(CHUNK_SIZE, part_size - len(local_buffer)))
        if not chunk:
            break
        local_buffer.extend(chunk)
    recv_exact(conn, 3)  # END
    end_time = time.time()
    duration = end_time - start_time
    with lock:
        results[port] = {"duration": duration, "bytes": len(local_buffer), "expected_bytes": part_size,
                         "complete": len(local_buffer) == part_size}
        global_stats["received_wire_bytes"] += len(local_buffer)
        if last_end_time is None or end_time > last_end_time:
            last_end_time = end_time
    conn.close(); sock.close()
    part_file = f"{output_dir}/part_{port}"
    with open(part_file, "wb") as f:
        f.write(local_buffer)
    print(f"[Receiver TCP] Port {port}: {len(local_buffer)} bytes in {duration:.2f}s")

def merge_parts(parts_dir, outputfile):
    parts = sorted([f for f in os.listdir(parts_dir) if f.startswith("part_")])
    total = 0
    with open(outputfile, "wb") as out:
        for part in parts:
            with open(os.path.join(parts_dir, part), "rb") as pf:
                data = pf.read()
                out.write(data)
                total += len(data)
    return total

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 receiver_tcp.py <single|multi>")
        sys.exit(1)
    mode = sys.argv[1]
    output_dir = "tcp_parts"
    output_file = "reconstructed_tcp.bin"
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir)
    ports = [5301] if mode == "single" else [5301, 5302, 5303]
    threads = [threading.Thread(target=recv_part, args=(p, output_dir)) for p in ports]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = merge_parts(output_dir, output_file)
    total_duration = (last_end_time - first_start_time) if first_start_time and last_end_time else 0
    expected = global_stats["expected_total_bytes"]
    print(f"[Receiver TCP][{mode}] Reconstructed {total} / {expected} bytes in {total_duration:.2f}s")
    print(f"[Receiver TCP] File complete: {'Yes' if total == expected else 'No'}")
    shutil.rmtree(output_dir, ignore_errors=True)
