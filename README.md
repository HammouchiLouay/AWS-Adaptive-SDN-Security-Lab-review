> **Source/version note:** the included CloudFormation template uses OS-Ken 4.2.2, whereas the validated running lab was repaired with OS-Ken 3.1.1. See [deployment notes](docs/DEPLOYMENT_NOTES.md) before deploying.

# AWS Adaptive SDN — Real OpenFlow 1.3 Controller Lab

A self-contained **real SDN control-plane experiment** on AWS: a single Ubuntu 24.04 EC2 instance running **OS-Ken 4.2.2** (maintained Ryu-derived controller), **Open vSwitch**, and **four separate Linux network namespaces**. Deployed with **AWS CloudFormation**.

> This is an educational lab. The controller is not AWS VPC's controller. OpenFlow controls a **virtual Open vSwitch inside EC2**. CloudFormation provisions the EC2/VPC infrastructure. The same pattern could be deployed by Terraform, but this repository ships a CloudFormation stack.

## Diagram

```
AWS VPC 10.60.0.0/16
  |
  +-- Public subnet 10.60.1.0/24 (EC2 host, no inbound SG rules)
        |
        +-- Ubuntu 24.04 EC2 + SSM Session Manager
              |
              +-- OS-Ken adaptive controller (TCP 127.0.0.1:6653)
              |           OpenFlow 1.3 |
              +-- Open vSwitch br-sdn (fail_mode=secure)
                    |           |           |           |
                  veth1       veth2       veth3       veth4
                    |           |           |           |
                  pc1         pc2         pc3         pc4
                .10.1       .10.2       .20.3       .20.4
                 SEGMENT 10                SEGMENT 20
```

All PC hosts are Linux network namespaces, **not additional EC2 instances**. Their private lab IPs are 192.168.10.1, 192.168.10.2, 192.168.20.3, 192.168.20.4. They are isolated from the EC2 host's real AWS interface; the switch has no external network port.

## AWS deployment

1. Set an AWS Budget alert and choose a region (e.g., eu-west-3). This creates **billable EC2, EBS and public IPv4** resources; it does not create a NAT Gateway.
2. AWS CloudFormation > Create stack > With new resources > Upload `cloudformation/adaptive-sdn.yaml`.
3. Stack name `adaptive-sdn-lab`, InstanceType `t3.small`, Ubuntu AMI parameter default. Acknowledge **CAPABILITY_IAM**.
4. Submit. Wait until CloudFormation reports `CREATE_COMPLETE`. **This does not mean cloud-init has completed.**
5. EC2 > Instances > `adaptive-sdn-controller-ovs-lab` > Connect > **Session Manager**. No SSH key or inbound rule is required.
6. Check the in-guest setup:

```bash
sudo cloud-init status --wait
sudo cat /opt/sdn/installation-status
sudo systemctl status sdn-controller --no-pager
sudo ovs-vsctl show
sudo ip netns list
sudo ovs-ofctl -O OpenFlow13 dump-flows br-sdn
```

Expected `/opt/sdn/installation-status`: `SDN_SETUP_COMPLETE`. If missing, examine `sudo tail -100 /var/log/sdn-bootstrap.log`, `sudo journalctl -u sdn-controller -n 80 --no-pager`, and `sudo cloud-init status --long`.

## Demonstrations and tests

```bash
sudo /opt/sdn/run_tests.sh
```

Results to verify:
- PC1 to PC2: reachable (same segment 10)
- PC3 to PC4: reachable (same segment 20)
- PC1 to PC3: blocked by the **SDN controller** (a /32 route + static ARP deliberately ensure this is a controller policy drop, not merely absent routing)
- 12 rapid ICMP requests from PC1 to PC2: threshold crossed; controller pushes an OpenFlow `priority=200` port drop with `hard_timeout=20` seconds
- Normal ping during quarantine: blocked
- After the timeout: recovery without operator intervention

For clear screenshots, run each command separately:

```bash
sudo ip netns exec pc1 ping -c 2 192.168.10.2
sudo ip netns exec pc3 ping -c 2 192.168.20.4
sudo ip netns exec pc1 ping -c 2 -W 1 192.168.20.3  # fails by controller policy
sudo ip netns exec pc1 ping -c 12 -i 0.2 192.168.10.2
sudo journalctl -u sdn-controller --no-pager | grep QUARANTINE
sudo ovs-ofctl -O OpenFlow13 dump-flows br-sdn
# Wait >20 seconds from detection (no need to restart services)
sudo /opt/sdn/verify_recovery.sh
```

### How adaptation works

The controller receives switch Packet-In messages on OpenFlow 1.3 TCP/6653. It checks known source MAC/ingress port and destination segment, and returns Packet-Out only to approved destination port(s). Broadcast packets are contained in the source segment. It tracks **ICMP IP packets by ingress port**, and if it receives more than 8 in a sliding 5-second window, installs an OpenFlow drop rule (`priority=200`, `hard_timeout=20`). The switch then blocks all frames *from that ingress port* for 20 seconds **in the data plane**, without sending them to the controller. After the hardware/software switch timeout, it resumes controller-based forwarding. This is a simple adaptive anomaly rule, **not a validated DDoS detection algorithm**; legitimate rapid pings can trigger it.

### Security notes

- SSM login is protected by IAM; assign the human operator the minimum permissions needed to use Session Manager.
- EC2 Security Group has **zero inbound rules**. The controller listens only on loopback.
- The PC namespaces have no access to EC2's real Ethernet adapter, Internet or AWS instance metadata.
- Segmentation here is **controller-enforced port-based microsegmentation**, not real AWS VLANs. A single Open vSwitch is used.
- OS-Ken has no high-availability replica in this educational lab. On controller loss, OVS fail_mode `secure` prevents automatic standalone fallback, but previously installed rules (e.g., quarantine) can remain until expiration.
- The control channel uses unencrypted loopback TCP only; do not extend it to untrusted networks without secure channel protection.

## Troubleshooting

| Symptom | Likely action |
|---|---|
| CloudFormation `CREATE_COMPLETE`, no namespaces | EC2 cloud-init still installing; check bootstrap log |
| `osken-manager` import/dependency error | Check `journalctl -u sdn-controller`; pip installation may have failed |
| OVS not connected | `sudo ovs-vsctl show`, `sudo systemctl restart sdn-controller`, then `sudo /opt/sdn/setup_topology.sh` |
| Hosts cannot ping even within segment | Confirm source MAC and OpenFlow `ofport_request` 1–4; inspect `dump-flows` |
| Session Manager unavailable | Confirm IAM profile, public route/outbound HTTPS and SSM Agent status (`sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service`) |

## Cleanup

CloudFormation > select `adaptive-sdn-lab` > **Delete**. Check termination and EBS removal. The stack's EC2 host is disposable. Never leave the lab running unused.

## Known limitations

The example has been statically validated for Python syntax, Bash syntax and YAML structure, **but it has not been run against a live AWS account or an Open vSwitch instance in this environment**. AWS account quotas/region and Python package dependency changes may affect deployment. Verify `cloud-init` and controller logs before considering it successful.
