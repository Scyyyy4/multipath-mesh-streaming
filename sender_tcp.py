import socket
import sys
import os
import time
import struct

CHUNK_SIZE = 65536
SEND_BUF_SIZE = 4 * 1024 * 1024

def send_part(ip, port, data, part_size):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, SEND_BUF_SIZE)
    sock.connect((ip, port))
    sock.sendall(b"START")
    sock.sendall(struct.pack("!Q", part_size))
    total_sent = 0
    while total_sent < len(data):
        chunk = data[total_sent:total_sent + CHUNK_SIZE]
        sock.sendall(chunk)
        total_sent += len(chunk)
    sock.sendall(b"END")
    sock.close()

def send_file(filename, ip, ports, mode):
    import threading
    filesize = os.path.getsize(filename)
    with open(filename, "rb") as f:
        raw = f.read()
    n = len(ports)
    base = filesize // n
    parts = []
    for i in range(n):
        start = i * base
        end = start + base if i < n - 1 else filesize
        parts.append(raw[start:end])
    print(f"[Sender TCP][{mode}] filesize={filesize}, paths={n}")
    start_time = time.time()
    threads = []
    for i, port in enumerate(ports):
        t = threading.Thread(target=send_part, args=(ip, port, parts[i], len(parts[i])))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    duration = time.time() - start_time
    goodput = (filesize * 8 / duration / 1_000_000) if duration > 0 else 0
    print(f"[Sender TCP][{mode}] Duration: {duration:.2f}s  Goodput: {goodput:.2f} Mbps")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 sender_tcp.py <filename> <single|multi>")
        sys.exit(1)
    filename = sys.argv[1]
    mode = sys.argv[2]
    ip = "10.0.0.5"
    all_ports = [5301, 5302, 5303]
    ports = [all_ports[0]] if mode == "single" else all_ports
    send_file(filename, ip, ports, mode)
