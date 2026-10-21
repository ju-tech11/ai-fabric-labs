#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
용도: oob-mgmt-server에서 번호만 골라 서버 2대 사이 테스트를 실행하고 결과를 여기서 보여준다.
      서버 접속은 Ansible(inventory·credentials.yml)을 그대로 사용 → 서버에 직접 들어갈 필요 없음
      Ethernet(RoCE, Soft-RoCE 포함)과 InfiniBand 모두 지원
  fast-rxe-test  : perftest (ib_write_bw, ib_send_lat ...) 점대점 측정
  fast-nccl-test : nccl-tests (all_reduce_perf, alltoall_perf ...) 서버 2대 MPI 실행
                   사전 점검(GPU·드라이버·CUDA·NCCL·nccl-tests·MPI·HCA·경로·SSH) → 없으면 설치 제안 → 실행 → 결과
옵션(환경변수):
  TOPO=<토폴로지>   다른 inventory 사용 (기본: ansible.cfg)
  DUR=10           perftest 대역폭 측정 시간(초)
  EXTRA="..."      perftest에 추가할 옵션 (QP 수·메시지 크기·방향은 메뉴에서 선택)
  NCCL_EXTRA="-x NCCL_DEBUG=INFO"   mpirun에 추가할 옵션
"""
import ipaddress
import os
import re
import shlex
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
os.chdir(ROOT)  # ansible.cfg(inventory, filter_plugins)를 쓰려고 레포 최상위에서 실행
INV = ["-i", "inventories/%s/hosts.yml" % os.environ["TOPO"]] if os.environ.get("TOPO") else []
ENV = dict(os.environ, ANSIBLE_STDOUT_CALLBACK="minimal", PYTHONWARNINGS="ignore",
           ANSIBLE_DEPRECATION_WARNINGS="False", ANSIBLE_HOST_KEY_CHECKING="False")
NCCL_DIR = "/opt/nccl-tests/build"


# ---------------------------------------------------------------- 공통
def remote(host, cmd, become=False, timeout=300):
    """서버에서 명령 실행 → (rc, 출력). Ansible이 SSH·비밀번호·sudo를 처리"""
    wrapped = "echo __B__; ( %s ) 2>&1; echo __E__$?" % cmd
    args = ["ansible", host] + INV + ["-m", "shell", "-a", wrapped] + (["-b"] if become else [])
    try:
        p = subprocess.run(args, capture_output=True, text=True, env=ENV, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "(timeout %ss)" % timeout
    m = re.search(r"__B__\n(.*?)__E__(\d+)", p.stdout, re.S)
    if not m:
        return 255, (p.stdout + p.stderr).strip()
    return int(m.group(2)), m.group(1).rstrip()


def kv(text):
    return dict(l.split("=", 1) for l in text.splitlines() if "=" in l)


def line(label, value, ok=True):
    mark = "" if ok else "   <-- check"
    print("  %s %s %s%s" % (label, "." * max(3, 62 - len(label)), value, mark))


def ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:2]) or (0,)


def ask(prompt):
    """입력 받기. 어느 질문에서든 q 를 입력하면 바로 종료"""
    s = input(prompt).strip()
    if s.lower() in ("q", "quit", "exit"):
        print("Quit.")
        sys.exit(0)
    return s


def pick(title, rows, default=None):
    print("\n" + title)
    for i, r in enumerate(rows, 1):
        print("  %2d  %s" % (i, "   ".join(r)))
    hint = " [Enter=%d]" % default if default else ""
    while True:
        s = ask("Enter number%s > " % hint)
        if not s and default:
            return rows[default - 1]
        if s.isdigit() and 1 <= int(s) <= len(rows):
            return rows[int(s) - 1]
        print("  Enter a number from 1 to %d" % len(rows))


def ask_yes(q, default=True):
    s = ask("%s [%s] > " % (q, "Y/n" if default else "y/N")).lower()
    return default if not s else s == "y"


def servers():
    p = subprocess.run(["ansible", "servers", "--list-hosts"] + INV, capture_output=True, text=True, env=ENV)
    hosts = [l.strip() for l in p.stdout.splitlines()[1:] if l.strip()]
    if not hosts:
        sys.exit("Cannot read the server list. Check the repo folder / inventory.\n" + p.stderr)
    out = []
    for h in hosts:
        g = subprocess.run(["getent", "hosts", h], capture_output=True, text=True)
        out.append((h, g.stdout.split()[0] if g.stdout.split() else h))
    return out


HCA_CMD = r"""
rdma link show; echo ---; ip -4 -o addr show; echo ---
for d in $(ls /sys/class/infiniband 2>/dev/null); do
  P=/sys/class/infiniband/$d/ports/1; ll=$(cat $P/link_layer 2>/dev/null); g=-
  if [ "$ll" = Ethernet ]; then
    for i in $(ls -v $P/gid_attrs/types 2>/dev/null); do
      [ "$(cat $P/gid_attrs/types/$i 2>/dev/null)" = "RoCE v2" ] || continue
      case $(cat $P/gids/$i) in 0000:0000:0000:0000:0000:ffff:*) g=$i; break;; esac
    done
  fi
  echo "$d $ll $g"
done
"""


def hcas(host):
    """링크가 ACTIVE인 RDMA 장치만: [dict(dev, link=Eth/IB, netdev, ip, gid)]
       Ethernet(RoCE)은 RoCEv2 IPv4 GID 번호도 찾음. InfiniBand는 IP·GID 불필요"""
    rc, out = remote(host, HCA_CMD)
    if rc != 0:
        sys.exit("%s: connection/command failed:\n%s" % (host, out))
    parts = (out.split("---") + ["", "", ""])[:3]
    ip = dict(re.findall(r"(?m)^\d+:\s+(\S+)\s+inet\s+(\S+)", parts[1]))
    attr = {l.split()[0]: l.split()[1:] for l in parts[2].splitlines() if len(l.split()) == 3}
    res = []
    for l in parts[0].splitlines():
        m = re.match(r"link\s+(\S+?)/\d+\s.*?state\s+(\S+)", l)
        if not m or m.group(2) != "ACTIVE":
            continue
        dev = m.group(1)
        nd = re.search(r"netdev\s+(\S+)", l)
        nd = nd.group(1) if nd else "-"
        ll, gid = attr.get(dev, ["Ethernet", "-"])
        res.append(dict(dev=dev, link="IB" if ll == "InfiniBand" else "Eth", netdev=nd, ip=ip.get(nd, "-"), gid=gid))
    return res


def hca_row(x):
    return (x["dev"], x["link"], x["netdev"], x["ip"])


def choose(allow_all=False):
    """서버·HCA 2쌍 선택. allow_all=True면 HCA 목록 끝에 '전체 ACTIVE HCA' 추가 (NCCL용)"""
    rows = servers()
    sel = {}
    for n, title in ((1, "first"), (2, "second")):
        cand = [r for r in rows if r[0] != sel.get("h1")]
        h, m = pick("Select the %s server for test" % title, cand)
        print("  %s : checking HCAs (ACTIVE only)..." % h)
        lst = hcas(h)
        if not lst:
            sys.exit("%s: no ACTIVE HCA (on Air run first: ansible-playbook tests/soft-roce/install.yml)" % h)
        rows_h = [hca_row(x) for x in lst]
        if allow_all:
            rows_h.append(("ALL", "-", "-", "all %d ACTIVE HCAs (NCCL assigns per GPU)" % len(lst)))
        r = pick("Select the HCA for test (%s)" % h, rows_h)
        x = next((y for y in lst if y["dev"] == r[0]), dict(dev="ALL", link=lst[0]["link"], netdev="-", ip="-", gid="-"))
        sel["h%d" % n], sel["m%d" % n], sel["x%d" % n] = h, m, x
    x1, x2 = sel["x1"], sel["x2"]
    print()
    for n in (1, 2):
        x = sel["x%d" % n]
        print("  host%d %-14s %s  %s  %s %s" % (n, sel["h%d" % n], x["dev"], x["link"], x["netdev"], x["ip"]))
    if x1["link"] != x2["link"]:
        sys.exit("  ! host1 is %s, host2 is %s. Both HCAs must be the same link type" % (x1["link"], x2["link"]))
    if "-" not in (x1["ip"], x2["ip"]):
        if ipaddress.ip_interface(x1["ip"]).network != ipaddress.ip_interface(x2["ip"]).network:
            print("  ! The two HCAs are in different subnets (different rail/plane) -> no path in this fabric")
            if not ask_yes("  Run anyway?", default=False):
                sys.exit(0)
    return sel


def check_path(sel):
    """Ethernet(RoCE)만: host2 HCA → host1 HCA IP로 ping (같은 rail로 연결돼 있는지)"""
    x1, x2 = sel["x1"], sel["x2"]
    if x1["link"] != "Eth" or "-" in (x1["ip"], x2["netdev"]):
        return
    a1 = x1["ip"].split("/")[0]
    rc, _ = remote(sel["h2"], "ping -c2 -W1 -I %s %s" % (x2["netdev"], a1))
    line("RDMA network path (%s %s -> %s)" % (sel["h2"], x2["netdev"], a1), "OK" if rc == 0 else "NG  ping failed", rc == 0)


def show(title, cmd, out):
    print("\n==== %s\n$ %s\n%s" % (title, cmd, out))


def rows_of(out):
    """perftest 결과 표의 숫자 행만"""
    return [l.split() for l in out.splitlines() if re.match(r"^\s*\d+\s+\d+\s+[\d.]+", l)]


# ---------------------------------------------------------------- fast-rxe-test
PERF = [  # (명령, 설명, 종류)
    ("ib_write_bw", "RDMA Write bandwidth (default)", "bw"),
    ("ib_read_bw", "RDMA Read bandwidth", "bw"),
    ("ib_send_bw", "Send/Recv bandwidth", "bw"),
    ("ib_write_lat", "RDMA Write latency", "lat"),
    ("ib_read_lat", "RDMA Read latency", "lat"),
    ("ib_send_lat", "Send/Recv latency", "lat"),
]
SIZES = [("64KB", 65536), ("1MB", 1048576), ("1GB", 1073741824)]
QPS = [1, 2, 4, 8]


def human(n):
    for u, d in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= d:
            return "%g %s" % (round(n / d, 1), u)
    return "%d B" % n


def link_gbps(host, x):
    """링크 속도(Gb/s): Ethernet은 NIC 속도(/sys/class/net/<NIC>/speed, Mb/s), IB는 HCA rate"""
    cmd = ("cat /sys/class/net/%s/speed 2>/dev/null" % x["netdev"] if x["netdev"] != "-"
           else "cat /sys/class/infiniband/%s/ports/1/rate" % x["dev"])
    _, out = remote(host, cmd)
    m = re.search(r"[\d.]+", out)
    if not m:
        return 0
    v = float(m.group(0))
    return v / 1000 if x["netdev"] != "-" else v


def host_limits(host, x):
    """(여유 메모리 bytes, HCA 최대 메시지 크기 bytes)"""
    _, out = remote(host, "awk '/MemAvailable/{print $2*1024}' /proc/meminfo; "
                          "ibv_devinfo -v -d %s 2>/dev/null | awk '/max_msg_sz/{print $2}'" % x["dev"])
    v = out.split()
    mem = int(v[0]) if v and v[0].isdigit() else 0
    msg = int(v[1], 16) if len(v) > 1 and v[1].startswith("0x") else 0
    return mem, msg


def fmt(v):
    return ("%g" % v) if v else "?"


def bw_rows(text):
    """perftest 결과 표의 숫자 행 [bytes, iterations, peak, average, msgrate]"""
    return [l.split() for l in text.splitlines() if re.match(r"^\s*\d+\s+\d+\s+[\d.]+\s+[\d.]+", l)]


def rxe_test():
    c = choose()
    tool = pick("Select the RDMA test (perftest)", [r[:2] for r in PERF], default=1)[0]
    kind = dict((r[0], r[2]) for r in PERF)[tool]
    soft = c["x1"]["dev"].startswith("rxe")      # rxe = Soft-RoCE, 그 외(mlx5 등) = 실장비 HCA
    bidi, qp, size_b, dur = False, 1, 0, 0

    if kind == "bw":
        # QP 수 → 메시지 크기(메모리·HCA 한도를 넘는 크기는 목록에서 뺌) → 방향. 측정 시간은 DUR(기본 10초)
        d_qp = 1 if soft else 4
        print("\nSelect the number of QPs (parallel RDMA connections)")
        for q in QPS:
            print("  %3d   %s" % (q, "(default on Soft-RoCE)" if soft and q == d_qp else
                                     "(default on hardware)" if not soft and q == d_qp else ""))
        print("  %3d   custom" % 0)
        while True:
            v = ask("Enter QPs [Enter=%d] > " % d_qp)
            if not v:
                qp = d_qp
                break
            if v == "0":
                v = ask("Number of QPs > ")
            if v.isdigit() and int(v) > 0:
                qp = int(v)
                break
            print("  Enter one of %s, or 0 for custom" % ", ".join(map(str, QPS)))

        lim = [host_limits(c["h%d" % n], c["x%d" % n]) for n in (1, 2)]
        mem = min(l[0] for l in lim if l[0]) if any(l[0] for l in lim) else 0
        msg = min(l[1] for l in lim if l[1]) if any(l[1] for l in lim) else 0
        sizes = [(name, b) for name, b in SIZES
                 if not (mem and b * 2 * qp > mem * 0.8) and not (msg and b > msg)]   # perftest 버퍼 = 크기 x 2 x QP
        rows = [(name, "(default)" if b == 1048576 else "") for name, b in sizes]
        rows.append(("all", "all sizes 2B ~ 8MB (-a)"))
        d_size = next((i + 1 for i, (_, b) in enumerate(sizes) if b == 1048576), 1)
        name = pick("Select the message size", rows, default=d_size)[0]
        size_b = dict(sizes).get(name, 0)

        bidi = pick("Select the direction", [
            ("Unidirectional", "host2 -> host1 (default)"),
            ("Bidirectional", "both directions at once, TX and RX shown separately")], default=1)[0] == "Bidirectional"
        dur = int(os.environ.get("DUR", "10")) if size_b else 0
        opt = "--report_gbits -q %d %s%s" % (qp, ("-s %d -D %d" % (size_b, dur)) if size_b else "-a",
                                             " -b --report-both" if bidi else "")
    else:
        size = pick("Select the message size", [
            ("2B", "default (smallest message latency)"),
            ("all", "all sizes 2B ~ 8MB (-a)")], default=1)[0]
        opt = "-a" if size == "all" else ""

    port = 18515 + int(time.time()) % 1000
    # 연결 정보 교환은 관리망(host1 관리 IP), 측정 트래픽은 고른 HCA로. RoCE는 RoCEv2 GID 지정, IB는 불필요
    gx = lambda x: "-x %s" % x["gid"] if x["link"] == "Eth" and x["gid"] != "-" else ""
    base = "-F -p %d %s %s" % (port, opt, os.environ.get("EXTRA", ""))
    srv_cmd = " ".join(("%s -d %s %s %s" % (tool, c["x1"]["dev"], gx(c["x1"]), base)).split())
    cli_cmd = " ".join(("%s -d %s %s %s %s" % (tool, c["x2"]["dev"], gx(c["x2"]), base, c["m1"])).split())

    print("\n[Preflight Check] perftest / HCA")
    for n in (1, 2):
        h, x = c["h%d" % n], c["x%d" % n]
        rc, _ = remote(h, "command -v %s" % tool)
        line("host%d %s  perftest (%s)" % (n, h, tool), "OK  installed" if rc == 0 else "NG  not installed", rc == 0)
        if rc != 0:
            sys.exit("  -> ansible-playbook tests/soft-roce/install.yml  (real hardware: apt install perftest)")
        x["gbps"] = link_gbps(h, x)
        line("host%d %s  HCA %s" % (n, h, x["dev"]),
             "ACTIVE  %s  %s %s%s  link %s Gb/s" % (x["link"], x["netdev"], x["ip"],
                                                   "  GID %s" % x["gid"] if x["link"] == "Eth" else "", fmt(x["gbps"])))
    check_path(c)

    wait = (dur or 60) + 300
    print("\nRunning: %s  %s (server) <- %s (client)" % (tool, c["h1"], c["h2"]))
    remote(c["h1"], "nohup timeout %d %s > /tmp/fast-rxe-test.log 2>&1 &" % (wait, srv_cmd), become=True)
    time.sleep(2)
    rc, out = remote(c["h2"], cli_cmd, become=True, timeout=wait + 60)
    time.sleep(1)
    _, sout = remote(c["h1"], "cat /tmp/fast-rxe-test.log", become=True)
    show("host1 %s (server)" % c["h1"], srv_cmd, sout)
    show("host2 %s (client)" % c["h2"], cli_cmd, out)

    if kind == "lat":
        rows = bw_rows(out + "\n" + sout)
        if rc != 0 or not rows:
            print("\nResult: FAIL (rc=%d)" % rc)
        else:
            best = min(rows, key=lambda r: float(r[5]))
            print("\nResult: OK  t_avg %s usec (%s bytes)" % (best[5], best[0]))
        return

    total = bw_rows(out.split("Local results:")[0])
    if rc != 0 or not total:
        print("\nResult: FAIL (rc=%d)" % rc)
        return
    link = min(c["x1"]["gbps"], c["x2"]["gbps"])
    pct = lambda v, l: "  = %d%% of %s Gb/s" % (round(float(v) / l * 100), fmt(l)) if l else ""
    best = max(total, key=lambda r: float(r[3]))
    head = "%s bytes, %d QP%s" % (best[0], qp, ", %d sec" % dur if dur else "")
    if not bidi:
        print("\nResult: OK  BW average %s Gb/s (%s)%s" % (best[3], head, pct(best[3], link)))
        return
    print("\nResult: OK  bidirectional (%s)" % head)
    if "Local results:" in out:
        loc = bw_rows(out.split("Local results:")[1].split("Remote results:")[0])
        rem = bw_rows(out.split("Remote results:")[1]) if "Remote results:" in out else []
        if loc:
            line("TX  %s -> %s" % (c["h2"], c["h1"]), "%s Gb/s%s" % (loc[-1][3], pct(loc[-1][3], link)))
        if rem:
            line("RX  %s -> %s" % (c["h1"], c["h2"]), "%s Gb/s%s" % (rem[-1][3], pct(rem[-1][3], link)))
    line("Total (TX + RX)", "%s Gb/s%s" % (best[3], pct(best[3], link * 2).replace("of ", "of 2 x link ")))


# ---------------------------------------------------------------- fast-nccl-test
NCCL_TESTS = [
    ("all_reduce_perf", "AllReduce (training gradient sync, default)"),
    ("all_gather_perf", "AllGather"),
    ("reduce_scatter_perf", "ReduceScatter"),
    ("alltoall_perf", "AlltoAll (MoE, cross-rail -> PXN check)"),
    ("broadcast_perf", "Broadcast"),
    ("reduce_perf", "Reduce"),
    ("sendrecv_perf", "SendRecv (point-to-point)"),
]
ALGOS = [
    ("Auto", "NCCL decides (default)"),
    ("Ring", "NCCL_ALGO=Ring"),
    ("Tree", "NCCL_ALGO=Tree (AllReduce only)"),
]
CHECK = r"""
echo gpu=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU')
echo drv=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
echo drvcuda=$(nvidia-smi 2>/dev/null | grep -oE 'CUDA Version: [0-9.]+' | awk '{print $3}')
N=$(command -v nvcc || ls -d /usr/local/cuda*/bin/nvcc 2>/dev/null | sort -V | tail -1)
echo toolkit=$([ -n "$N" ] && $N --version | grep -oE 'release [0-9.]+' | awk '{print $2}')
v=$(ls /usr/lib/*/libnccl.so.2.* /usr/local/lib/libnccl.so.2.* 2>/dev/null | head -1 | sed 's/.*libnccl.so.//'); echo nccl=$v
echo ncclcuda=$(dpkg-query -W -f='${Version}' libnccl2 2>/dev/null | grep -oE 'cuda[0-9.]+' | sed 's/cuda//')
[ -x %(bin)s ] && echo tests=installed || echo tests=
echo mpi=$(mpirun --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
echo sock=$(awk -F= '/^NCCL_SOCKET_IFNAME/{print $2}' /etc/nccl.conf 2>/dev/null)
"""


def build_cmd(c, binp, maxb, algo, ngpu, sock):
    """host1에서 실행할 mpirun 명령 (서버당 GPU 수만큼 프로세스, GPU 1개당 1개)"""
    def envs(x):  # 고른 HCA만 쓰게 + RoCE면 그 HCA의 RoCEv2 GID
        e = "" if x["dev"] == "ALL" else "-x NCCL_IB_HCA==%s " % x["dev"]
        if x["link"] == "Eth" and x["gid"] != "-":
            e += "-x NCCL_IB_GID_INDEX=%s " % x["gid"]
        return e + ("" if algo == "Auto" else "-x NCCL_ALGO=%s " % algo)
    app = "%s -b 8 -e %s -f 2 -g 1" % (binp, maxb)
    cmd = ("mpirun --bind-to none --mca plm_rsh_args '-o StrictHostKeyChecking=no' "
           "--mca btl_tcp_if_include {s} --mca oob_tcp_if_include {s} {extra} "
           "-np {g} -H {m1}:{g} {e1}-x NCCL_SOCKET_IFNAME={s} {app} : "
           "-np {g} -H {m2}:{g} {e2}-x NCCL_SOCKET_IFNAME={s} {app}").format(
        s=sock, app=app, g=ngpu, e1=envs(c["x1"]), e2=envs(c["x2"]), m1=c["m1"], m2=c["m2"],
        extra=os.environ.get("NCCL_EXTRA", ""))
    return " ".join(cmd.split())


def nccl_preflight(c, test, binp):
    """두 서버 점검 결과 출력 → (info, 없는 항목이 있는 서버 번호 목록, CUDA 불일치 여부)"""
    print("\n[Preflight Check] CUDA / NCCL / MPI")
    info, missing, bad = {}, [], False
    for n in (1, 2):
        h, x = c["h%d" % n], c["x%d" % n]
        _, out = remote(h, CHECK % {"bin": binp})
        i = info[n] = kv(out)
        val = lambda k, extra="": ("OK  installed (%s%s)" % (i[k], extra)) if i.get(k) else "NG  not installed"
        p = "host%d %s  " % (n, h)
        line(p + "GPU driver", val("drv", ", supports CUDA %s" % (i.get("drvcuda") or "?")), bool(i.get("drv")))
        line(p + "CUDA toolkit (nvcc)", val("toolkit"), bool(i.get("toolkit")))
        line(p + "NCCL library (libnccl.so.2)",
             val("nccl", ", built for CUDA %s" % i["ncclcuda"] if i.get("ncclcuda") else ""), bool(i.get("nccl")))
        need = max(ver(i.get("toolkit")), ver(i.get("ncclcuda")))
        if i.get("drvcuda") and need > (0,):
            ok = ver(i["drvcuda"]) >= need
            bad = bad or not ok
            need_s = ".".join(map(str, need))
            line(p + "driver CUDA vs toolkit/NCCL",
                 "OK  (%s >= %s)" % (i["drvcuda"], need_s) if ok else "NG  MISMATCH (driver %s < %s)" % (i["drvcuda"], need_s), ok)
        line(p + "nccl-tests (%s)" % test, "OK  installed" if i.get("tests") else "NG  not installed", bool(i.get("tests")))
        line(p + "MPI (mpirun)", val("mpi"), bool(i.get("mpi")))
        line(p + "HCA %s" % x["dev"], "ACTIVE  %s  %s %s" % (x["link"], x["netdev"], x["ip"]))
        if not all(i.get(k) for k in ("nccl", "tests", "mpi")):
            missing.append(n)
    for k, name in (("nccl", "NCCL"), ("toolkit", "CUDA toolkit"), ("drv", "GPU driver")):
        if info[1].get(k) and info[2].get(k):
            same = info[1][k] == info[2][k]
            line("%s version host1 = host2" % name,
                 "OK  same (%s)" % info[1][k] if same else "NG  DIFFERENT (%s / %s)" % (info[1][k], info[2][k]), same)
    return info, missing, bad


def nccl_test():
    c = choose(allow_all=True)
    test = pick("Select the NCCL test", NCCL_TESTS, default=1)[0]
    algo = pick("Select the algorithm (NCCL_ALGO)", ALGOS, default=1)[0]
    maxb = pick("Select the max message size", [("1G", "quick"), ("8G", "standard"), ("16G", "long")], default=2)[0]
    binp = "%s/%s" % (NCCL_DIR, test)

    print("\n[Preflight Check] GPU")
    g = {}
    for n in (1, 2):
        _, out = remote(c["h%d" % n], "nvidia-smi -L 2>/dev/null | grep -c '^GPU' || true")
        g[n] = int((out.strip() or "0").splitlines()[-1])
        line("host%d %s  GPU" % (n, c["h%d" % n]), "%dEA" % g[n], g[n] > 0)
    if not g[1] or not g[2]:
        ng = max(g[1], g[2], 1)
        print("\n  Cannot find GPU. Just printing the command.")
        print("  (No GPU -> CUDA/NCCL check and run skipped. On Air use fast-rxe-test for RDMA)")
        show("Command to run on host1 %s" % c["h1"], build_cmd(c, binp, maxb, algo, ng, "eth0"), "")
        return

    while True:
        info, missing, bad = nccl_preflight(c, test, binp)
        if not missing:
            break
        hosts = ",".join(c["h%d" % n] for n in missing)
        print("\n  NCCL / nccl-tests / MPI missing on: %s" % hosts)
        if not ask_yes("  Install now? (ansible-playbook tests/nccl/install.yml, may take a while)"):
            sys.exit(0)
        print("\n" + "-" * 64 + "\n Installing NCCL / CUDA toolkit / nccl-tests / MPI on %s ...\n" % hosts + "-" * 64)
        subprocess.run(["ansible-playbook", "tests/nccl/install.yml", "--limit", hosts] + INV, env=dict(os.environ))
        print("-" * 64 + "\n Install finished. Checking again\n" + "-" * 64)
    check_path(c)
    if bad:
        print("\n  ! NCCL/toolkit is built for a newer CUDA than the GPU driver supports. The test may fail")
        if not ask_yes("  Run anyway?", default=False):
            sys.exit(0)

    ngpu = min(int(info[1].get("gpu") or 1), int(info[2].get("gpu") or 1))
    cmd = build_cmd(c, binp, maxb, algo, ngpu, info[1].get("sock") or "eth0")

    # ---- mpirun용 SSH 키: host1 → host2 비밀번호 없이 (한 번만)
    _, pub = remote(c["h1"], "test -f ~/.ssh/id_ed25519 || ssh-keygen -q -t ed25519 -N '' -f ~/.ssh/id_ed25519; cat ~/.ssh/id_ed25519.pub")
    pub = pub.strip().splitlines()[-1]
    remote(c["h2"], "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && "
           "(grep -qxF %s ~/.ssh/authorized_keys || echo %s >> ~/.ssh/authorized_keys) && chmod 600 ~/.ssh/authorized_keys"
           % (shlex.quote(pub), shlex.quote(pub)))
    rc, _ = remote(c["h1"], "ssh -o BatchMode=yes -o StrictHostKeyChecking=no %s true" % c["m2"])
    line("SSH without password host1 -> host2 (mpirun)", "OK" if rc == 0 else "NG", rc == 0)
    if rc != 0:
        sys.exit("  host1 cannot SSH to host2 (check management network %s)" % c["m2"])

    print("\nRunning: %s  %s + %s  (%d GPU per server, max %s, %s)" % (test, c["h1"], c["h2"], ngpu, maxb, algo))
    rc, out = remote(c["h1"], cmd, timeout=3600)
    show("mpirun on host1 %s" % c["h1"], cmd, out)
    v = re.findall(r"Avg bus bandwidth\s*:\s*([\d.]+)", out)
    print("\nResult: %s" % (("OK  Avg bus bandwidth %s GB/s" % v[-1]) if rc == 0 and v else "FAIL (rc=%d)" % rc))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        {"rxe": rxe_test, "nccl": nccl_test}[mode]()
    except KeyError:
        sys.exit("usage: fast-rxe-test | fast-nccl-test")
    except (KeyboardInterrupt, EOFError):
        print()
