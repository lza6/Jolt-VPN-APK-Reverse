#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对存活节点做压测：单流吞吐（下行 Mbps）+ 并发成功率 + 聚合吞吐。

  python stress.py                          # 读 probe_result.json 的存活节点
  python stress.py --streams 8 --rounds 3
  python stress.py --size 1000000 --url http://ipv4.download.thinkbroadband.com/1MB.zip
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import statistics
import time

import socksutil

import winfix  # noqa: E402  (Windows 控制台 UTF-8 修复)

# 测速源按「实测通过率」排序，逐个回退。
# 实测（2026-10-29，SG/US-DAL/NL 三节点）：
#   leaseweb ams1 10mb.bin   → 3/3 可用（最稳，首选）
#   leaseweb ubuntu 镜像      → 3/3 可用
#   thinkbroadband            → 2/3 可用，NL 偶发慢
#   speed.cloudflare.com      → 初期 7.4 Mbps，被反复压后转为超时（疑似对出口 IP 限流）
#   其余（linode / softlayer / fdcservers / proof.ovh）基本不可用或只回 301/308
SPEED_SOURCES = [
    "http://speedtest.ams1.nl.leaseweb.net/10mb.bin",
    "http://mirror.nl.leaseweb.net/ubuntu-releases/22.04/ubuntu-22.04.5-desktop-amd64.iso",
    "http://ipv4.download.thinkbroadband.com/5MB.zip",
    "http://speed.cloudflare.com/__down?bytes={size}",
]


def download(port: int, url: str, expect: int, timeout: float) -> tuple[bool, int, float, str]:
    """经 socks 拉一段数据，返回 (ok, bytes, seconds, err)。"""
    t0 = time.time()
    try:
        raw, _ = socksutil.http_get("127.0.0.1", port, url, timeout=timeout, max_bytes=expect)
    except Exception as e:  # noqa: BLE001
        return False, 0, time.time() - t0, f"{type(e).__name__}: {e}"
    status = raw.split(b"\r\n", 1)[0][:24].decode("latin-1") if raw else "<empty>"
    body = socksutil.http_body(raw)
    ok = len(body) >= expect * 0.8
    return ok, len(body), time.time() - t0, "" if ok else f"{status} / 仅收到 {len(body)}B"


def single_stream(port: int, size: int, timeout: float) -> tuple[bool, float, str, str]:
    """单流：遍历测速源直到拿到足量数据。返回 (ok, mbps, url, err)。"""
    err = ""
    for tpl in SPEED_SOURCES:
        expect = min(size, 5_000_000) if "thinkbroadband" in tpl else size
        url = tpl.format(size=size)
        ok, n, dt, e = download(port, url, expect, timeout)
        if ok:
            return True, round(n * 8 / dt / 1e6, 2), url, ""
        err = f"{url} → {e}"
    return False, 0.0, "", err


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", default="probe_result.json")
    ap.add_argument("--out", default="stress_result.json")
    ap.add_argument("--streams", type=int, default=6)
    ap.add_argument("--size", type=int, default=2_000_000)
    ap.add_argument("--timeout", type=float, default=20.0)
    args = ap.parse_args()

    with open(args.probe, encoding="utf-8") as f:
        probe = json.load(f)
    # per_node 的键就是 socks 端口
    targets = [(int(p), n) for p, n in probe["per_node"].items()
               if n.get("alive") and n.get("uptime", 0) > 0]
    if not targets:
        print("probe_result.json 里没有存活节点")
        return 1
    targets.sort(key=lambda kv: kv[1].get("rtt_p50") or 9e9)

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "streams": args.streams, "nodes": {}}

    for port, n in targets:
        name = f"{n['country']}/{n['city']}"
        ok, mbps, url, err = single_stream(port, args.size, args.timeout)
        agg = None
        ok_cnt = 0
        if ok:
            t0 = time.time()
            with cf.ThreadPoolExecutor(args.streams) as ex:
                rs = list(ex.map(lambda _: download(port, url, args.size, args.timeout), range(args.streams)))
            ok_cnt = sum(1 for r in rs if r[0])
            total_b = sum(r[1] for r in rs)
            dt = time.time() - t0
            agg = round(total_b * 8 / dt / 1e6, 2)
        report["nodes"][str(port)] = {
            "country": n["country"], "city": n["city"], "tier": n["tier"], "server": n["server"],
            "exit_ip": n.get("exit_ip"), "rtt_p50": n.get("rtt_p50"),
            "single_mbps": mbps, "aggregate_mbps": agg, "streams_ok": f"{ok_cnt}/{args.streams}",
            "source": url, "error": err,
        }
        print(
            f"{name:<26}{n['tier']:<9} RTT {str(n.get('rtt_p50')):>6}ms  单流 {mbps:>6.2f} Mbps  "
            f"聚合({args.streams}并发) {str(agg):>6} Mbps  成功 {ok_cnt}/{args.streams}"
            + (f"  [{err}]" if err else "")
        )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n写入 {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
