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
  Select the first server / HCA        ACTIVE인 HCA만 표시 (예: 1  rxe_a0  Eth  eth1  10.10.0.1/24)
  Select the second server / HCA
  Select the RDMA test (perftest)      ib_write_bw(기본) / ib_read_bw / ib_send_bw / *_lat
  Select the number of QPs             QP 수를 바로 입력: 1 / 2 / 4 / 8, 0 = 직접 입력 (기본: Soft-RoCE 1, 실장비 4)
  Select the message size              64KB / 1MB(기본) / 1GB / all(-a)
                                       메모리(크기 x 2 x QP)나 HCA 최대 메시지를 넘는 크기는 목록에서 빠짐
  Select the direction                 Unidirectional(기본) / Bidirectional(-b --report-both, TX·RX 따로)
[Preflight Check]  perftest / HCA (ACTIVE, Eth/IB, GID, link 속도) / RDMA network path (RoCE만, ping)
```
- 대역폭 테스트는 항상 `--report_gbits` (Gb/s), 측정 시간 10초 고정 (`DUR=20 fast-rxe-test`로 변경)
- 결과: 단방향 `Result: OK  BW average 385.20 Gb/s (1048576 bytes, 4 QP, 10 sec)  = 96% of 400 Gb/s`
- 양방향: `TX host2 -> host1`, `RX host1 -> host2`, `Total (TX + RX) ... of 2 x link`
- 링크 속도: Ethernet은 `/sys/class/net/<NIC>/speed`, IB는 HCA rate
- Soft-RoCE는 CPU 처리라 QP·메시지를 키우면 오히려 느려질 수 있음 (Air 숫자는 동작 확인용)
- 옵션: `EXTRA="..."`(perftest 옵션 추가), `TOPO=<토폴로지>`

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
