#!/bin/bash

USER="fyp1"
PASS="fyp1user"

VM1="127.0.0.1"
VM2="10.10.10.162"
VM3="10.10.10.163"
VM4="10.10.10.164"
VM5="10.10.10.165"

run_tc_local() { CMD="$1"; echo "$PASS" | sudo -S bash -c "$CMD"; }

run_tc_remote() {
    HOST="$1"; CMD="$2"
    sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$USER@$HOST" "echo '$PASS' | sudo -S bash -c '$CMD'"
}

run_cmd() {
    HOST="$1"; CMD="$2"
    if [ "$HOST" == "127.0.0.1" ]; then run_tc_local "$CMD"; else run_tc_remote "$HOST" "$CMD"; fi
}

set_net() {
    HOST="$1"; IFACE="$2"; RATE="$3"; LOSS="$4"
    echo "[INFO] Setting $HOST:$IFACE rate=$RATE loss=$LOSS"
    CMD="
tc qdisc del dev $IFACE root 2>/dev/null || true
tc qdisc add dev $IFACE root handle 1: tbf rate $RATE burst 32k latency 400ms
tc qdisc add dev $IFACE parent 1:1 handle 10: netem loss $LOSS
"
    run_cmd "$HOST" "$CMD"
}

clear_net() {
    HOST="$1"; IFACE="$2"
    echo "[INFO] Clearing qdisc on $HOST:$IFACE"
    run_cmd "$HOST" "tc qdisc del dev $IFACE root 2>/dev/null || true"
}

show_status() {
    HOST="$1"; IFACE="$2"
    echo "[STATUS] $HOST:$IFACE"
    run_cmd "$HOST" "tc -s qdisc show dev $IFACE"
    echo "---"
}

apply_all() {
    set_net "$VM1" enp6s19 "$1" "$2"
    set_net "$VM1" enp6s20 "$3" "$4"
    set_net "$VM1" enp6s21 "$5" "$6"
    set_net "$VM2" enp6s19 "$1" "$2"
    set_net "$VM3" enp6s20 "$3" "$4"
    set_net "$VM4" enp6s21 "$5" "$6"
    set_net "$VM5" enp6s19 "$1" "$2"
    set_net "$VM5" enp6s20 "$3" "$4"
    set_net "$VM5" enp6s21 "$5" "$6"
    echo "[INFO] All rules applied."
}

clear_all() {
    for vm in "$VM1" "$VM2" "$VM3" "$VM4" "$VM5"; do
        for iface in enp6s19 enp6s20 enp6s21; do
            clear_net "$vm" "$iface"
        done
    done
    echo "[INFO] All rules cleared."
}

show_all() {
    for vm in "$VM1" "$VM2" "$VM3" "$VM4" "$VM5"; do
        for iface in enp6s19 enp6s20 enp6s21; do
            show_status "$vm" "$iface"
        done
    done
}

case "$1" in
    apply)
        [ $# -ne 7 ] && { echo "Usage: $0 apply <rate1> <loss1> <rate2> <loss2> <rate3> <loss3>"; echo "Example: $0 apply 20mbit 0% 20mbit 5% 20mbit 10%"; exit 1; }
        apply_all "$2" "$3" "$4" "$5" "$6" "$7" ;;
    clear)  clear_all ;;
    status) show_all ;;
    *)      echo "Usage: $0 <apply|clear|status>"; exit 1 ;;
esac
