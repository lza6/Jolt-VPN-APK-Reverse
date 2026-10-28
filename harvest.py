#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jolt VPN v4.9 (com.joltapps.vpn) — 节点池收割器

协议要点（全部静态提取自 dex，可复算）：
  GET {base}/api/getAllServers
      header: key: <硬编码 API Key>
  base 有两个（主/备），节点集合基本一致，互为冗余：
      https://api.joltappstudio.com/        (key: Kxf18A***（已脱敏）)
      https://api.mudasserkhalidllc.com/    (key: E$uTzF***（已脱敏）)
  响应里 ipaddress / encryption / password / server_content 均为
  AES/CBC/PKCS5Padding + Base64：
      主 API  key=93TR***（已脱敏）  iv=y7Wn***（已脱敏）
      备 API  key=47DE***（已脱敏）  iv=x3Vm***（已脱敏）

用法:
  python harvest.py                # 拉取双源 + 解密 + 落盘
  python harvest.py --no-ovpn      # 不写 .ovpn 文件
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.request

import winfix  # noqa: E402  (Windows 控制台 UTF-8 修复)

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖: pip install cryptography")

# 凭据不写在代码里：优先读本地 jolt_secrets.py（已 gitignore），
# 也可用环境变量 JOLT_SOURCES_JSON 注入。公开仓库只带 jolt_secrets.example.py。
def _load_sources() -> list[dict]:
    env = os.environ.get("JOLT_SOURCES_JSON", "").strip()
    if env:
        raw = json.loads(env)
    else:
        try:
            import jolt_secrets  # type: ignore[import-not-found]
        except ImportError:
            sys.exit(
                "缺少 jolt_secrets.py。\n"
                "  cp jolt_secrets.example.py jolt_secrets.py\n"
                "  然后把 APK 里提取到的 api_key / aes_key / iv 填进去（见 docs/PROTOCOL.md 第 3 节）。"
            )
        raw = jolt_secrets.SOURCES
    out = []
    for s in raw:
        s = dict(s)
        s["aes_key"] = s["aes_key"].encode() if isinstance(s["aes_key"], str) else s["aes_key"]
        s["iv"] = s["iv"].encode() if isinstance(s["iv"], str) else s["iv"]
        out.append(s)
    return out


SOURCES = _load_sources()

PATH = "api/getAllServers"


def _dec(b64: str, key: bytes, iv: bytes) -> str:
    if not b64:
        return ""
    ct = base64.b64decode(b64)
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    pt = d.update(ct) + d.finalize()
    pad = pt[-1]
    if pad < 1 or pad > 16:
        return ""
    return pt[:-pad].decode("utf-8", "replace")


def fetch(src: dict, timeout: int = 45, retries: int = 3) -> list[dict]:
    url = src["base"] + PATH
    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "key": src["api_key"],
                "User-Agent": "okhttp/4.12.0",
                "Accept-Encoding": "gzip",
            },
        )
        try:
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip

                    raw = gzip.decompress(raw)
            payload = json.loads(raw.decode("utf-8"))
            if payload.get("code") != 200:
                raise RuntimeError(f"api code={payload.get('code')} msg={payload.get('message')}")
            data = payload["data"]
            print(f"  [{src['name']}] HTTP 200 · {len(data)} 条 · {time.time() - t0:.1f}s")
            return data
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"  [{src['name']}] attempt {attempt}/{retries} 失败: {type(e).__name__}: {e}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"{src['name']} 拉取失败: {last}")


def normalize(data: list[dict], src: dict) -> list[dict]:
    out = []
    for x in data:
        node = {
            "country": x.get("country_name", ""),
            "city": x.get("city_name", ""),
            "flag": x.get("flag", ""),
            "tier": x.get("type", ""),
            "protocol": x.get("protocol", ""),
            "tag": x.get("tag", ""),
            "source": src["name"],
            "port": x.get("port"),
        }
        node["ip"] = _dec(x.get("ipaddress", ""), src["aes_key"], src["iv"])
        node["method"] = _dec(x.get("encryption", ""), src["aes_key"], src["iv"])
        node["password"] = _dec(x.get("password", ""), src["aes_key"], src["iv"])
        if x.get("server_content"):
            node["ovpn"] = _dec(x["server_content"], src["aes_key"], src["iv"])
        out.append(node)
    return out


def key_of(n: dict) -> tuple:
    return (n["protocol"], n["ip"], n.get("port"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="nodes_decrypted.json")
    ap.add_argument("--ovpn-dir", default="ovpn")
    ap.add_argument("--no-ovpn", action="store_true")
    args = ap.parse_args()

    merged: dict[tuple, dict] = {}
    ok_sources = 0
    for src in SOURCES:
        try:
            nodes = normalize(fetch(src), src)
        except Exception as e:  # noqa: BLE001
            print(f"  [{src['name']}] 跳过: {e}")
            continue
        ok_sources += 1
        for n in nodes:
            k = key_of(n)
            if k in merged:
                merged[k]["mirrors"] = merged[k].get("mirrors", [merged[k]["source"]]) + [src["name"]]
            else:
                merged[k] = n
    if ok_sources == 0:
        print("两个 API 均不可用，退出")
        return 1

    nodes = sorted(merged.values(), key=lambda n: (n["protocol"], n["tier"], n["country"]))
    for i, n in enumerate(nodes):
        n["idx"] = i

    if not args.no_ovpn:
        os.makedirs(args.ovpn_dir, exist_ok=True)
        for n in nodes:
            body = n.pop("ovpn", None)
            if not body:
                continue
            fn = f"{args.ovpn_dir}/{n['flag']}_{n['country'].replace(' ', '_')}_{n['tier']}.ovpn"
            with open(fn, "w", encoding="utf-8", newline="\n") as f:
                f.write(body if body.endswith("\n") else body + "\n")
            n["ovpn_file"] = fn

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(nodes, f, ensure_ascii=False, indent=1)

    ss = [n for n in nodes if n["protocol"] == "shadowsocks"]
    ov = [n for n in nodes if n["protocol"] == "openvpn"]
    print(f"\n合计 {len(nodes)} 个唯一节点：shadowsocks {len(ss)} · openvpn {len(ov)}")
    print(f"写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
