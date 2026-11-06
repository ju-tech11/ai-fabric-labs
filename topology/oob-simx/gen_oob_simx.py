#!/usr/bin/env python3
r"""
Generate NVIDIA DSX Air import JSON for the oob-simx lab.

Two topologies. Run t1 first.

  oob-simx-t1-split   host 2, no switch
                      Does the BlueField ARM come up as its own OS, reachable
                      separately from the host OS? Needed as a JSON file because
                      SimX / BlueField options are not available in the Air GUI
                      topology builder.

  oob-simx            host 2 + OOB-Leaf1/2 + OOB-Spine1/2
                      The real lab. EVPN-VXLAN + VRF: does the separation hold
                      across leaves?

Per-server ports, modelled on a real node scaled down:

    eth1              host OS management (motherboard LOM)
    eth2              host BMC (modelled with a second virtio port)
    dpu1 oob_net0     BlueField ARM OS management (the card's 1G RJ45)
    dpu1 p0 / p1      BlueField data uplinks (dual port)
    nic1 p0 / p1      ConnectX-7, unused for OOB -- kept for later tests

Only the DPU costs real resources. Ethernet ports and the ConnectX NIC are
effectively free, so they are not trimmed.
"""

import json

# ---------------------------------------------------------------- images
# Replace with the image names your Air org actually has access to.
SIMX_IMAGE = "simx-nic-26.7-1104_x86_64"
BF_IMAGE = "bf-bundle-3.4.0-50_26.04_ubuntu-22.04_prod.img"
CL_VERSION = "cumulus-vx-5.16.1"
HOST_OS = "generic/ubuntu2204"

# ---------------------------------------------------------------- sizing
# DPU_SPEC matches the 'BlueField DPU Emulation' example in the partner
# collateral. If the ARM does not boot, raise it to the larger values used by
# that document's final template (cpu 16 / memory 32768).
DPU_SPEC = {"cpu": 4, "memory": 8192, "storage": 20}
HOST_SPEC = {"cpu": 4, "memory": 8192, "storage": 20}
SWITCH_SPEC = {"cpu": 2, "memory": 4096, "storage": 20}
OOB_SPEC = {
    "server": {"cpu": 2, "memory": 2048, "storage": 20},
    "switch": {"cpu": 5, "memory": 5120, "storage": 20},
}

# ---------------------------------------------------------------- addressing
MGMT_IP = {"switch": "192.168.1.{id}", "server": "192.168.11.{id}"}
MGMT_MAC = {"switch": "44:38:39:23:01:{id:02x}", "server": "44:38:39:12:01:{id:02x}"}

LEAVES = [("OOB-Leaf1", 1), ("OOB-Leaf2", 2)]
SPINES = [("OOB-Spine1", 101), ("OOB-Spine2", 102)]
HOSTS = [("host-01", 1), ("host-02", 2)]
UPLINK_PORTS = ["swp49", "swp50"]

# leaf port groups: role -> first swp number
PORTS = {
    "host_os": 0,    # swp1, swp2    <- eth1
    "host_bmc": 5,   # swp6, swp7    <- eth2
    "dpu_os": 10,    # swp11, swp12  <- dpu1 oob_net0
    "dpu_p0": 20,    # swp21, swp22  <- dpu1 p0
    "dpu_p1": 30,    # swp31, swp32  <- dpu1 p1
    "cx_p0": 40,     # swp41, swp42  <- nic1 p0
    "cx_p1": 44,     # swp45, swp46  <- nic1 p1
}

LAYOUT = {"y_spine": 0, "y_leaf": 400, "y_host": 800, "y_oob": -275, "x0": 825, "dx": 550}


def switch_node(name, nid, role, x, y):
    return name, {
        **SWITCH_SPEC,
        "positioning": {"x": x, "y": y},
        "nic_model": "virtio",
        "cpu_mode": "custom",
        "cpu_options": [],
        "secureboot": False,
        "os": CL_VERSION,
        "labels": {"role": role},
        "management_mac": MGMT_MAC["switch"].format(id=nid),
        "management_ip": MGMT_IP["switch"].format(id=nid),
        "oob": False,
        "storage_pci": {},
        "pxehost": False,
        "features": {"uefi": False},
    }


def host_node(name, nid, x, y, mgmt=True):
    body = {
        "emulation_type": "HOST",
        **HOST_SPEC,
        "positioning": {"x": x, "y": y},
        "nic_model": "virtio",
        "cpu_mode": "custom",
        "cpu_options": [],
        "secureboot": False,
        "os": HOST_OS,
        "labels": {"role": "server"},
        "simulator_image": SIMX_IMAGE,
        "network_pci": {
            "nic1": {
                "emulation_type": "NIC_ETHERNET",
                "model": "connectx7",
                "number_of_ports": 2,
                "port_type": "ethernet",
                "simulator_image": SIMX_IMAGE,
            },
            "dpu1": {
                "emulation_type": "DPU_ETHERNET",
                "model": "bluefield3",
                "number_of_ports": 2,
                "port_type": "ethernet",
                "nic_model": "virtio",
                "os": BF_IMAGE,
                **DPU_SPEC,
                "cpu_arch": "x86",
                "simulator_image": SIMX_IMAGE,
            },
        },
    }
    if mgmt:
        body["management_mac"] = MGMT_MAC["server"].format(id=nid)
        body["management_ip"] = MGMT_IP["server"].format(id=nid)
        body["oob"] = False
        body["storage_pci"] = {}
        body["pxehost"] = False
        body["features"] = {"uefi": False}
    return name, body


def host_port_links(hosts, leaf_for):
    """leaf_for(role) -> leaf name. Returns host-to-leaf links."""
    links = []
    for idx, (host, _) in enumerate(hosts, start=1):
        plan = [
            ({"node": host, "interface": "eth1"}, "host_os"),
            ({"node": host, "interface": "eth2"}, "host_bmc"),
            ({"node": host, "network_pci": "dpu1", "interface": "oob_net0"}, "dpu_os"),
            ({"node": host, "network_pci": "dpu1", "interface": "p0"}, "dpu_p0"),
            ({"node": host, "network_pci": "dpu1", "interface": "p1"}, "dpu_p1"),
            ({"node": host, "network_pci": "nic1", "interface": "p0"}, "cx_p0"),
            ({"node": host, "network_pci": "nic1", "interface": "p1"}, "cx_p1"),
        ]
        for host_ep, role in plan:
            links.append([
                host_ep,
                {"node": leaf_for(role), "interface": "swp%d" % (PORTS[role] + idx)},
            ])
    return links


def oob_block():
    return {
        "nodes": {
            "oob-mgmt-server": {
                **OOB_SPEC["server"],
                "positioning": {"x": 1375, "y": LAYOUT["y_oob"]},
            },
            "oob-mgmt-switch": {
                **OOB_SPEC["switch"],
                "positioning": {"x": 1925, "y": LAYOUT["y_oob"]},
            },
        },
        "enable_dhcp": True,
    }


def wrap(title, nodes, links, with_oob=True):
    content = {"nodes": nodes, "links": links}
    if with_oob:
        content["oob"] = oob_block()
        content["instructions"] = [
            {"node": n, "executor": "init", "name": "hostname", "data": {"hostname": n}}
            for n in nodes
        ]
    else:
        content["oob"] = False
    return {"format": "JSON", "title": title, "ztp": "", "content": content}


# ---------------------------------------------------------------- t1
def build_t1(title):
    """Two hosts back to back, no switch, no Air OOB.

    Kept as close as possible to the partner collateral's 'dpu-dpu' example so
    that a failed import points at image access, not at this lab.
    """
    nodes = {}
    for i, (name, nid) in enumerate(HOSTS):
        n, body = host_node(name, nid, LAYOUT["x0"] + LAYOUT["dx"] * i * 2,
                            LAYOUT["y_host"], mgmt=False)
        body.pop("positioning", None)
        body.pop("labels", None)
        body.pop("cpu_mode", None)
        body.pop("cpu_options", None)
        body.pop("secureboot", None)
        nodes[n] = body
    links = [
        [
            {"node": "host-01", "network_pci": "dpu1", "interface": "p0"},
            {"node": "host-02", "network_pci": "dpu1", "interface": "p0"},
        ],
        [
            {"node": "host-01", "network_pci": "nic1", "interface": "p0"},
            {"node": "host-02", "network_pci": "nic1", "interface": "p0"},
        ],
    ]
    return wrap(title, nodes, links, with_oob=False)


# ---------------------------------------------------------------- the lab
def build_lab(title):
    """Two leaves, two spines. p0-side ports on Leaf1, p1-side on Leaf2."""
    nodes = {}
    for i, (name, nid) in enumerate(SPINES):
        x = LAYOUT["x0"] + int(LAYOUT["dx"] * (0.5 + i * 2))
        nodes.update(dict([switch_node(name, nid, "spine", x, LAYOUT["y_spine"])]))
    for i, (name, nid) in enumerate(LEAVES):
        x = LAYOUT["x0"] + LAYOUT["dx"] * i * 2
        nodes.update(dict([switch_node(name, nid, "leaf", x, LAYOUT["y_leaf"])]))
    for i, (h, hid) in enumerate(HOSTS):
        nodes.update(dict([
            host_node(h, hid, LAYOUT["x0"] + LAYOUT["dx"] * i * 2, LAYOUT["y_host"])
        ]))

    links = []
    for li, (leaf, _) in enumerate(LEAVES, start=1):
        for port, (spine, _) in zip(UPLINK_PORTS, SPINES):
            links.append([
                {"node": leaf, "interface": port},
                {"node": spine, "interface": "swp%d" % li},
            ])

    # p0-side roles land on Leaf1, p1-side roles on Leaf2
    leaf2_roles = {"host_bmc", "dpu_p1", "cx_p1"}
    links += host_port_links(
        HOSTS, lambda role: LEAVES[1][0] if role in leaf2_roles else LEAVES[0][0]
    )
    return wrap(title, nodes, links)


# ---------------------------------------------------------------- checks
def check(topo):
    nodes = topo["content"]["nodes"]
    errors, seen = [], {}
    for link in topo["content"]["links"]:
        if len(link) != 2:
            errors.append("link with %d endpoints" % len(link))
            continue
        for ep in link:
            n = ep["node"]
            if n not in nodes:
                errors.append("unknown node %r" % n)
                continue
            pci = ep.get("network_pci")
            if pci and pci not in nodes[n].get("network_pci", {}):
                errors.append("node %s has no network_pci %r" % (n, pci))
            key = (n, pci, ep["interface"])
            if key in seen:
                errors.append("interface used twice: %r" % (key,))
            seen[key] = True

    vcpu = mem = 0
    for n in nodes.values():
        vcpu += n.get("cpu", 0)
        mem += n.get("memory", 0)
        for p in n.get("network_pci", {}).values():
            vcpu += p.get("cpu", 0)
            mem += p.get("memory", 0)
    oob = topo["content"].get("oob")
    if isinstance(oob, dict):
        for n in oob.get("nodes", {}).values():
            vcpu += n.get("cpu", 0)
            mem += n.get("memory", 0)
    return errors, vcpu, mem


if __name__ == "__main__":
    import sys

    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    for fname, fn in [
        ("oob-simx-t1-split", build_t1),
        ("oob-simx", build_lab),
    ]:
        topo = fn(fname)
        errors, vcpu, mem = check(topo)
        with open("%s/%s.json" % (outdir, fname), "w") as f:
            json.dump(topo, f, indent=4)
            f.write("\n")
        nodes = len(topo["content"]["nodes"])
        if isinstance(topo["content"].get("oob"), dict):
            nodes += 2
        print("%-20s nodes=%-3d links=%-3d vCPU=%-3d RAM=%-3d GB  %s" % (
            fname, nodes, len(topo["content"]["links"]), vcpu, round(mem / 1024),
            "OK" if not errors else "ERRORS: " + "; ".join(errors),
        ))
