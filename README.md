# Multi-Path Data Streaming in a Mesh Network Using Network Coding

**CUHK IERG4999 Final Year Project II** — SU, Caiyi (1155191405)

This project designs, implements, and evaluates a controllable multi-path data streaming platform for experimental research in mesh networks. Starting from a physical Raspberry Pi mesh testbed, the system evolved into a virtualized five-node Proxmox environment with deterministic kernel-level multi-path routing, end-to-end file transmission, XOR-based UDP forward error correction (FEC), and automated performance evaluation.

---

## Architecture Overview

```
vm1 (sender)
  ├── enp6s19 ──► vm2 ──► vm5 (receiver)   [Path 1 / port 5301]
  ├── enp6s20 ──► vm3 ──► vm5              [Path 2 / port 5302]
  └── enp6s21 ──► vm4 ──► vm5              [Path 3 / port 5303]
```

Path selection is implemented via **DSCP-based Linux policy routing**: each outgoing port is marked with a different DSCP value, which is matched by `ip rule` entries to select among three separate routing tables. All paths converge on a dummy interface (`10.0.0.5`) at the destination.

```bash
# Example kernel-level routing configuration (vm1)
ip rule add tos 0x10 lookup path_1   # port 5301 → vm2
ip rule add tos 0x20 lookup path_2   # port 5302 → vm3
ip rule add tos 0x30 lookup path_3   # port 5303 → vm4

iptables -t mangle -A OUTPUT -p udp --dport 5301 -j DSCP --set-dscp 0x10
iptables -t mangle -A OUTPUT -p udp --dport 5302 -j DSCP --set-dscp 0x20
iptables -t mangle -A OUTPUT -p udp --dport 5303 -j DSCP --set-dscp 0x30
```

---

## Repository Structure

```
.
├── sender_udp.py          # UDP file sender (single/multi-path)
├── receiver_udp.py        # UDP file receiver with reordering and reassembly
├── sender_tcp.py          # TCP file sender (single/multi-path, segment-level split)
├── receiver_tcp.py        # TCP file receiver with per-port threads
├── sender_fec.py          # UDP sender with XOR-based FEC (configurable block size k)
├── receiver_fec.py        # UDP receiver with FEC decoding and recovery metrics
├── net_control.sh         # tc tbf + netem rate/loss control across all VMs via SSH
├── run_experiments.py     # Automated batch experiment runner (CSV log output)
├── results/               # Experiment result CSVs (example runs)
│   ├── experiment_results_1.csv
│   ├── experiment_results_2.csv
│   └── experiment_results_3.csv
└── docs/
    └── final_report.pdf   # Full project report
```

---

## Key Components

### Transport Modes

| Mode | Protocol | Path distribution |
|---|---|---|
| `single` | TCP / UDP / FEC | One flow on port 5301 |
| `multi` | TCP / UDP / FEC | Three concurrent flows on ports 5301–5303 |

**UDP**: packets distributed across paths in round-robin order at the packet level.

**TCP**: file divided into contiguous segments, one segment per flow.

**FEC (UDP)**: XOR-based block coding with configurable block size `k`. Every `k` source packets produce one repair (parity) packet. Single-loss recovery per block.

### FEC Encoding

```python
for each coding block:
    parity = source_1 XOR source_2 XOR ... XOR source_k
    transmit all source packets
    transmit one repair packet
```

Redundancy ratio ≈ `1/k`. Smaller `k` → more redundancy, better recovery. Larger `k` → less overhead, weaker protection.

### Network Emulation

`net_control.sh` applies `tc tbf` (rate limiting) and `tc netem loss` (packet loss injection) to all three path interfaces across all five VMs via SSH:

```bash
# Apply 20 Mbit/s on all paths, 5% loss on path 2, 10% on path 3
bash net_control.sh apply 20mbit 0% 20mbit 5% 20mbit 10%

# Clear all rules
bash net_control.sh clear
```

### Automated Experiments

`run_experiments.py` iterates over all combinations of protocol, mode, sending rate, loss settings, and FEC block size. Results are written to a unified CSV for analysis.

---

## Quick Start

### Prerequisites

- Five Linux nodes (VMs or Raspberry Pi) with routing configured as described above
- Python 3.8+
- `sshpass`, `tc` (iproute2), `iptables` on all nodes

### Run a single UDP multi-path transfer

```bash
# On vm5 (receiver)
python3 receiver_udp.py multi

# On vm1 (sender)
python3 sender_udp.py testfile.bin multi
```

### Run a FEC transfer with block size k=4

```bash
# On vm5
python3 receiver_fec.py multi

# On vm1
python3 sender_fec.py testfile.bin multi 4
```

### Run full experiment suite

```bash
python3 run_experiments.py
```

---

## Main Results

| Protocol | Zero-loss goodput (multi-path) | Behavior under loss |
|---|---|---|
| TCP | 57.43 Mbps | Graceful degradation; retransmission maintains integrity |
| UDP | 57.23 Mbps | Collapses at ≥1% loss; no recovery |
| FEC (k=4) | 45.05 Mbps | Stable ~45 Mbps up to 10% loss; some residual gaps |

- **Multi-path vs single-path**: multi-path TCP at 3% loss achieves 23.03 Mbps vs 13.06 Mbps single-path.
- **FEC block size**: smaller `k` (k=2) gives better recovery rate and lower residual loss than larger blocks (k=8).
- **Throughput ≠ integrity**: FEC can deliver high goodput while still leaving gaps in the reconstructed file; continuity must be checked separately.

---

## Tech Stack

`Linux` · `Python` · `Raspberry Pi 4B` · `Proxmox VE` · `tc (tbf + netem)` · `iptables` · `ip rule / DSCP policy routing` · `UDP / TCP sockets` · `XOR FEC` · `SSH automation`

---

## Research Context

This project was completed as part of the Bachelor of Information Engineering programme at the **Chinese University of Hong Kong (CUHK)**, Department of Information Engineering, under the supervision of Prof. Yang Weihao (INC Lab). It provides a foundation for future work on BATS network coding, adaptive FEC, and multi-path video streaming.
