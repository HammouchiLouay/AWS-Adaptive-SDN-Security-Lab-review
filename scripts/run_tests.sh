#!/usr/bin/env bash
set -uo pipefail
printf '\n=== SDN health ===\n'
systemctl --no-pager --full status sdn-controller | head -18 || true
ovs-vsctl get-controller br-sdn
ovs-vsctl get bridge br-sdn protocols
ovs-ofctl -O OpenFlow13 dump-flows br-sdn
printf '\n=== Same segment (expected success) ===\n'
ip netns exec pc1 ping -c 2 -W 2 192.168.10.2
ip netns exec pc3 ping -c 2 -W 2 192.168.20.4
printf '\n=== Cross segment (expected fail; controller DENY) ===\n'
if ip netns exec pc1 ping -c 2 -W 1 192.168.20.3; then
  echo 'UNEXPECTED: cross-segment ping succeeded'; exit 1
else
  echo 'PASS: cross-segment ping blocked'
fi
printf '\n=== Adaptive ICMP quarantine: PC1 ===\n'
# 12 ICMP probes deliberately exceed 8-in-5s threshold.
ip netns exec pc1 ping -c 12 -i 0.2 -W 1 192.168.10.2 || true
printf '\n=== OpenFlow quarantine rule (priority=200, hard_timeout=20) ===\n'
ovs-ofctl -O OpenFlow13 dump-flows br-sdn | grep -E 'priority=200|priority=10' || true
printf '\n=== Controller evidence ===\n'
journalctl -u sdn-controller -n 40 --no-pager | grep -E 'QUARANTINE|SWITCH_CONNECTED|SEGMENT_DROP|SPOOF_DROP' || true
printf '\nAfter ~20 seconds, rerun normal same-segment ping to verify recovery.\n'
