# Deployment caveat: OS-Ken version

The validated AWS lab discussed in the presentation ran **OS-Ken 3.1.1** after repairing an initial cloud-init setup. The historical repository's CloudFormation template and README currently install/describe **OS-Ken 4.2.2**. The exact checked-in CloudFormation template was **not validated as reproducible end-to-end** with that version, so don't claim the template deploys the demonstrated system without a compatibility test. `CREATE_COMPLETE` on AWS does not imply cloud-init finished.

Verified behavior on the repaired instance: OpenFlow 1.3 controller on 127.0.0.1:6653, OVS `br-sdn`, pc1↔pc2 and pc3↔pc4 allowed, cross-segment blocked, >8 ICMP packet threshold / 5 seconds triggers a priority-200 ingress port drop with 20-second hard timeout, then automatic recovery.

To publish the exact validated deployment, replace the bootstrap installation and service versions with the tested files exported from the working EC2 instance, redeploy in a fresh test stack, and only then mark the template verified.
