#!/bin/bash
# 용도: Air oob-mgmt-server 준비를 한 번에 (Ansible·git·passlib 설치 → 레포 clone/pull → credentials.yml 준비)
# 실행 (oob-mgmt-server에서):
#   curl -fsSL https://raw.githubusercontent.com/ju-tech11/ai-fabric-labs/main/air/bootstrap_oob.sh | bash
#   브랜치 테스트:  curl ... /<브랜치>/air/bootstrap_oob.sh | BRANCH=<브랜치> bash
set -e
REPO=${REPO:-https://github.com/ju-tech11/ai-fabric-labs.git}
BRANCH=${BRANCH:-main}
T=${T:-compute-rail-nospine}
DIR=${DIR:-$HOME/ai-fabric-labs}

# 보라색 설치 창(커널/서비스 재시작 질문) 안 뜨게
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
sudo -E apt-get update -y
sudo -E apt-get install -y ansible sshpass git python3-passlib

if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin
  git -C "$DIR" checkout "$BRANCH"
  git -C "$DIR" pull --ff-only origin "$BRANCH"
else
  git clone -b "$BRANCH" "$REPO" "$DIR"
fi

C="$DIR/inventories/$T/group_vars/all/credentials.yml"
if [ ! -f "$C" ]; then
  cp "$C.example" "$C"
  echo ">> Created $C . Put the passwords in it:  nano $C"
else
  echo ">> $C already exists (kept as is)"
fi
# fast-rxe-test / fast-nccl-test 를 어디서나 실행할 수 있게
mkdir -p "$HOME/.local/bin"
ln -sf "$DIR/tests/soft-roce/fast-rxe-test" "$HOME/.local/bin/fast-rxe-test"
ln -sf "$DIR/tests/nccl/fast-nccl-test" "$HOME/.local/bin/fast-nccl-test"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc";; esac

echo ">> Ready:  cd $DIR && ansible all -m ping"
echo ">> Test commands: fast-rxe-test, fast-nccl-test  (first time: 'source ~/.bashrc' or log in again)"
