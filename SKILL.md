---
name: jolt-vpn-node-harvest
description: Jolt VPN v4.9 (com.joltapps.vpn) 白标 VPN 节点池收割 —— 双 API + 硬编码 AES 解密 + sing-box socks5 层 + 拨测压测。同类「Express + getAllServers + AES 字段加密」白标 App 可直接套用。
---

# Jolt VPN 节点池收割（可复用）

## 状态

| 能力 | 状态 |
|---|---|
| 纯 HTTP 拉节点（零鉴权） | ✅ 已验证 |
| AES 字段解密 | ✅ 已验证 |
| SS → socks5 代理池 | ✅ 已验证（4/10 存活） |
| 拨测 / 压测 / 看板 | ✅ 已验证 |
| OpenVPN 实际拨通 | ⏳ 未验证（缺 TUN/root） |

## 三条命令

```powershell
python refresh_pool.py --restart --rounds 2      # 收割→生成→重启→拨测→proxies.txt
python probe.py --rounds 3                       # 单独拨测
python demo_server.py --port 8944                # 看板 + /proxies.txt + /sub/clash
```

## 九条坑

1. **本机 `curl` 没有 SOCKS 支持**：`curl --socks5 127.0.0.1:<死端口>` 会静默直连目标。
   验证代理一律用 `socksutil.py`。
2. **本机 DNS/TLS 有中间人**：`ipinfo.io` / `ifconfig.me` 直连与走隧道返回同一个本地出口 IP。
   探测目标必须用 IP 字面量（`http://208.95.112.1/json/`）或 DNS over TCP 8.8.8.8。
3. **两个 API 延迟差异巨大**（2.7 s vs 19.5 s），超时别设 10 s。
4. **加密字段是标准 base64**（含 `+ / =`），不是 urlsafe。
5. **节点列表不轮换**（6 次采样哈希一致）→ 一次收割长期有效，但宿主机存活会变。
6. **Windows 控制台 GBK** 会在 print emoji 时炸，用 `winfix.py`。
7. **端口占用**：本机 8942 被别的 node.exe 占着，demo 默认 8944。
8. **new-api 的 proxy 文件不支持行尾注释**（整行 `url.Parse`），元信息只能放 `#` 开头整行。
9. **测速源选错会得出完全错误结论**：`speed.cloudflare.com/__down` 走 80 端口最稳，
   `tele2`/`cachefly` 在多数出口不可达。

## 复用判定（换一个白标 VPN App 时先看这三点）

1. dex 里搜 `getAllServers` / `get("api/` — 有没有节点列表接口。
2. `@Headers({"key:...` — 有没有硬编码请求头（白标 App 极常见）。
3. `AES/CBC/PKCS5Padding` + 静态 `SECRET_IV` — 字段加密是不是同款。
   三条都命中 → 直接套本仓库的 `harvest.py`，只改常量和字段名。
