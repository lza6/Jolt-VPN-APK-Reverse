#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jolt VPN 节点池 demo 看板

  python demo_server.py --port 8942
  http://127.0.0.1:8942/            节点表（存活 / 出口 IP / RTT / 吞吐）
  http://127.0.0.1:8942/proxies.txt new-api 可直接粘贴的 socks5 清单（仅存活）
  http://127.0.0.1:8942/sub         ss:// 订阅（base64，SIP002）
  http://127.0.0.1:8942/sub/clash   Clash / mihomo YAML
  http://127.0.0.1:8942/api/nodes   原始 JSON
  POST /refresh                     后台重跑 probe.py
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_RTT_MS = 1500.0  # 与 refresh_pool.py 默认阈值保持一致，避免看板与清单口径打架
STATE = {"probing": False, "last_probe": None}
LOCK = threading.Lock()


def load_json(name: str, default):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def snapshot() -> dict:
    mapping = load_json("portmap.json", {})
    probe = load_json("probe_result.json", {"per_node": {}, "summary": {}})
    stress = load_json("stress_result.json", {"nodes": {}})
    per_node = probe.get("per_node", {})
    rows = []
    for port_s, meta in sorted(mapping.items(), key=lambda kv: int(kv[0])):
        pn = per_node.get(port_s, {})
        st = stress.get("nodes", {}).get(port_s, {})
        rows.append(
            {
                **meta,
                "socks_port": int(port_s),
                "alive": bool(pn.get("alive")),
                "uptime": pn.get("uptime"),
                "exit_ip": pn.get("exit_ip"),
                "exit_country": pn.get("exit_country"),
                "isp": pn.get("isp"),
                "rtt_p50": pn.get("rtt_p50"),
                "single_mbps": st.get("single_mbps"),
                "aggregate_mbps": st.get("aggregate_mbps"),
                "streams_ok": st.get("streams_ok"),
                "error": pn.get("error"),
            }
        )
    alive = [r for r in rows if r["alive"]]
    usable = [r for r in alive if (r["rtt_p50"] or 9e9) <= MAX_RTT_MS]
    for r in rows:
        r["usable"] = bool(r["alive"] and (r["rtt_p50"] or 9e9) <= MAX_RTT_MS)
    rtts = [r["rtt_p50"] for r in alive if r["rtt_p50"]]
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "summary": {
            "total": len(rows),
            "alive": len(alive),
            "usable": len(usable),
            "exit_ips": len({r["exit_ip"] for r in alive if r["exit_ip"]}),
            "rtt_p50": sorted(rtts)[len(rtts) // 2] if rtts else None,
            "probe_at": probe.get("summary", {}).get("generated_at"),
            "probing": STATE["probing"],
            "last_refresh": STATE.get("last_refresh"),
        },
        "rows": rows,
    }


def secrets_index() -> dict:
    """(server, port) -> 解密后的明文明文凭证，供 ss:// 与 Clash 输出复用。"""
    idx = {}
    for n in load_json("nodes_decrypted.json", []):
        if n.get("protocol") == "shadowsocks" and n.get("ip"):
            idx[(n["ip"], int(n.get("port") or 0))] = n
    return idx


def ss_uri(r: dict, idx: dict) -> str:
    n = idx.get((r["server"], int(r["server_port"])))
    if not n:
        return ""
    userinfo = base64.urlsafe_b64encode(f"{n['method']}:{n['password']}".encode()).decode().rstrip("=")
    name = quote(f"Jolt-{r['flag']}-{r['city'] or r['country']}-{r['tier']}")
    return f"ss://{userinfo}@{n['ip']}:{n['port']}#{name}"


PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Jolt VPN v4.9 · 节点池看板</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#c9d1d9;--dim:#8b949e;--ok:#3fb950;--bad:#f85149;--acc:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Microsoft YaHei",sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:16px;align-items:center}
h1{font-size:17px;margin:0;font-weight:600}
.chip{border:1px solid var(--line);border-radius:999px;padding:3px 11px;font-size:12px;color:var(--dim)}
.chip b{color:var(--fg)}
.chip.ok b{color:var(--ok)}.chip.bad b{color:var(--bad)}
main{padding:20px 24px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:9px 10px;color:var(--dim);font-weight:500;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid #21262d;white-space:nowrap}
tr:hover td{background:#1c2129}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.on{background:var(--ok);box-shadow:0 0 6px var(--ok)}.off{background:var(--bad)}
.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.num{text-align:right;font-family:ui-monospace,Consolas,monospace}
.tier-free{color:var(--acc)}.tier-premium{color:#d29922}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
footer{padding:14px 24px;color:var(--dim);font-size:12px;border-top:1px solid var(--line)}
.btn{background:#21262d;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:5px 12px;cursor:pointer;font-size:13px}
.btn:hover{border-color:var(--acc)}
code{background:#21262d;padding:1px 5px;border-radius:4px}
</style></head><body>
<header>
  <h1>Jolt VPN v4.9 (b40) · 节点池</h1>
  <span class="chip ok">存活 <b id="alive"></b>/<b id="total"></b></span>
  <span class="chip">可用(≤1500ms) <b id="usable"></b></span>
  <span class="chip">独立出口 <b id="exits"></b></span>
  <span class="chip">RTT P50 <b id="rtt"></b></span>
  <button class="btn" onclick="refresh()">重新拨测</button>
  <span class="chip" id="ts" style="margin-left:auto"></span>
</header>
<main>
<table>
<thead><tr>
  <th>状态</th><th>国家 / 城市</th><th>层级</th><th>服务器</th><th>协议</th>
  <th>本地 socks5</th><th>出口 IP</th><th>ISP</th><th class="num">RTT</th>
  <th class="num">单流 Mbps</th><th class="num">聚合 Mbps</th><th class="num">并发成功</th>
</tr></thead>
<tbody id="tb"></tbody>
</table>
<p style="color:var(--dim);margin-top:16px">
  new-api 接入：<code>http://127.0.0.1:__PORT__/proxies.txt</code> ·
  订阅：<code>/sub</code> · Clash：<code>/sub/clash</code> · JSON：<code>/api/nodes</code>
</p>
</main>
<footer id="ft"></footer>
<script>
const f = v => v===null||v===undefined||v==='' ? '—' : v;
async function load(){
  const r = await fetch('/api/nodes'); const d = await r.json(); const s = d.summary;
  document.getElementById('alive').textContent = s.alive;
  document.getElementById('total').textContent = s.total;
  document.getElementById('usable').textContent = s.usable;
  document.getElementById('exits').textContent = s.exit_ips;
  document.getElementById('rtt').textContent = f(s.rtt_p50) + (s.rtt_p50?' ms':'');
  document.getElementById('ts').textContent = '拨测于 ' + f(s.probe_at) + (s.probing?' · 拨测中…':'');
  document.getElementById('tb').innerHTML = d.rows.map(n => `<tr>
    <td><span class="dot ${n.alive?'on':'off'}"></span>${n.alive?'在线':'离线'}</td>
    <td>${n.flag.toUpperCase()} ${n.country} / ${f(n.city)}</td>
    <td class="tier-${n.tier}">${n.tier}</td>
    <td class="mono">${n.server}:${n.server_port}</td>
    <td>${n.method||'openvpn'}</td>
    <td class="mono">${n.usable?'socks5://127.0.0.1:'+n.socks_port:(n.alive?'（RTT 超阈，未入池）':'—')}</td>
    <td class="mono">${f(n.exit_ip)}</td>
    <td>${f(n.isp)}</td>
    <td class="num">${n.rtt_p50?n.rtt_p50+' ms':'—'}</td>
    <td class="num">${f(n.single_mbps)}</td>
    <td class="num">${f(n.aggregate_mbps)}</td>
    <td class="num">${f(n.streams_ok)}</td>
  </tr>`).join('');
  document.getElementById('ft').textContent = '节点 ${d.summary.total} 个 · 存活 ${d.summary.alive} 个 · 更新 ${d.generated_at}';
}
async function refresh(){ await fetch('/refresh',{method:'POST'}); setTimeout(load, 800); }
load(); setInterval(load, 15000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    server_version = "JoltDemo/1.0"

    def _send(self, code: int, body: bytes, ctype="application/json; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *a):  # noqa: A003
        if "/api/nodes" not in self.path:
            sys.stderr.write(f"{time.strftime('%H:%M:%S')} {self.address_string()} {fmt % a}\n")

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        snap = snapshot()

        if path == "/":
            page = PAGE.replace("__PORT__", str(self.server.server_address[1]))
            return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")

        if path == "/api/nodes":
            return self._send(200, json.dumps(snap, ensure_ascii=False).encode())

        if path == "/health":
            return self._send(200, json.dumps({"ok": True, "alive": snap["summary"]["alive"]}).encode())

        if path == "/proxies.txt":
            lines = [f"socks5://127.0.0.1:{r['socks_port']}" for r in snap["rows"] if r["usable"]]
            return self._send(200, ("\n".join(lines) + "\n").encode(), "text/plain; charset=utf-8")

        if path == "/sub":
            idx = secrets_index()
            uris = [u for u in (ss_uri(r, idx) for r in snap["rows"] if r["usable"]) if u]
            blob = base64.b64encode("\n".join(uris).encode()).decode()
            return self._send(200, blob.encode(), "text/plain; charset=utf-8")

        if path == "/sub/clash":
            idx = secrets_index()
            out = ["mixed-port: 7890", "allow-lan: false", "mode: rule", "log-level: info", "proxies:"]
            names = []
            for r in snap["rows"]:
                n = idx.get((r["server"], int(r["server_port"])))
                if not r["usable"] or not n:
                    continue
                name = f"Jolt-{r['flag']}-{r['city'] or r['country']}-{r['tier']}".replace(" ", "_")
                names.append(name)
                out += [
                    f"  - name: {name}",
                    "    type: ss",
                    f"    server: {n['ip']}",
                    f"    port: {n['port']}",
                    f"    cipher: {n['method']}",
                    f"    password: \"{n['password']}\"",
                    "    udp: true",
                ]
            if not names:
                return self._send(503, b"# no alive node\n", "text/yaml; charset=utf-8")
            out += [
                "proxy-groups:",
                "  - name: Jolt",
                "    type: url-test",
                "    url: http://cp.cloudflare.com/generate_204",
                "    interval: 300",
                "    proxies:",
            ] + [f"      - {x}" for x in names]
            return self._send(200, ("\n".join(out) + "\n").encode(), "text/yaml; charset=utf-8")

        return self._send(404, b'{"error":"not found"}')

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] != "/refresh":
            return self._send(404, b'{"error":"not found"}')
        with LOCK:
            if STATE["probing"]:
                return self._send(202, b'{"ok":true,"already":true}')
            STATE["probing"] = True

        def run() -> None:
            try:
                r = subprocess.run(
                    [sys.executable, "-u", os.path.join(HERE, "probe.py"), "--out", "probe_result.json"],
                    cwd=HERE, timeout=600, capture_output=True,
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                STATE["last_refresh"] = {
                    "rc": r.returncode,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "tail": (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()[-1:] or [""],
                    "err": (r.stderr or b"").decode("utf-8", "replace")[-300:],
                }
                STATE["last_probe"] = time.time()
            except Exception as e:  # noqa: BLE001
                STATE["last_refresh"] = {"rc": -1, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "err": repr(e)}
            finally:
                STATE["probing"] = False

        threading.Thread(target=run, daemon=True).start()
        return self._send(202, b'{"ok":true,"started":true}')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8942)
    ap.add_argument("--bind", default="127.0.0.1")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.bind, args.port), H)
    print(f"Jolt VPN 节点池看板 → http://{args.bind}:{args.port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
