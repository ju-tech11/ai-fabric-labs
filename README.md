# gpu-rail-fabric

DSX Air용 rail-optimized GPU fabric (리프 4 · 스파인 2 · DGX 4) + Ansible 배포/검증.

## 구조
```
inventory/
  hosts.yml                    장비 목록 (leaf / spine / servers)
  host_vars/<장비>.yml          장비별 값: id, plane, rails
  group_vars/all/common.yml    공통 규칙 (주소·포트·BGP·환경)
  group_vars/all/credentials.yml  계정 (Git 제외)
playbooks/
  filter_plugins/fabric.py     포트·IP·VLAN 계산 (모든 템플릿이 이 결과만 사용)
  gen_topology.yml             Air 토폴로지(.dot/.json) 생성
  deploy.yml / validate.yml / site.yml
roles/nvue_fabric              스위치: startup.yaml.j2 + features/*.j2
roles/server_netplan           서버: netplan + sysctl
topology/                      생성된 토폴로지, links.md(링크 표)
air/ztp_cumulus.sh             Air ZTP (스위치 초기 비밀번호)
tools/preview.py               Ansible 없이 미리보기
```

## 실행 순서
1. (노트북) `python3 tools/preview.py` 로 결과 확인
2. Air: `topology/gpu-rail-fabric.json` import → ZTP에 `air/ztp_cumulus.sh` → Start → Enable SSH
3. oob-mgmt-server: `git clone <저장소>` → `sudo apt install -y ansible sshpass`
4. `credentials.yml.example` → `credentials.yml` 복사 후 비밀번호 입력, `ansible all -m ping`
5. `ansible-playbook playbooks/deploy.yml -e nvue_dry_run=true` (diff만) → `ansible-playbook playbooks/site.yml`
6. `cat results/summary.txt` → Air Stop

## 확장 / 실장비
- 장비 추가: hosts.yml 범위 + host_vars 파일 추가 (규칙이 맞지 않으면 필터가 에러로 멈춤)
- 실장비: inventory 폴더 복사 → common.yml에서 `breakout_enabled: true`, `mgmt_mode: static`, `server_iface_map` 수정

## 확인 필요
- VX에서 `qos roce` apply 실패 시 `roce_enabled: false`
- breakout/RoCE의 YAML 키 형식은 실장비 `nv config show -o yaml`로 한 번 대조
