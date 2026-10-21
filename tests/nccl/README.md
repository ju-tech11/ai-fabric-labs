# nccl — NCCL + nccl-tests

RDMA 장치가 먼저 필요하므로 `install.yml`이 `../soft-roce/install.yml`을 먼저 실행한다 (`rdma_mode: hw`면 그 단계는 건너뜀).
NCCL은 **NVIDIA GPU가 있어야 실행**된다. Air 서버(generic/ubuntu2204 VM)는 GPU가 없어서 NCCL을 실행할 수 없다.
- `install.yml`: GPU가 없으면 NCCL 설치를 건너뜀 (설치 과정만 연습: `-e nccl_force=true`)
- `fast-nccl-test`: GPU가 없으면 `Cannot find GPU. Just printing the command.` 후 실행될 명령만 보여줌
- Air에서 RDMA 확인은 `fast-rxe-test` (perftest)

## 설치되는 것 (서버, 순서대로)
| 순서 | 항목 | 어디에 | 비고 |
|---|---|---|---|
| 0 | soft-roce 전체 | `../soft-roce` | rdma_mode: soft 일 때 |
| 0 | GPU 확인 | | 0EA면 아래 전부 건너뜀 |
| 1 | apt: `build-essential`, `git`, `wget` | 시스템 | make·gcc |
| 1 | apt: `openmpi-bin`, `libopenmpi-dev` | `/usr/bin/mpirun`, `/usr/lib/<arch>/openmpi` | 여러 서버 동시 실행용 MPI |
| 2 | GPU 드라이버 | | **점검만** (OK installed / NG). 없으면 수동 설치 (커널 모듈·재부팅 필요) |
| 2 | NVIDIA CUDA 저장소 (`cuda-keyring`) | `/usr/share/keyrings/` | NCCL·nvcc가 없을 때만 |
| 2 | apt: `libnccl2`, `libnccl-dev` | `/usr/lib/<arch>/libnccl.so.2`, `/usr/include/nccl.h` | 없을 때만. 툴킷(없으면 드라이버) CUDA 이하로 빌드된 최신 |
| 2 | apt: `cuda-nvcc-X-Y`, `cuda-cudart-dev-X-Y` | `/usr/local/cuda-X.Y` | 없을 때만. NCCL과 같은 CUDA 버전 |
| 3 | nccl-tests (GitHub) | `/opt/nccl-tests/build/*_perf` | `make MPI=1` (Air는 GPU 아키텍처 1개만 빌드) |
| 4 | `/etc/nccl.conf` | `/etc/` | GID 번호, TC 106, SOCKET_IFNAME |

- 없는 것을 설치할 때는 `No NCCL library. Installing libnccl2 <버전> ...` 처럼 구분선과 함께 먼저 알림
- 끝에 항목별 요약: `OK  already installed (버전)` / `OK  installed now (버전)` / `NG ...`
- 이미 있는 것은 그대로 사용 (덮어쓰지 않음)

## 실행
```
ansible-playbook tests/nccl/install.yml          # 오래 걸림 (nccl-tests 빌드)
ansible-playbook tests/nccl/run.yml              # GPU 있는 서버만, 서버 1대 안에서 all_reduce·alltoall
```

## fast-nccl-test (번호만 골라서 2대 실행)
```
fast-nccl-test
  Select the first server / HCA        HCA 목록 끝에 ALL (ACTIVE 전체, GPU 8개 측정용)
  Select the second server / HCA
  Select the NCCL test                 all_reduce(기본) / all_gather / reduce_scatter / alltoall / broadcast / reduce / sendrecv
  Select the algorithm (NCCL_ALGO)     Auto(기본) / Ring / Tree
  Select the max message size          1G / 8G(기본) / 16G
[Preflight Check] GPU
  host1 dgx-b300-01  GPU ........................................ 8EA      (0EA: "Cannot find GPU. Just printing the command." and stop)
[Preflight Check] CUDA / NCCL / MPI
  host1 dgx-b300-01  GPU driver ................................. OK  installed (570.86.15, supports CUDA 12.8)
  host1 dgx-b300-01  CUDA toolkit (nvcc) ........................ OK  installed (12.8)
  host1 dgx-b300-01  NCCL library (libnccl.so.2) ................ OK  installed (2.26.5, built for CUDA 12.8)
  host1 dgx-b300-01  driver CUDA vs toolkit/NCCL ................ OK  (12.8 >= 12.8)
  host1 dgx-b300-01  nccl-tests (all_reduce_perf) ............... OK  installed
  host1 dgx-b300-01  MPI (mpirun) ............................... OK  installed (4.1.2)
  host1 dgx-b300-01  HCA mlx5_0 ................................. ACTIVE  Eth  enp1s0np0 10.10.0.1/24
  (host2 동일)
  NCCL / CUDA toolkit / GPU driver version host1 = host2 ........ OK  same (...)
  RDMA network path (dgx-b300-02 enp1s0np0 → 10.10.0.1) ......... OK   (RoCE만)
  SSH without password host1 → host2 (mpirun) ................... OK
```
- NCCL·nccl-tests·MPI가 없으면 "지금 설치할까요?" → `tests/nccl/install.yml`을 그 두 서버에만 실행 후 다시 점검
- host1 → host2 비밀번호 없는 SSH 키 자동 등록 (mpirun용, 한 번만)
- host1에서 mpirun: 서버당 GPU 수만큼 프로세스(GPU 1개당 1개), 고른 HCA는 `NCCL_IB_HCA==<HCA>`, RoCE면 `NCCL_IB_GID_INDEX=<자동>`, 알고리즘은 `NCCL_ALGO`
- Ethernet(RoCE)과 InfiniBand 모두 같은 방식 (NCCL IB 전송은 둘 다 RDMA verbs 사용)
- 드라이버가 지원하는 CUDA < 툴킷/NCCL의 CUDA면 MISMATCH 경고 (흔한 실패 원인). install.yml은 드라이버가 있으면 그 CUDA 이하로 빌드된 NCCL을 고름
- 결과 `Avg bus bandwidth`를 여기서 표시. GPU가 없으면(Air) 실행할 명령만 보여줌
- 옵션: `NCCL_EXTRA="-x NCCL_DEBUG=INFO"`(mpirun 옵션 추가), `TOPO=<토폴로지>`

## 여러 서버 (실장비, rail·PXN 확인)
서버끼리 비밀번호 없이 SSH 되어야 함 (같은 경로에 nccl-tests)
```
mpirun -np 16 -H dgx-b300-01:8,dgx-b300-02:8 --bind-to none \
  -x NCCL_DEBUG=INFO /opt/nccl-tests/build/all_reduce_perf -b 8 -e 8G -f 2 -g 1
# PXN 비교: alltoall_perf 를 -x NCCL_PXN_DISABLE=0 / =1 로 각각
```

## 주의
- Air 서버 메모리 2GB → 빌드가 느리거나 실패하면 `common.yml`의 `air_server.memory` 를 늘려서 topology 재생성
- 장비의 NCCL이 오래된 버전이면 nccl-tests master 빌드가 실패할 수 있음 → `nccl_tests_version`을 맞는 태그로
