#!/usr/bin/env bash
set -euo pipefail
printf 'Testing PC1 to PC2 after quarantine expiry...\n'
ip netns exec pc1 ping -c 2 -W 2 192.168.10.2
printf '\nActive OpenFlow flows:\n'
ovs-ofctl -O OpenFlow13 dump-flows br-sdn
