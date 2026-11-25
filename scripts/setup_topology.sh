#!/usr/bin/env bash
set -euo pipefail
BR=br-sdn
# Ensure controller is running first: bridge has secure fail mode (fail-closed).
systemctl is-active --quiet sdn-controller
ovs-vsctl --if-exists del-br "$BR"
for id in 1 2 3 4; do ip netns del "pc$id" 2>/dev/null || true; done
ovs-vsctl add-br "$BR"
ovs-vsctl set bridge "$BR" protocols=OpenFlow13
ovs-vsctl set-fail-mode "$BR" secure
ovs-vsctl set-controller "$BR" tcp:127.0.0.1:6653
for id in 1 2 3 4; do
  if [[ "$id" -le 2 ]]; then segment=10; else segment=20; fi
  ip netns add "pc$id"
  ip link add "veth$id" type veth peer name "eth0" netns "pc$id"
  ip link set "veth$id" up
  ip -n "pc$id" link set lo up
  ip -n "pc$id" link set eth0 address "$(printf '02:00:00:00:%02d:%02d' "$segment" "$id")"
  ip -n "pc$id" addr add "192.168.$segment.$id/24" dev eth0
  ip -n "pc$id" link set eth0 up
  ovs-vsctl add-port "$BR" "veth$id" -- set Interface "veth$id" ofport_request="$id"
done
# Deliberate direct routes and static neighbor entries let us test an actual
# cross-segment OpenFlow DENY instead of merely relying on absent L3 routes.
ip -n pc1 route add 192.168.20.3/32 dev eth0
ip -n pc1 neigh replace 192.168.20.3 lladdr 02:00:00:00:20:03 dev eth0 nud permanent
ip -n pc3 route add 192.168.10.1/32 dev eth0
ip -n pc3 neigh replace 192.168.10.1 lladdr 02:00:00:00:10:01 dev eth0 nud permanent
# VLAN-like segmentation is enforced by the controller's allowed port groups;
# these namespaces have no IP route to the host EC2 network.
echo 'Topology ready: pc1/pc2 segment10; pc3/pc4 segment20.'
ovs-vsctl show
