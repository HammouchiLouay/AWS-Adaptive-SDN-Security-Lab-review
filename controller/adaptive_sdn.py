"""Adaptive SDN lab using OS-Ken (Ryu-derived), OpenFlow 1.3.

Four namespaces behind one Open vSwitch. No production interfaces attached.
Static host-to-port identity provides deterministic segmentation; a per-port
ICMP threshold triggers temporary OpenFlow quarantine with hard_timeout.
"""
import logging
import time
from collections import defaultdict, deque

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.lib.packet import ethernet, ether_types, ipv4, packet
from os_ken.ofproto import ofproto_v1_3

LOG = logging.getLogger(__name__)

# OVS OpenFlow ports assigned with ofport_request by setup_topology.sh.
PORT_SEGMENT = {1: 10, 2: 10, 3: 20, 4: 20}
PORT_MAC = {
    1: '02:00:00:00:10:01',
    2: '02:00:00:00:10:02',
    3: '02:00:00:00:20:03',
    4: '02:00:00:00:20:04',
}
MAC_PORT = {mac: port for port, mac in PORT_MAC.items()}
WINDOW_SECONDS = 5.0
ICMP_LIMIT = 8  # >8 ICMP source packets within 5 seconds triggers quarantine.
QUARANTINE_SECONDS = 20


class AdaptiveSegmentation(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icmp_windows = defaultdict(deque)
        self.quarantined_until = {}

    @staticmethod
    def install_flow(dp, priority, match, actions=None, hard_timeout=0):
        proto, parser = dp.ofproto, dp.ofproto_parser
        instructions = ([parser.OFPInstructionActions(proto.OFPIT_APPLY_ACTIONS, actions)]
                        if actions is not None else [])
        dp.send_msg(parser.OFPFlowMod(
            datapath=dp, priority=priority, match=match,
            instructions=instructions, hard_timeout=hard_timeout,
            idle_timeout=0, table_id=0))

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_ready(self, ev):
        dp = ev.msg.datapath
        p = dp.ofproto_parser
        o = dp.ofproto
        self.icmp_windows.clear()
        self.quarantined_until.clear()
        # Fail closed: only packet-in for four known access ports.
        self.install_flow(dp, 0, p.OFPMatch(), [])
        for port in PORT_SEGMENT:
            self.install_flow(dp, 10, p.OFPMatch(in_port=port), [
                p.OFPActionOutput(o.OFPP_CONTROLLER, o.OFPCML_NO_BUFFER)])
        LOG.warning('SWITCH_CONNECTED dpid=%s OF1.3 controlled ports=%s',
                    dp.id, sorted(PORT_SEGMENT))

    def emit_packet(self, dp, in_port, frame, out_ports):
        parser = dp.ofproto_parser
        acts = [parser.OFPActionOutput(port) for port in out_ports]
        dp.send_msg(parser.OFPPacketOut(
            datapath=dp, buffer_id=dp.ofproto.OFP_NO_BUFFER,
            in_port=in_port, actions=acts, data=frame))

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ingress = msg.match.get('in_port')
        if ingress not in PORT_SEGMENT:
            return
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if eth is None or eth.ethertype in (ether_types.ETH_TYPE_LLDP, ether_types.ETH_TYPE_IPV6):
            return
        src = eth.src.lower()
        if PORT_MAC[ingress] != src:
            LOG.warning('SPOOF_DROP in_port=%s mac=%s', ingress, src)
            return
        now = time.monotonic()
        if now < self.quarantined_until.get(ingress, 0):
            return
        ip = pkt.get_protocol(ipv4.ipv4)
        if ip is not None and ip.proto == 1:  # ICMP
            q = self.icmp_windows[ingress]
            while q and q[0] <= now - WINDOW_SECONDS:
                q.popleft()
            q.append(now)
            if len(q) > ICMP_LIMIT:
                self.quarantined_until[ingress] = now + QUARANTINE_SECONDS
                self.icmp_windows[ingress].clear()
                self.install_flow(dp, 200, dp.ofproto_parser.OFPMatch(in_port=ingress),
                                  [], hard_timeout=QUARANTINE_SECONDS)
                LOG.warning('QUARANTINE host=PC%d segment=%d duration=%ds reason=icmp_threshold',
                            ingress, PORT_SEGMENT[ingress], QUARANTINE_SECONDS)
                return
        segment = PORT_SEGMENT[ingress]
        target = MAC_PORT.get(eth.dst.lower())
        if target is None:
            # Broadcast/unknown unicast is limited to *same* segment.
            output_ports = [n for n, s in PORT_SEGMENT.items()
                            if s == segment and n != ingress]
        elif PORT_SEGMENT[target] == segment and target != ingress:
            output_ports = [target]
        else:
            LOG.info('SEGMENT_DROP src=PC%d dest=%s segment=%d', ingress, eth.dst, segment)
            return
        if output_ports:
            self.emit_packet(dp, ingress, msg.data, output_ports)
