#!/usr/bin/env python3
"""
Automated batch experiment runner.
Iterates over all configured protocol / mode / loss / rate / block_k combinations,
applies network emulation, runs sender + receiver, collects logs, and writes a CSV.

See README.md and final_report.pdf Section 3.7-3.8 for details.
"""
import subprocess
import time
import csv
import os
import sys

# ---- Configuration ----
NET_CONTROL = "./net_control.sh"
RECEIVER_HOST = "10.10.10.165"      # vm5
RECEIVER_USER = "fyp1"
RECEIVER_PASS = "fyp1user"
TEST_FILE = "testfile.bin"
OUTPUT_CSV = "results/experiment_results.csv"

PROTOCOLS = ["tcp", "udp", "fec"]
MODES = ["single", "multi"]
SEND_RATES = ["20mbit", "30mbit"]   # per-path rates
LOSS_PROFILES = [("0%", "0%", "0%"), ("3%", "3%", "3%"), ("5%", "5%", "5%"), ("10%", "10%", "10%")]
FEC_BLOCK_SIZES = [2, 4, 8]


def run_cmd(cmd, timeout=120):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT"


def apply_net(rate, losses):
    l1, l2, l3 = losses
    cmd = f"bash {NET_CONTROL} apply {rate} {l1} {rate} {l2} {rate} {l3}"
    run_cmd(cmd, timeout=30)


def clear_net():
    run_cmd(f"bash {NET_CONTROL} clear", timeout=30)


def run_experiment(protocol, mode, rate, losses, block_k=4):
    apply_net(rate, losses)
    time.sleep(1)

    if protocol == "tcp":
        recv_cmd = f"python3 receiver_tcp.py {mode}"
        send_cmd = f"python3 sender_tcp.py {TEST_FILE} {mode}"
    elif protocol == "udp":
        recv_cmd = f"python3 receiver_udp.py {mode}"
        send_cmd = f"python3 sender_udp.py {TEST_FILE} {mode}"
    else:
        recv_cmd = f"python3 receiver_fec.py {mode}"
        send_cmd = f"python3 sender_fec.py {TEST_FILE} {mode} {block_k}"

    # Start receiver on vm5 via SSH (background)
    ssh_recv = f"sshpass -p {RECEIVER_PASS} ssh -o StrictHostKeyChecking=no {RECEIVER_USER}@{RECEIVER_HOST} '{recv_cmd}' &"
    run_cmd(ssh_recv, timeout=10)
    time.sleep(1)

    # Run sender locally
    sender_log = run_cmd(send_cmd, timeout=120)
    time.sleep(2)

    clear_net()
    return sender_log


def parse_log(log, protocol):
    out = {}
    for line in log.splitlines():
        if "Duration:" in line:
            out["duration"] = line.split("Duration:")[1].strip().split()[0]
        if "Wire throughput:" in line:
            out["wire_mbps"] = line.split("Wire throughput:")[1].strip().split()[0]
        if "Application goodput:" in line:
            out["goodput_mbps"] = line.split("Application goodput:")[1].strip().split()[0]
        if "File complete:" in line:
            out["file_complete"] = "Yes" in line
    return out


def main():
    os.makedirs("results", exist_ok=True)
    fieldnames = ["protocol", "mode", "rate", "loss_p1", "loss_p2", "loss_p3", "block_k",
                  "duration", "wire_mbps", "goodput_mbps", "file_complete"]
    with open(OUTPUT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for protocol in PROTOCOLS:
            for mode in MODES:
                for losses in LOSS_PROFILES:
                    block_ks = FEC_BLOCK_SIZES if protocol == "fec" else [4]
                    for bk in block_ks:
                        for rate in SEND_RATES:
                            print(f"Running: {protocol} {mode} rate={rate} loss={losses} k={bk}")
                            log = run_experiment(protocol, mode, rate, losses, bk)
                            parsed = parse_log(log, protocol)
                            row = {"protocol": protocol, "mode": mode, "rate": rate,
                                   "loss_p1": losses[0], "loss_p2": losses[1], "loss_p3": losses[2],
                                   "block_k": bk, **parsed}
                            writer.writerow(row)
                            f.flush()
    print(f"Done. Results saved to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
