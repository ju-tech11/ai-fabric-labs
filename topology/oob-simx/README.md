# oob-simx — OOB 관리 패브릭 + SimX/BlueField 랩

DSX Air에서 **OOB 관리 패브릭을 테스트 대상으로** 세우는 랩.
SN2201 리프 2대 + SN4700 스파인 2대에 EVPN-VXLAN + VRF로 테넌트를 나누고,
서버에는 SimX ConnectX-7과 BlueField-3 DPU를 붙인다.

`compute-rail-nospine`과 겹치지 않는다. 저쪽은 rail L2, 이쪽은 L3 + 오버레이.

## 파일 2개

| 파일 | 토폴로지 | 보는 것 | vCPU | RAM |
|---|---|---|---|---|
| `oob-simx-t1-split.json` | 호스트 2, 스위치 0 | **DPU OS가 호스트 OS와 별도로 뜨고 ssh로 따로 들어가지는가** | 16 | 32 GB |
| `oob-simx.json` | 호스트 2 + 리프 2 + 스파인 2 | **EVPN-VXLAN + VRF로 OOB가 분리되는가** | 31 | 55 GB |

**t1을 먼저 한다.** 메인 랩이 실패하면 원인이 이미지인지 스위치 설정인지 구분이 안 된다.
t1은 파트너 문서의 `dpu-dpu` 예제와 거의 같은 모양이라, 여기서 막히면 원인은 이미지 권한이다.

t1에 파일이 필요한 이유는 테스트마다 파일을 두려는 게 아니라, **Air GUI 토폴로지 빌더에
SimX/BlueField 옵션이 없기 때문**이다 (`network_pci`, `emulation_type`, `simulator_image`는
JSON import 전용). GUI 서버 노드 속성에 DPU 항목이 보이면 t1 파일은 버려도 된다.

## 서버 포트 구성

실장비(1 DPU dual-port + CX 8 + LOM 1)를 축소한 것.

| 포트 | 역할 | 소속 | 메인 랩에서 붙는 리프 |
|---|---|---|---|
| `eth1` | 호스트 OS 관리 (LOM) | 호스트 노드 | Leaf1 |
| `eth2` | 호스트 BMC 모사 | 호스트 노드 | Leaf2 |
| `dpu1 oob_net0` | **DPU OS(ARM) 관리** | BF 카드 1G RJ45 | Leaf1 |
| `dpu1 p0` / `p1` | DPU 데이터 업링크 | BF 카드 | Leaf1 / Leaf2 |
| `nic1 p0` / `p1` | ConnectX-7 — OOB에 안 씀, 향후 테스트용 | CX 카드 | Leaf1 / Leaf2 |

**이더넷 포트를 줄이지 않은 이유**: 비용이 0이다.
`network_pci`에서 `cpu`/`memory`/`os`를 갖는 건 `DPU_ETHERNET`뿐이고 그것만 별도 VM이 된다.
`NIC_ETHERNET`(CX)과 호스트 virtio 포트는 사실상 무료.

BF 카드 자체의 BMC 포트는 넣지 않았다 — SimX가 링크 가능한 인터페이스로 노출하는지 미확인.

`p1` 계열을 Leaf2에 물리므로 EVPN multihoming 쌍이 자연스럽게 생긴다.

## 테넌트 설계

| VRF | 용도 | VLAN | L2VNI | L3VNI | 서브넷 | 포트 |
|---|---|---|---|---|---|---|
| `t_ipmi` | BMC/IPMI, PDU | 110 | 10110 | 10010 | 10.110.0.0/24 | `eth1`, `eth2` |
| `t_dpu` | DPU ARM 관리 | 120 | 10120 | 10020 | 10.120.0.0/24 | `dpu1 oob_net0` |
| `t_data` | DPU 데이터 | 130 | 10130 | 10030 | 10.130.0.0/24 | `dpu1 p0`, `p1` |
| `t_compute` | CX — 분리 확인용 | 140 | 10140 | 10040 | 10.140.0.0/24 | `nic1 p0`, `p1` |

언더레이: eBGP unnumbered + BFD. ASN 리프 65101/65102, 스파인 65201/65202.
loopback `10.255.1.{id}/32`. 오버레이: BGP `l2vpn-evpn`, VTEP = loopback.

링크·포트·IP 전체 표는 [links.md](links.md).

## 실행

```bash
T=oob-simx
# 1) Air: topology/$T/oob-simx-t1-split.json import -> Start -> 아래 t1 확인
# 2) 통과하면 topology/$T/oob-simx.json import
#    ZTP에 air/ztp_cumulus.sh 넣고 Start -> Enable SSH
# 3) oob-mgmt-server:
curl -fsSL https://raw.githubusercontent.com/ju-tech11/ai-fabric-labs/main/air/bootstrap_oob.sh | T=$T bash
```

### t1 — DPU OS 분리 확인

호스트에서:

```bash
lspci | grep -i -E 'mellanox|bluefield'
ibv_devinfo
ls /dev/rshim*
ip -br link
```

그다음 ARM에 들어간다. 접속 경로가 둘 중 하나일 것:

- Air 노드 목록에 BF가 **별도 노드로** 뜨면 그쪽 콘솔로 바로
- 아니면 호스트에서 RShim 경유 (`/dev/rshim0/console`, 또는 `ssh ubuntu@192.168.100.2`)

통과 기준: `ibv_devinfo`에 mlx5 장치가 뜨고, **ARM 쉘에 호스트와 별개로 들어간다**.
어느 경로였는지 기록해둘 것 — 메인 랩에서 ARM 관리망 설계가 거기에 달렸다.

ARM에서 인터페이스 구성도 같이 본다. 호스트 representor(`pf0hpf`)와 업링크(`p0`)가
둘 다 보이면 DPU 모드로 뜬 것:

```bash
ip -br link
ovs-vsctl show
```

### 메인 랩 — 패브릭 분리 확인

```bash
nv show vrf default router bgp neighbor
nv show vrf default router bgp address-family l2vpn-evpn
nv show evpn vni
```

| 출발 | 목적지 | 기대 |
|---|---|---|
| host-01 `eth1` | host-02 `eth1` | 통신 |
| host-01 `dpu1 oob_net0` | host-02 `dpu1 oob_net0` | 통신 |
| host-01 `eth1` | host-02 `dpu1 oob_net0` | **차단** |
| host-01 `dpu1 p0` | host-02 `nic1 p0` | **차단** |

리프 1대를 내렸을 때(`nv action shutdown`) 같은 VRF 통신이 유지되는지도 같이 본다.

### 범위 밖

- **NCCL**: Air에 GPU가 없어 `nccl-tests`가 안 돌아간다. RDMA(perftest)까지만
- **IB 스위치**: SimX는 ConnectX NIC / BlueField DPU / 이더넷 스위치만 에뮬레이션.
  QM9700 이미지는 Air에 없음

## BlueField 모드 전환 (t1에서)

```bash
mlxconfig -d /dev/mst/mt41692_pciconf0 -e q
mlxconfig -d /dev/mst/mt41692_pciconf0 s INTERNAL_CPU_MODEL=1 INTERNAL_CPU_OFFLOAD_ENGINE=1
```

적용에는 graceful shutdown + power cycle이 필요하고, **BF-3는 NIC 모드에서 ARM OS가 부팅하지 않는다**.
NIC 모드로 바꾸는 순간 ARM 접속이 끊기므로 복귀는 호스트 쪽에서:

```bash
mlxconfig -d /dev/mst/mt41692_pciconf0 s INTERNAL_CPU_MODEL=1 INTERNAL_CPU_OFFLOAD_ENGINE=0
```

SimX에서 `mlxconfig` 쓰기가 영속되는지는 미지수. 안 되면 토폴로지 JSON에서
모드를 지정하는 방식일 가능성이 크다.

## 재생성

JSON은 손으로 쓴 게 아니라 생성기가 만든다. `tools/preview.py`는 plane/rail 모델 전용이라
이 모양을 못 만들어서 이 랩만 독립 생성기를 둔다.

```bash
python3 topology/oob-simx/gen_oob_simx.py topology/oob-simx
```

링크 엔드포인트 검증과 리소스 합계를 같이 출력한다.
상수(`SIMX_IMAGE`, `BF_IMAGE`, `DPU_SPEC`, `PORTS`, `HOSTS`)만 고치면 둘 다 갱신된다.

## import 전 확인

- **이미지 이름**: org의 Images 탭 실제 값으로 맞춰둠 (2026-11-06 확인).
  `simx-nic-26.7-1104_x86_64`, `bf-bundle-3.4.0-50_26.04_ubuntu-22.04_prod.img`.
  둘 다 Visibility `Internal`. 파트너 문서 예제는 더 오래된 버전(`simx-nic-26.10-1021`,
  `bf-bundle-3.0.0-135_25.04`)을 쓰는데 이 org에는 없다 — 문서 예제를 그대로 import하면
  에러 없이 노드가 통째로 사라지니 주의
- **`oob_net0`**: BF ARM의 OOB 인터페이스를 토폴로지 링크로 지정할 수 있는지 미확인.
  파트너 문서는 `p0`/`p1`만 예시로 든다. import가 거부하면 그 링크만 지우고
  ARM 관리는 Air 자동 OOB에 맡길 것:
  ```bash
  python3 -c "import json;p='topology/oob-simx/oob-simx.json';d=json.load(open(p));d['content']['links']=[l for l in d['content']['links'] if all(e.get('interface')!='oob_net0' for e in l)];json.dump(d,open(p,'w'),indent=4)"
  ```
- **`number_of_ports: 2`**: 문서 템플릿에는 DPU에만 있다. CX(`NIC_ETHERNET`)에서도
  받는지 미확인 → 실패하면 CX를 1포트로 줄일 것
- **DPU 사양**: 문서 `dpu-dpu` 예제 값(4 vCPU / 8 GB). ARM이 안 뜨면 문서 최종
  템플릿 값(16 / 32768)으로 올릴 것
- **관리 IP**: `192.168.1.x` / `192.168.11.x` — `compute-rail-nospine`
  (`192.168.0.x` / `192.168.10.x`)과 겹치지 않게 분리했다
- **대문자 호스트명**: `OOB-Leaf1` 등은 요청 네이밍 그대로. Ansible 인벤토리는
  대소문자를 구분하니 인벤토리 추가 시 표기 통일할 것

Ansible 인벤토리와 NVUE 피처(`vxlan`, `evpn`, 테넌트 `vrf`)는 아직 없다.
t1이 통과한 다음에 추가한다.
