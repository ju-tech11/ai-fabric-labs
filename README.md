# ai-fabric-labs

DSX Air용 AI 패브릭 토폴로지 모음 + Ansible 배포/검증.
role·playbook은 공통이고, 토폴로지마다 `inventories/<이름>/` 하나씩 (원본 데모 저장소의 inventories/evpn_* 와 같은 방식).

## 토폴로지
| 이름 | 구성 |
|---|---|
| `compute-rail-nospine` | 리프 4 (2 플레인 × 2), DGX 4, rail L2 VLAN. 스파인·BGP·VXLAN 없음 (기본값) |

## 구조
```
inventories/<토폴로지>/
  hosts.yml                       장비 목록 (leaf / spine / servers)
  host_vars/<장비>.yml             장비별 값 (리프: id, plane, rails / 서버·스파인: id, plane)
  group_vars/all/common.yml       이 토폴로지의 규칙 (주소·포트·BGP·Air 사양·fabric_name)
  group_vars/all/credentials.yml  계정 (Git 제외, .example 복사)
playbooks/                        공통: deploy / validate / site / gen_topology, filter_plugins/fabric.py
roles/                            공통: nvue_fabric(스위치), server_netplan(서버)
topology/<토폴로지>/               생성된 Air import 파일(.json/.dot), links.md  ※ 직접 수정 금지
air/ztp_cumulus.sh                Air ZTP (스위치 초기 비밀번호)
tools/preview.py                  Ansible 없이 미리보기
```

## 이름·관리 IP (compute-rail-nospine)
| 장비 | hostname | eth0 (관리, /16) |
|---|---|---|
| 리프 | leaf-a-01, leaf-a-02, leaf-b-01, leaf-b-02 | 192.168.0.1 ~ .0.4 |
| 서버 | dgx-b300-01 ~ dgx-b300-04 | 192.168.10.1 ~ .10.4 |

- 관리 IP: `common.yml`의 `mgmt_ip_format` + host_vars `id`로 계산 → Air JSON의 `management_ip`/`management_mac`, Air OOB DHCP가 MAC 기준으로 고정 할당
- hostname: Air JSON의 `instructions`(executor: init)로 import 단계에서 지정 + Ansible이 한 번 더 고정
- Air JSON은 화면 붙여넣기 형식(`title`) 기준. API(`/api/v3/simulations/import/`)로 올릴 땐 `title` → `name`
- DOT에는 관리 IP·hostname 지정이 없음 → **import는 .json 사용**

## 실행 (예: compute-rail-nospine)
```
T=compute-rail-nospine
python3 tools/preview.py $T                                        # (노트북) 결과 확인
# Air: topology/$T/$T.json import → ZTP에 air/ztp_cumulus.sh → Start → Enable SSH
# oob-mgmt-server:
git clone <저장소> && cd ai-fabric-labs && sudo apt install -y ansible sshpass
cp inventories/$T/group_vars/all/credentials.yml{.example,}         # 비밀번호 입력
ansible -i inventories/$T/hosts.yml all -m ping
ansible-playbook -i inventories/$T/hosts.yml playbooks/deploy.yml -e nvue_dry_run=true
ansible-playbook -i inventories/$T/hosts.yml playbooks/site.yml
cat results/$T-summary.txt                                          # → Air Stop
```
`-i`를 생략하면 ansible.cfg의 기본값(compute-rail-nospine)이 쓰임.

## 새 토폴로지 추가
1. 비슷한 inventory 복사: `cp -r inventories/compute-rail-nospine inventories/<새이름>`
2. `common.yml`의 `fabric_name`과 규칙, `hosts.yml`, `host_vars` 수정
3. `python3 tools/preview.py <새이름>` → `preview/<새이름>/`을 `topology/<새이름>/`로 복사 → commit
(VXLAN 등 새 기능이 필요하면 roles/nvue_fabric/templates/features/ 에 조각 추가)

### 예: 스파인 있는 버전 (공통 role은 이미 지원, inventory만 추가하면 됨)
- `hosts.yml`의 switches 아래에 `spine:` 그룹 추가 (예: spine-a, spine-b)
- `host_vars/spine-a.yml` → `id: 101`, `plane: a` (spine-b도 같은 방식)
- `common.yml`:
  ```yaml
  fabric_name: compute-rail-spine
  uplink_ports: [swp63, swp64]          # 리프 쪽 업링크. 스파인 쪽 포트(swp1~)는 자동 계산
  bgp_asn_base: 65100                   # ASN = 65100 + id
  loopback_format: "10.255.0.{id}/32"
  graceful_restart_mode: helper-only
  bfd: {profile: bgp-underlay-bfd, detect_multiplier: 3, min_rx_interval: 300, min_tx_interval: 300}
  ```
- 업링크가 생기면 리프/스파인에 loopback·eBGP unnumbered·BFD가 자동으로 들어가고, 검증에 BGP 이웃 수가 추가됨

## 확인 필요
- VX에서 `qos roce` apply 실패 시 `roce_enabled: false`
- breakout/RoCE YAML 키 형식은 실장비 `nv config show -o yaml`로 한 번 대조
