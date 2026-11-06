# oob-simx 링크 표

`gen_oob_simx.py`가 만든 JSON과 같은 내용. 직접 수정하지 말고 생성기를 고칠 것.

## 리프 포트 그룹 (N = 호스트 번호)

| 호스트 포트 | 역할 | 리프 포트 |
|---|---|---|
| `eth1` | 호스트 OS 관리 (LOM) | `swp{N}` |
| `eth2` | 호스트 BMC 모사 | `swp{5+N}` |
| `dpu1 oob_net0` | DPU OS(ARM) 관리 | `swp{10+N}` |
| `dpu1 p0` | DPU 데이터 | `swp{20+N}` |
| `dpu1 p1` | DPU 데이터 | `swp{30+N}` |
| `nic1 p0` | ConnectX-7 | `swp{40+N}` |
| `nic1 p1` | ConnectX-7 | `swp{44+N}` |

## 관리망 (eth0, Air OOB DHCP가 MAC 기준 고정 할당)

| 장비 | id | eth0 | MAC |
|---|---|---|---|
| OOB-Leaf1 | 1 | 192.168.1.1 | 44:38:39:23:01:01 |
| OOB-Leaf2 | 2 | 192.168.1.2 | 44:38:39:23:01:02 |
| OOB-Spine1 | 101 | 192.168.1.101 | 44:38:39:23:01:65 |
| OOB-Spine2 | 102 | 192.168.1.102 | 44:38:39:23:01:66 |
| host-01 | 1 | 192.168.11.1 | 44:38:39:12:01:01 |
| host-02 | 2 | 192.168.11.2 | 44:38:39:12:01:02 |

## oob-simx-t1-split — 호스트 2대 직결

| A | B |
|---|---|
| `host-01 dpu1 p0` | `host-02 dpu1 p0` |
| `host-01 nic1 p0` | `host-02 nic1 p0` |

## oob-simx — 리프 2 + 스파인 2 (메인 랩)

| A | B |
|---|---|
| `OOB-Leaf1 swp49` | `OOB-Spine1 swp1` |
| `OOB-Leaf1 swp50` | `OOB-Spine2 swp1` |
| `OOB-Leaf2 swp49` | `OOB-Spine1 swp2` |
| `OOB-Leaf2 swp50` | `OOB-Spine2 swp2` |
| `host-01 eth1` | `OOB-Leaf1 swp1` |
| `host-01 eth2` | `OOB-Leaf2 swp6` |
| `host-01 dpu1 oob_net0` | `OOB-Leaf1 swp11` |
| `host-01 dpu1 p0` | `OOB-Leaf1 swp21` |
| `host-01 dpu1 p1` | `OOB-Leaf2 swp31` |
| `host-01 nic1 p0` | `OOB-Leaf1 swp41` |
| `host-01 nic1 p1` | `OOB-Leaf2 swp45` |
| `host-02 eth1` | `OOB-Leaf1 swp2` |
| `host-02 eth2` | `OOB-Leaf2 swp7` |
| `host-02 dpu1 oob_net0` | `OOB-Leaf1 swp12` |
| `host-02 dpu1 p0` | `OOB-Leaf1 swp22` |
| `host-02 dpu1 p1` | `OOB-Leaf2 swp32` |
| `host-02 nic1 p0` | `OOB-Leaf1 swp42` |
| `host-02 nic1 p1` | `OOB-Leaf2 swp46` |

