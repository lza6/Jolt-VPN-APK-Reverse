#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一条命令跑完：收割 → 生成配置 → （必要时重启 sing-box）→ 拨测 → 输出 proxies.txt。

  python refresh_pool.py
  python refresh_pool.py --restart --singbox-bin tools/singbox/sing-box-1.14.4-windows-amd64/sing-box.exe
  python refresh_pool.py --restart --port 22100 --workers 10 --rounds 2

建议用 Windows 任务计划每 6 小时跑一次（节点列表静态，但宿主机存活会变）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import winfix  # noqa: E402,F401  (Windows 控制台 UTF-8 修复)

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd: list[str], **kw) -> int:
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=HERE, env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **kw)


def launch_singbox(bin_path: str, cfg: str) -> None:
    """后台拉起 sing-box；已有同名进程先杀掉。"""
    subprocess.call(["taskkill", "/IM", os.path.basename(bin_path), "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    log = open(os.path.join(HERE, "singbox.log"), "a", encoding="utf-8")
    subprocess.Popen([bin_path, "run", "-c", cfg], cwd=HERE, stdout=log, stderr=log,
                     creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    print(f"  sing-box 已启动: {cfg}")
    time.sleep(3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-port", type=int, default=22100)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--restart", action="store_true", help="配置变化时重启 sing-box")
    ap.add_argument("--singbox-bin", default=r"tools\singbox\sing-box-1.14.4-windows-amd64\sing-box.exe")
    ap.add_argument("--max-rtt", type=float, default=1500.0,
                    help="RTT 超过该值(ms)的节点不写进 proxies.txt（默认 1500ms；"
                         "实测 DE 常年 2200-6800ms 且 0 吞吐，必须剔掉）")
    ap.add_argument("--proxies-out", default="proxies.txt")
    args = ap.parse_args()

    if run([sys.executable, "harvest.py"]) != 0:
        print("收割失败，中止")
        return 1

    old_cfg = None
    if os.path.exists(os.path.join(HERE, "singbox.json")):
        with open(os.path.join(HERE, "singbox.json"), "rb") as f:
            old_cfg = f.read()

    if run([sys.executable, "gen_singbox.py", "--base-port", str(args.base_port)]) != 0:
        print("生成配置失败，中止")
        return 1

    with open(os.path.join(HERE, "singbox.json"), "rb") as f:
        new_cfg = f.read()
    changed = old_cfg != new_cfg
    print(f"\n配置{'已变化' if changed else '未变化'}")

    if args.restart:
        if changed or not old_cfg:
            if not os.path.exists(os.path.join(HERE, args.singbox_bin)):
                print(f"  ⚠ 找不到 sing-box: {args.singbox_bin}，跳过重启")
            else:
                launch_singbox(os.path.join(HERE, args.singbox_bin), "singbox.json")
        else:
            print("  配置一致，保持现有进程")

    if run([sys.executable, "probe.py", "--rounds", str(args.rounds), "--workers", str(args.workers)]) != 0:
        print("拨测失败（全部节点不可用）")
        # 仍继续写空文件，避免下游读到过期清单

    with open(os.path.join(HERE, "probe_result.json"), encoding="utf-8") as f:
        probe = json.load(f)
    alive = sorted(
        p for p, v in probe["per_node"].items()
        if v.get("alive") and (v.get("rtt_p50") or 9e9) <= args.max_rtt
    )
    dropped = [p for p, v in probe["per_node"].items()
               if v.get("alive") and (v.get("rtt_p50") or 9e9) > args.max_rtt]
    if dropped:
        print(f"按 RTT > {args.max_rtt}ms 剔除: {', '.join(dropped)}")
    out = os.path.join(HERE, args.proxies_out)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        # 注意：new-api 的 TRYINGOPEN_PROXY_FILE 解析器会对整行做 url.Parse，
        # 只跳过以 # 开头的整行注释，**不支持行尾注释** → 元信息只能放文件头。
        f.write(f"# Jolt VPN 代理池 · {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n")
        total = len(probe["per_node"])
        probed_alive = sum(1 for v in probe["per_node"].values() if v.get("alive"))
        f.write(f"# 写入 {len(alive)}/{total}（探活存活 {probed_alive}，"
                f"RTT>{args.max_rtt:.0f}ms 剔除 {probed_alive - len(alive)}）\n")
        for p in alive:
            v = probe["per_node"][p]
            f.write(f"# {p} {v.get('country')}/{v.get('city')} {v.get('exit_ip')} "
                    f"rtt={v.get('rtt_p50')}ms\n")
        for p in alive:
            f.write(f"socks5://127.0.0.1:{p}\n")
    print(f"\n写入 {out}（{len(alive)} 条）")
    return 0 if alive else 1


if __name__ == "__main__":
    sys.exit(main())
