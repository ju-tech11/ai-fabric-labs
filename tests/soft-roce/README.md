# soft-roce — Soft-RoCE 설치와 rail별 RDMA 대역폭

Air처럼 RDMA 하드웨어가 없는 가상 NIC(e1000/virtio)에서 리눅스 커널의 Soft-RoCE(`rdma_rxe`)로 RoCEv2를 흉내 낸다.
`rdma_mode: hw`(실장비 ConnectX)면 설치를 건너뛴다.

## 설치되는 것 (서버)
| 순서 | 항목 | 내용 |
|---|---|---|
| 1 | apt: `rdma-core` | RDMA 기본 라이브러리·도구 (`rdma` 명령, libibverbs, librdmacm) |
| 1 | apt: `ibverbs-utils` | `ibv_devices`, `ibv_devinfo` |
| 1 | apt: `rdmacm-utils` | `rping` 등 연결 테스트 |
| 1 | apt: `perftest` | `ib_write_bw`, `ib_read_bw`, `ib_send_lat` |
| 1 | apt: `infiniband-diags` | `ibstat` 등 진단 |
| 2 | 커널 모듈 `rdma_rxe` | 없으면 `linux-modules-extra-$(uname -r)` 설치, `/etc/modules-load.d/rdma_rxe.conf`로 부팅 시 로드 |
| 3 | `/usr/local/sbin/rxe-setup.sh` | rail NIC마다 `rdma link add rxe_<plane><rail> type rxe netdev <NIC>` |
| 3 | systemd `rxe-setup` | 부팅 때 위 스크립트 실행 (재부팅해도 장치 유지) |

장치 이름: `rxe_a0`=eth1(plane A rail0), `rxe_b0`=eth2, … `rxe_b7`=eth16

## 실행
```
ansible-playbook tests/soft-roce/install.yml
ssh ubuntu@dgx-b300-01 "rdma link"              # 16개, state ACTIVE
ansible-playbook tests/soft-roce/bw_test.yml
cat results/compute-rail-nospine-rdma.txt
ansible-playbook tests/soft-roce/bw_test.yml -e rdma_test_server=dgx-b300-03 -e rdma_test_client=dgx-b300-04 -e rdma_test_duration=5
```

## fast-rxe-test (번호만 골라서 실행)
```
fast-rxe-test
  Select the first server for test     1  dgx-b300-01  192.168.10.1 ...
  Select the HCA for test              ACTIVE인 장치만 (예: 1  rxe_a0  eth1  10.10.0.1/24)
  Select the second server for test
  Select the HCA for test
  Select the RDMA test (perftest)      ib_write_bw(기본) / ib_read_bw / ib_send_bw / ib_write_lat / ib_read_lat / ib_send_lat
  Select the message size              대역폭: 64KB를 DUR초(기본) 또는 전체 크기(-a) / 지연: 2B(기본) 또는 전체 크기(-a)
[Preflight Check]  perftest / HCA (ACTIVE, Eth/IB, GID) / RDMA network path (RoCE만, ping)
```
- Ethernet(RoCE·Soft-RoCE)과 InfiniBand 모두 지원: 연결 정보는 관리망(host1 관리 IP)으로 주고받고, 측정 트래픽은 고른 HCA로
  - RoCE: 그 HCA의 RoCEv2 IPv4 GID 번호를 자동으로 찾아 `-x <GID>` 지정
  - IB: IP·GID 필요 없음
- 첫 서버에서 받는 쪽(백그라운드), 두 번째 서버에서 보내는 쪽(`... <host1 관리 IP>`) 실행 → 두 출력과 결과(Gb/s 또는 usec)를 여기서 표시
- 서브넷이 다른 HCA(다른 rail/plane)를 고르면 경고
- 옵션: `DUR=10`(측정 시간), `EXTRA="-q 4"`(perftest 옵션 추가), `TOPO=<토폴로지>`
- perftest는 점대점 측정 도구 → AllReduce 같은 집합통신은 fast-nccl-test

## 수동으로 한 rail만
```
# 받는 쪽 (dgx-b300-01)
ib_write_bw -d rxe_b7 -R
# 보내는 쪽 (dgx-b300-02)
ib_write_bw -d rxe_b7 -R 10.20.7.1
```
`-R`: IP로 연결(rdma_cm) → GID 번호 신경 안 써도 됨

## 주의
- Soft-RoCE는 CPU로 처리 → 대역폭 숫자 의미 없음, OK/FAIL만 본다
- VX 스위치는 ASIC이 없어 PFC/ECN이 실제로 동작하지 않음
- 실장비: `common.yml`에 `rdma_mode: hw`, `rdma_dev_map: {a-0: mlx5_0, ...}` → `bw_test.yml`은 그대로 사용
