# -*- coding: utf-8 -*-
"""
용도: host_vars(리프의 plane/rails, 서버의 id, 스파인의 plane)와 group_vars/all/common.yml 규칙으로
      모든 링크를 계산한다. 스위치·서버 설정, Air 토폴로지, 검증이 전부 이 결과만 쓴다.

  서버 링크 : 리프 내 rail 순번 j, 노드 n → idx = j*N + (n-1)
             케이지 = idx // subports + 1, 하위 포트 = idx % subports → swp{케이지}s{하위}
             VLAN = vlan_base + rail, IP = 10.{octet}.{rail}.{node}
             서버 NIC 번호 = rail * 플레인수 + 플레인순번 + 1
  업링크   : 리프의 uplink_ports[k] ↔ 같은 플레인 스파인의 swp{(리프순번 * 업링크수) + k + 1}
"""
from ansible.errors import AnsibleFilterError


def _err(msg):
    raise AnsibleFilterError(msg)


def fabric_links(leaves, servers, f, iface_map=None):
    iface_map = iface_map or {}
    plane_idx = {p["name"]: i for i, p in enumerate(f["planes"])}
    octet = {p["name"]: p["octet"] for p in f["planes"]}
    servers = sorted(servers, key=lambda s: int(s["id"]))
    nodes = len(servers)
    sub = int(f["subports_per_cage"])

    # 플레인마다 rail 0~(rail_count-1)이 정확히 한 번씩 배정됐는지 검사
    for p in plane_idx:
        got = sorted(r for l in leaves if l["plane"] == p for r in l["rails"])
        if got != list(range(int(f["rail_count"]))):
            _err("plane %s의 rails 배정이 잘못됨: %s" % (p, got))

    links = []
    for leaf in leaves:
        name, p = leaf["inventory_hostname"], leaf["plane"]
        for j, rail in enumerate(leaf["rails"]):
            for n, srv in enumerate(servers, start=1):
                idx = j * nodes + (n - 1)
                cage = idx // sub + 1
                if cage > int(f["switch_cage_count"]):
                    _err("%s: 케이지 %d 필요 > %s개" % (name, cage, f["switch_cage_count"]))
                node = int(srv["id"])
                ifno = rail * len(plane_idx) + plane_idx[p] + 1
                links.append({
                    "plane": p, "rail": rail, "vlan": int(f["vlan_base"]) + rail,
                    "leaf": name, "leaf_cage": cage,
                    "leaf_parent_port": f["leaf_parent_format"].format(cage=cage),
                    "leaf_port": f["leaf_port_format"].format(cage=cage, sub=idx % sub),
                    "server": srv["inventory_hostname"], "node": node,
                    "server_iface_index": ifno,
                    "server_iface": iface_map.get("%s-%d" % (p, rail),
                                                  f["server_iface_format"].format(index=ifno)),
                    "server_ip": f["server_ip_format"].format(octet=octet[p], rail=rail, node=node),
                    "prefix": int(f["prefix_len"]),
                })
    return links


def fabric_uplinks(leaves, spines, f):
    ups = f["uplink_ports"]
    out = []
    for sp in spines:
        mine = sorted([l for l in leaves if l["plane"] == sp["plane"]], key=lambda l: int(l["id"]))
        for li, leaf in enumerate(mine):
            for k, lp in enumerate(ups):
                out.append({"plane": sp["plane"], "leaf": leaf["inventory_hostname"], "leaf_port": lp,
                            "spine": sp["inventory_hostname"],
                            "spine_port": "swp%d" % (li * len(ups) + k + 1)})
    return out


def fabric_ping_targets(links, server):
    """server에서 같은 플레인·같은 rail의 다른 서버로 보낼 ping 목록"""
    out = []
    for m in (l for l in links if l["server"] == server):
        for peer in links:
            if peer["plane"] == m["plane"] and peer["rail"] == m["rail"] and peer["server"] != server:
                out.append({"iface": m["server_iface"], "dst_ip": peer["server_ip"],
                            "dst_host": peer["server"], "plane": m["plane"], "rail": m["rail"]})
    return out


class FilterModule(object):
    def filters(self):
        return {"fabric_links": fabric_links, "fabric_uplinks": fabric_uplinks,
                "fabric_ping_targets": fabric_ping_targets}
