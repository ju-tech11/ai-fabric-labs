# tests/ — 테스트 라이브러리

토폴로지(`inventories/<이름>/`)를 배포한 뒤, 그 토폴로지의 **서버들**에 테스트 도구를 설치하고 실행한다.
어떤 서버·NIC·IP에 설치할지는 inventory + `common.yml` + `playbooks/filter_plugins/fabric.py`가 자동으로 계산한다
(스위치용 `build/*/startup.yaml`과는 무관).

```
tests/
  fast_test.py          fast-rxe-test / fast-nccl-test 본체 (번호로 서버·HCA 골라 실행)
  soft-roce/            RoCE 장치 만들기 (Air 가상 NIC용 Soft-RoCE) + rail별 RDMA 대역폭
    install.yml         설치
    bw_test.yml         rail별 ib_write_bw 전체 자동
    fast-rxe-test       서버 2대·HCA를 골라 ib_write_bw 1번
    roles/soft_roce/
  nccl/                 NCCL + nccl-tests (soft-roce에 의존 → install.yml이 먼저 자동 실행)
    install.yml         설치·빌드
    run.yml             서버 1대 안에서 실행 (GPU 있는 서버만)
    fast-nccl-test      서버 2대·HCA를 골라 nccl-tests 2대 실행
    roles/nccl/
```

## 의존 관계
```
playbooks/site.yml (네트워크·서버 IP)  →  tests/soft-roce/install.yml  →  tests/nccl/install.yml
                                          (rdma_mode: soft 일 때만)        (soft-roce를 먼저 자동 실행)
```

## 실행 (oob-mgmt-server, 레포 최상위 폴더에서)
```
ansible-playbook tests/soft-roce/install.yml     # RDMA 장치
ansible-playbook tests/soft-roce/bw_test.yml     # rail별 대역폭 → results/<토폴로지>-rdma.txt
ansible-playbook tests/nccl/install.yml          # NCCL·nccl-tests (soft-roce 포함)
ansible-playbook tests/nccl/run.yml              # GPU 있을 때만 실행
fast-rxe-test                                    # 번호 선택 → ib_write_bw
fast-nccl-test                                   # 번호 선택 → nccl-tests 2대
```
- `fast-*` 명령은 `air/bootstrap_oob.sh`가 `~/.local/bin`에 연결해 둠 (없으면 `tests/soft-roce/fast-rxe-test`처럼 경로로 실행)
- 서버 접속은 Ansible(inventory·credentials.yml)을 그대로 씀 → 서버에 직접 로그인할 필요 없음
- 다른 토폴로지: `-i inventories/<이름>/hosts.yml`
- 일부 서버만: `--limit dgx-b300-01,dgx-b300-02`
- `rdma_mode`(soft / hw)는 `inventories/<토폴로지>/group_vars/all/common.yml`

## 새 테스트 추가
`tests/<이름>/` 폴더에 `install.yml`, (필요하면) `run.yml`, `roles/<이름>/`, `README.md`.
다른 테스트에 의존하면 `install.yml` 맨 위에 `- import_playbook: ../<의존>/install.yml`.
