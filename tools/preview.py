#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""용도: Ansible 없이(python3 + jinja2 + pyyaml) 생성 결과를 preview/<토폴로지>/ 에 미리 만든다. 장비 접속 없음.
실행: python3 tools/preview.py <토폴로지>      예) python3 tools/preview.py compute-rail-nospine"""
import glob, json, os, re, sys, types
import jinja2, yaml

R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if len(sys.argv) < 2:
    sys.exit("사용법: python3 tools/preview.py <토폴로지>\n가능: " + ", ".join(sorted(os.listdir(os.path.join(R, "inventories")))))
INV = "inventories/" + sys.argv[1]
m = types.ModuleType("ansible.errors"); m.AnsibleFilterError = type("AnsibleFilterError", (Exception,), {})
sys.modules.setdefault("ansible", types.ModuleType("ansible")); sys.modules["ansible.errors"] = m
sys.dont_write_bytecode = True  # __pycache__ 생성 안 함
sys.path.insert(0, os.path.join(R, "playbooks/filter_plugins"))
import fabric as fab  # noqa: E402

def load(p):
    return yaml.safe_load(open(os.path.join(R, p), encoding="utf-8")) or {}

def expand(name):  # leaf-a-[01:02] → leaf-a-01, leaf-a-02
    mt = re.match(r"(.*)\[(\d+):(\d+)\](.*)", name)
    if not mt:
        return [name]
    a, b, w = int(mt.group(2)), int(mt.group(3)), len(mt.group(2))
    return ["%s%0*d%s" % (mt.group(1), w, i, mt.group(4)) for i in range(a, b + 1)]

groups = {}
def walk(g, node):
    hosts = [h for k in (node or {}).get("hosts", {}) or {} for h in expand(k)]
    for c, sub in ((node or {}).get("children") or {}).items():
        hosts += walk(c, sub)
    groups[g] = hosts
    return hosts
walk("all", load(INV + "/hosts.yml")["all"])

gv = load(INV + "/group_vars/all/common.yml")
for k in ("fabric", "fabric_links_all", "fabric_uplinks_all"):
    gv.pop(k)
gv["air_switch"]["os"] = gv["air_switch"]["os"].replace("{{ cl_version }}", gv["cl_version"])
hv = {h: dict(load(INV + "/host_vars/%s.yml" % h), inventory_hostname=h) for h in groups["all"]}
f = {k: gv[k] for k in ("rail_count", "planes", "vlan_base", "server_ip_format", "prefix_len", "server_iface_format",
                        "subports_per_cage", "switch_cage_count", "leaf_parent_format", "leaf_port_format", "uplink_ports")}
leaves, spines, servers = ([hv[h] for h in groups.get(g, [])] for g in ("leaf", "spine", "servers"))
ctx = dict(gv, groups=groups, hostvars=hv,
           fabric_links_all=fab.fabric_links(leaves, servers, f, gv["server_iface_map"]),
           fabric_uplinks_all=fab.fabric_uplinks(leaves, spines, f))

env = jinja2.Environment(loader=jinja2.FileSystemLoader(
    [os.path.join(R, p) for p in ("roles/nvue_fabric/templates", "roles/server_netplan/templates", "playbooks/templates")]),
    trim_blocks=True, undefined=jinja2.StrictUndefined)
env.filters["to_nice_json"] = lambda o, indent=2: json.dumps(o, indent=indent)
env.filters["combine"] = lambda a, b: dict(a, **b)
out = os.path.join(R, "preview", sys.argv[1]); os.makedirs(out, exist_ok=True)

def render(tpl, name, check=None, **extra):
    text = env.get_template(tpl).render(**dict(ctx, **extra))
    if check:
        check(text)
    open(os.path.join(out, name), "w", encoding="utf-8").write(text)

render("topology.dot.j2", gv["fabric_name"] + ".dot")
render("topology.json.j2", gv["fabric_name"] + ".json", json.loads)
render("links.md.j2", "links.md")
for h in groups["switches"]:
    render("startup.yaml.j2", h + "-startup.yaml", yaml.safe_load, **hv[h])
for h in groups["servers"]:
    render("60-rail-fabric.yaml.j2", h + "-netplan.yaml", yaml.safe_load, **hv[h])
print("서버 링크 %d개, 업링크 %d개 → %s" % (len(ctx["fabric_links_all"]), len(ctx["fabric_uplinks_all"]), out))
