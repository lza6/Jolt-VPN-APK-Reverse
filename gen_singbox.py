#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
由 nodes_decrypted.json 生成 sing-box 配置：每个 shadowsocks 节点一个本地 socks5 入站。

  python gen_singbox.py --base-port 22100 --out singbox.json

端口映射写进 portmap.json，probe.py / demo_server.py 直接读。
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", default="nodes_decrypted.json")
    ap.add_argument("--out", default="singbox.json")
    ap.add_argument("--map", default="portmap.json")
    ap.add_argument("--base-port", type=int, default=22100)
    args = ap.parse_args()

    with open(args.nodes, encoding="utf-8") as f:
        nodes = json.load(f)

    ss = [n for n in nodes if n["protocol"] == "shadowsocks" and n.get("ip")]
    if not ss:
        sys.exit("没有可用的 shadowsocks 节点")

    inbounds, outbounds, rules, mapping = [], [], [], {}
    for i, n in enumerate(ss):
        port = args.base_port + i
        itag, otag = f"in{i}", f"ss{i}"
        inbounds.append({"type": "socks", "tag": itag, "listen": "127.0.0.1", "listen_port": port})
        outbounds.append(
            {
                "type": "shadowsocks",
                "tag": otag,
                "server": n["ip"],
                "server_port": int(n["port"]),
                "method": n["method"],
                "password": n["password"],
            }
        )
        rules.append({"inbound": [itag], "outbound": otag})
        mapping[str(port)] = {
            "idx": n["idx"],
            "country": n["country"],
            "city": n["city"],
            "flag": n["flag"],
            "tier": n["tier"],
            "server": n["ip"],
            "server_port": int(n["port"]),
            "method": n["method"],
        }

    cfg = {
        "log": {"level": "warn", "timestamp": True},
        "inbounds": inbounds,
        "outbounds": outbounds + [{"type": "direct", "tag": "direct"}],
        "route": {"rules": rules, "final": "direct"},
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    with open(args.map, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)

    print(f"{len(ss)} 个 socks5 入站 → 127.0.0.1:{args.base_port}..{args.base_port + len(ss) - 1}")
    print(f"写入 {args.out} / {args.map}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
