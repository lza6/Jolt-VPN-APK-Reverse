#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把工作目录打成「可公开」的脱敏副本。

  python tools/publish_redacted.py --dest ../Jolt-VPN-APK-Reverse-public

设计原则：
  1. 白名单制 —— 只复制明确列出的文件，其余（nodes_decrypted.json / ovpn/ / x/ / jadx_out/ / 日志）一律不出去。
  2. 值级脱敏 —— 从 jolt_secrets.py 与 nodes_decrypted.json 读出**真实值**，逐条在文本里替换掉。
  3. 发布前守卫 —— 复制完再全量扫一遍，只要还残留任何一个真实值就 **中止**（exit 2），不产出一个"看起来能推"的目录。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

# 自成一体：Windows 控制台默认 GBK，这里不依赖 winfix.py
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 需要复制的文件（相对 ROOT）。目录用 "dir/" 形式表示递归。
WHITELIST = [
    "README.md",
    "SKILL.md",
    ".gitignore",
    "REDACTION.md",
    "harvest.py",
    "gen_singbox.py",
    "probe.py",
    "stress.py",
    "demo_server.py",
    "refresh_pool.py",
    "socksutil.py",
    "winfix.py",
    "jolt_secrets.example.py",
    "docs/",
    "samples/",
    "tools/publish_redacted.py",
]

# 这些 IP 不脱敏（公共基础设施 / 本机回环）
IP_KEEP = {
    "127.0.0.1", "0.0.0.0", "8.8.8.8", "1.1.1.1", "255.255.255.255",
    "208.95.112.1",  # ip-api.com，用作探测目标
    "183.250.230.8",  # 见 docs/REPORT.md，被当作"本机出口假象"举例
}

IP_RE = re.compile(r"\b((?:\d{1,3}\.){3}\d{1,3})\b")
SS_URI_RE = re.compile(r"ss://([A-Za-z0-9_\-=]+)@")


def load_secrets() -> dict:
    """收集所有必须脱敏的真实值。"""
    secrets: dict[str, list[str]] = {"api_key": [], "aes": [], "ip": [], "password": []}

    try:
        sys.path.insert(0, ROOT)
        import jolt_secrets  # type: ignore[import-not-found]

        for s in jolt_secrets.SOURCES:
            secrets["api_key"].append(str(s["api_key"]))
            for f in ("aes_key", "iv"):
                v = s[f]
                secrets["aes"].append(v.decode() if isinstance(v, bytes) else str(v))
    except Exception:  # noqa: BLE001
        print("  ⚠ 读不到 jolt_secrets.py（真实常量不会参与脱敏，仅靠正则兜底）")

    p = os.path.join(ROOT, "nodes_decrypted.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for n in json.load(f):
                if n.get("ip") and n["ip"] not in IP_KEEP:
                    secrets["ip"].append(n["ip"])
                if n.get("password"):
                    secrets["password"].append(n["password"])
    else:
        print("  ⚠ 读不到 nodes_decrypted.json（节点 IP/密码不参与脱敏）")

    for k in secrets:
        secrets[k] = sorted({v for v in secrets[k] if v}, key=len, reverse=True)

    # 片段兜底：代码里常把长常量拆成"前 N 位"暴露（例如 KEY_1 = IV 的前 8 位），
    # 只匹配完整值会漏。这里把 aes/iv 的前 8 位也当作独立敏感值处理。
    secrets["aes"] = sorted(
        {*secrets["aes"], *(v[:8] for v in secrets["aes"] if len(v) >= 12)},
        key=len, reverse=True,
    )
    return secrets


def redact_text(text: str, secrets: dict) -> str:
    # 1) 精确字符型凭据：保留前缀便于对照，其余打码
    for v in secrets["api_key"]:
        text = text.replace(v, v[:6] + "***（已脱敏）")
    for v in secrets["aes"]:
        text = text.replace(v, v[:4] + "***（已脱敏）")
    for v in secrets["password"]:
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(v)}(?![A-Za-z0-9])", v[:2] + "***", text)

    # 2) ss:// 的 userinfo 里含 base64(method:password)
    text = SS_URI_RE.sub("ss://<REDACTED-USERINFO>@", text)

    # 3) IP：前两段保留（便于说明国家/机房），后两段打码
    def _ip(m: re.Match) -> str:
        ip = m.group(1)
        if ip in IP_KEEP:
            return ip
        parts = ip.split(".")
        if all(0 <= int(x) <= 255 for x in parts):
            return f"{parts[0]}.{parts[1]}.***.***"
        return ip

    # 4) 清理残留：片段替换后可能留下几个字符（如 "y7Wn***（已脱敏）"），统一收口
    text = re.sub(r"（已脱敏）[A-Za-z0-9]{1,4}(?=[\"'\s,;）])", "（已脱敏）", text)

    return IP_RE.sub(_ip, text)


def guard(dest: str, secrets: dict) -> list[str]:
    """全量扫描产物，返回仍残留的真实值列表。"""
    hits: list[str] = []
    for base, _dirs, files in os.walk(dest):
        if ".git" in base:
            continue
        for fn in files:
            p = os.path.join(base, fn)
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    body = f.read()
            except Exception:  # noqa: BLE001
                continue
            rel = os.path.relpath(p, dest)
            for kind, values in secrets.items():
                for v in values:
                    if kind == "ip":
                        if v in body:
                            hits.append(f"{rel}: 残留真实 IP {v}")
                    elif v in body:
                        hits.append(f"{rel}: 残留真实 {kind} {v[:4]}***")
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", required=True)
    ap.add_argument("--force", action="store_true", help="目标目录已存在时清空重建")
    args = ap.parse_args()

    dest = os.path.abspath(args.dest)
    if os.path.exists(dest):
        if not args.force:
            print(f"目标已存在: {dest}（加 --force 清空重建）")
            return 1
        shutil.rmtree(dest)
    os.makedirs(dest)

    secrets = load_secrets()
    print(
        f"待脱敏真实值: api_key {len(secrets['api_key'])} · aes {len(secrets['aes'])} · "
        f"ip {len(secrets['ip'])} · password {len(secrets['password'])}"
    )

    copied = 0
    for entry in WHITELIST:
        src = os.path.join(ROOT, entry.rstrip("/"))
        if not os.path.exists(src):
            print(f"  ⚠ 白名单项不存在，跳过: {entry}")
            continue
        if os.path.isdir(src):
            for base, _dirs, files in os.walk(src):
                for fn in files:
                    sp = os.path.join(base, fn)
                    rel = os.path.relpath(sp, ROOT)
                    if "__pycache__" in rel or rel.endswith((".pyc", ".log")):
                        continue
                    dstp = os.path.join(dest, rel)
                    os.makedirs(os.path.dirname(dstp), exist_ok=True)
                    with open(sp, encoding="utf-8", errors="replace") as f:
                        body = f.read()
                    with open(dstp, "w", encoding="utf-8", newline="\n") as f:
                        f.write(redact_text(body, secrets))
                    copied += 1
        else:
            dstp = os.path.join(dest, entry)
            os.makedirs(os.path.dirname(dstp) or dest, exist_ok=True)
            with open(src, encoding="utf-8", errors="replace") as f:
                body = f.read()
            with open(dstp, "w", encoding="utf-8", newline="\n") as f:
                f.write(redact_text(body, secrets))
            copied += 1

    print(f"已复制并脱敏 {copied} 个文件 → {dest}")

    hits = guard(dest, secrets)
    if hits:
        print("\n❌ 守卫失败，以下文件仍残留真实值，禁止发布：")
        for h in hits[:40]:
            print("   " + h)
        if len(hits) > 40:
            print(f"   ...共 {len(hits)} 处")
        return 2

    print("✅ 守卫通过：产物中未发现任何真实 api_key / aes / 节点 IP / SS 密码")
    return 0


if __name__ == "__main__":
    sys.exit(main())
