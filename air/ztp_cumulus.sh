#!/bin/bash
# CUMULUS-AUTOPROVISIONING
# 용도: Air ZTP. 스위치 첫 부팅 때 cumulus 비밀번호를 정해 Ansible이 바로 접속하게 함
#       CHANGE_ME = inventory/group_vars/all/credentials.yml 의 switch_password
echo 'cumulus:CHANGE_ME' | chpasswd
exit 0
