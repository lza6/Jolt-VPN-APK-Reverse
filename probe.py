#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
逐节点真实拨测：经本地 socks5 入站 → 节点 → ip-api，取出口 IP / 归属 / RTT。

  python probe.py                       # 单轮
  python probe.py --rounds 3 --workers 10
  python probe.py --out probe_result.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import statistics
import sys
import time

import socksutil

import winfix  # noqa: E402  (Windows 控制台 UTF-8 修复)

ECHO = "http://ip-api.com/json/?fields=status,country,city,isp,as,query"


def probe_one(port: int, meta: dict, timeout: float) -> dict:
    """对单个 socks 入站做一次拨测，失败自动重试 3 次。"""
    last = ""
    for attempt in range(1, 4):
        t0 = time.time()
        try:
            raw, _ = socksutil.http_get("127.0.0.1", port, ECHO, timeout=timeout, max_bytes=4096)
            rtt = round((time.time() - t0) * 1000)
            body = socksutil.http_body(raw)
            if b"{" not in body:
                raise RuntimeError("非 JSON 响应")
            info = json.loads(body[body.index(b"{") :].decode("utf-8", "replace"))
            if info.get("status") != "success":
                raise RuntimeError(f"ip-api: {info.get('message')}")
            return {
                "socks_port": port,
                **meta,
                "alive": True,
                "exit_ip": info.get("query"),
                "exit_country": info.get("country"),
                "exit_city": info.get("city"),
                "isp": info.get("isp"),
                "asn": info.get("as"),
                "rtt_ms": rtt,
                "attempts": attempt,
            }
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.0)
    return {"socks_port": port, **meta, "alive": False, "error": last}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="portmap.json")
    ap.add_argument("--out", default="probe_result.json")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()

    with open(args.map, encoding="utf-8") as f:
        mapping = {int(k): v for k, v in json.load(f).items()}

    results: list[dict] = []
    for rd in range(1, args.rounds + 1):
        print(f"\n===== 第 {rd}/{args.rounds} 轮 =====")
        with cf.ThreadPoolExecutor(args.workers) as ex:
            futs = {ex.submit(probe_one, p, m, args.timeout): p for p, m in mapping.items()}
            for f in cf.as_completed(futs):
                r = f.result()
                results.append(r)
                if r["alive"]:
                    print(
                        f"  ✅ {r['country']:<16}{r['city'] or '-':<12}{r['tier']:<8}"
                        f"{r['server']:<18}→ {r['exit_ip']:<16}{r['rtt_ms']:>6}ms  [{r['isp']}]"
                    )
                else:
                    print(f"  ❌ {r['country']:<16}{r['city'] or '-':<12}{r['tier']:<8}{r['server']:<18} {r['error']}")

    # 聚合成“每节点最后一轮结果 + 存活率”
    per_node: dict[int, dict] = {}
    for port, meta in mapping.items():
        per_node[port] = {**meta, "rounds": 0, "alive": 0, "rtts": [], "alive_flag": False}
    for r in results:
        e = per_node[r["socks_port"]]
        e["rounds"] += 1
        if r["alive"]:
            e["alive"] += 1
            e["alive_flag"] = True
            e["rtts"].append(r["rtt_ms"])
            for k in ("exit_ip", "exit_country", "exit_city", "isp", "asn", "rtt_ms", "attempts"):
                e[k] = r.get(k)
        else:
            e["error"] = r.get("error")
    for port, e in per_node.items():
        e["alive"] = e.pop("alive_flag")
        e["alive_count"] = sum(1 for r in results if r["socks_port"] == port and r["alive"])
        e["uptime"] = round(e["alive_count"] / e["rounds"] * 100, 1) if e["rounds"] else 0.0
        e["rtt_p50"] = statistics.median(e["rtts"]) if e["rtts"] else None
        e.pop("rtts", None)

    alive = [e for e in per_node.values() if e["alive"]]
    rtts = [e["rtt_p50"] for e in alive if e["rtt_p50"]]
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "nodes_total": len(per_node),
        "nodes_alive": len(alive),
        "alive_rate": round(len(alive) / len(per_node) * 100, 1) if per_node else 0,
        "rtt_p50": statistics.median(rtts) if rtts else None,
        "rtt_min": min(rtts) if rtts else None,
        "rtt_max": max(rtts) if rtts else None,
        "exit_ips": sorted({e["exit_ip"] for e in alive}),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "per_node": per_node, "raw": results}, f, ensure_ascii=False, indent=1)

    print(
        f"\n存活 {summary['nodes_alive']}/{summary['nodes_total']} ({summary['alive_rate']}%) · "
        f"RTT P50 {summary['rtt_p50']}ms · 独立出口 {len(summary['exit_ips'])} 个"
    )
    print(f"写入 {args.out}")
    return 0 if summary["nodes_alive"] else 1


if __name__ == "__main__":
    sys.exit(main())
