# Jolt VPN v4.9 b40 — 逆向 / 节点池 / 代理池评估（R1）

> **免责声明**：本项目是 Android 客户端的**安全研究与协议分析**存档。仓库内所有活凭据
> （API Key / AES Key / 节点 IP / SS 密码 / OVPN 证书）**已全部脱敏**，详见 [REDACTION.md](REDACTION.md)。
> 节点与基础设施属于第三方运营方，**请勿**用于任何生产服务或对外提供代理能力。

> 目标 APK：`Jolt VPN v4.9 b40 (Premium by @ElaMods).apk`（29 MB，arm64-v8a + armeabi-v7a，ElaMods 破解版）
> 包名：`com.joltapps.vpn` · 后端：`joltappstudio` / `mudasserkhalidllc`
>
> **结论先行**：协议 **100% 静态还原、零鉴权可复现**（两条硬编码 API Key + AES 密钥全部来自 dex 明文，
> 不需要 Frida、不需要抓包、不需要登录）。节点池 = **10 个 Shadowsocks + 10 个 OpenVPN**，
> 属**自营 VPS 农场**（GTHost / M247 / OVH / Scalaxy）。
> Shadowsocks 侧 **4/10 存活**（独立出口 IP），其中 **3 个可当代理池用**：
> 单流 **4.7–8.7 Mbps**、6 并发聚合 **15–37 Mbps**、RTT **163 / 429 / 796 ms**。
> OpenVPN 侧 10 份配置全部导出（含 `ca/cert/key/tls-crypt`），本轮未接入代理池（需 TUN + root）。

| 项目 | 状态 | 证据 |
|------|------|------|
| 节点列表接口 | ✅ 已验证 | `GET /api/getAllServers`，双后端镜像，各 20 条 |
| 鉴权方式 | ✅ 已验证 | 单请求头 `key: <硬编码串>`，无登录 / 无设备注册 / 无签名 |
| 字段加密 | ✅ 已验证 | `AES/CBC/PKCS5Padding` + Base64，密钥 IV 均硬编码（主/备各一套） |
| 节点池规模 | ✅ 已验证 | 10 Shadowsocks（8388, `chacha20-ietf-poly1305`）+ 10 OpenVPN（UDP 1194/1195） |
| 列表稳定性 | ✅ 已验证 | 连续 6 次采样（30s 间隔）节点 IP 集合哈希完全一致，**不轮换** |
| Shadowsocks 存活 | ✅ 实测 | 4/10 TCP+SS 握手成功，出口 IP = 节点自身 IP（无 NAT 共享） |
| 吞吐 | ✅ 实测 | 单流 4.74 / 7.93 / 8.70 Mbps；6 并发聚合 16.72 / 36.66 / 15.22 Mbps |
| OpenVPN 配置 | ✅ 已导出 | 10 份 `.ovpn`，含内嵌 CA/证书/私钥/`tls-crypt`；`AES-128-GCM` |
| OpenVPN 拨通 | ⏳ 未验证 | 需 TUN 设备 + root（本机 WSL sudo 需密码），本轮不做 |
| 可商用性 | ⛔ 不建议 | 凭证 ≠ 授权，见「合规与风险」 |

## 目录

```
harvest.py          拉取双 API → AES 解密 → nodes_decrypted.json + ovpn/*.ovpn
gen_singbox.py      nodes → sing-box 配置（每节点一个本地 socks5 入站）
probe.py            逐节点真实拨测（存活 / 出口 IP / RTT / 可用率）
stress.py           单流吞吐 + 并发成功率 + 聚合带宽
demo_server.py      看板 + /proxies.txt + /sub + /sub/clash
socksutil.py        纯标准库 SOCKS5 客户端（本机 curl 无 socks 支持，见 REPORT）
winfix.py           Windows 控制台 UTF-8 修复
docs/PROTOCOL.md    协议手写手册（常量 / 加解密 / 字段表 / 最小实现 / 坑）
docs/REPORT.md      逆向过程、实测数据、踩坑清单、未破点
docs/NEWAPI-HANDOFF.md  new-api 对接交接包（三种接入方式 / 三层验收 / 运维 SOP / 排错表）
docs/HANDOFF-PROMPT.md  可直接粘给下一个会话的对接指令书
REDACTION.md        脱敏说明（被去掉了什么、保留了什么、怎么本地还原）
ovpn/               10 份已解密的 OpenVPN 配置
samples/            脱敏样例（结构参考，凭证已打码）
```

## 快速开始

```powershell
# 0) 依赖（仅这一个）+ 凭据（仓库里没有，需自行从 APK 提取）
pip install cryptography
cp jolt_secrets.example.py jolt_secrets.py   # 按 docs/PROTOCOL.md 第 2-3 节填常量
# 1) 下载 sing-box（脚本不自动下，放到 tools/singbox/）
#    https://github.com/SagerNet/sing-box/releases  → windows-amd64.zip

# 2) 收割（双 API 自动回退）
python harvest.py

# 3) 生成并启动 socks5 层
python gen_singbox.py --base-port 22100
tools\singbox\sing-box-1.14.4-windows-amd64\sing-box.exe run -c singbox.json

# 4) 拨测 + 压测
python probe.py --rounds 3 --workers 10
python stress.py --streams 6 --size 2000000

# 5) 看板（本机 8942 已被别的 node.exe 占用，默认用 8944）
python demo_server.py --port 8944
#   http://127.0.0.1:8944/            节点表
#   http://127.0.0.1:8944/proxies.txt new-api 直接读的 socks5 清单
#   http://127.0.0.1:8944/sub         ss:// 订阅（base64）
#   http://127.0.0.1:8944/sub/clash   Clash / mihomo YAML
```

一键替代第 2–5 步（推荐；收割 → 生成 → **配置变了才重启** → 拨测 → 落 `proxies.txt`）：

```powershell
python refresh_pool.py --restart --rounds 2
```

`proxies.txt` 只写「存活 **且** RTT ≤ 1500 ms」的节点（`--max-rtt` 可调）；看板 `/proxies.txt`
用同一口径，避免两边打架。

## 实测数据（2026-10-29，本机出口，直连拨测）

### Shadowsocks 节点池

| 国家/城市 | 层级 | 服务器 | ISP / ASN | 存活 | RTT P50 | 单流 Mbps | 6 并发聚合 | 并发成功 |
|---|---|---|---|---|---|---|---|---|
| 🇸🇬 Singapore | premium | 38.180.***.*** | M247 · AS9009 | ✅ 100% | **139–196 ms** | 1.8–8.7 | **15.2–15.3** | 6/6 |
| 🇺🇸 Dallas | free | 216.106.***.*** | GTHost · AS63023 | ✅ 100% | **428–447 ms** | 7.5–8.0 | **36.7–41.1** | 6/6 |
| 🇳🇱 Amsterdam | premium | 5.61.***.*** | Scalaxy · AS58061 | ✅ 100% | **745–884 ms** | 4.1–4.7 | **15.4–16.7** | 6/6 |
| 🇩🇪 Frankfurt | free | 170.101.***.*** | GTHost · AS63023 | ⚠️ 探活通、压测死 | 2264–6751 ms | 0.00 | — | 0/6 |
| 🇺🇸 New York | premium | 38.180.***.*** | M247 · AS9009 | ❌ ICMP 通、SS 死 | — | — | — | — |
| 🇪🇸 Madrid | free | 167.17.***.*** | GTHost · AS63023 | ❌ 主机不通 | — | — | — | — |
| 🇫🇷 Paris | free | 139.64.***.*** | GTHost · AS63023 | ❌ 主机不通 | — | — | — | — |
| 🇬🇧 London | free | 198.244.***.*** | OVH · AS16276 | ❌ 主机不通 | — | — | — | — |
| 🇨🇦 Montreal | free | 15.235.***.*** | OVH · AS16276 | ❌ 主机不通 | — | — | — | — |
| 🇯🇵 Tokyo | premium | 176.97.***.*** | M247 · AS9009 | ❌ 主机不通 | — | — | — | — |

> 「主机不通」= ICMP 100% 丢包 + 从新加坡节点侧二次验证 8388/1194/22/443 全闭 → 宿主机已下线，不是本地网络问题。
> 「ICMP 通、SS 死」= 宿主机在，但 8388 的 Shadowsocks 服务已停（OpenVPN 侧可能仍可用）。

### 稳定性

- 节点列表：6 次采样 IP 集合哈希 `4746368f` 6/6 相同 → **配置层完全静止**（不轮换、不新增）。
- 密码：多次拉取解密结果一致 → **凭证不轮换**。
- 节点可用性：轻载拨测 3 轮 4/10 全绿；高并发压测时 SG 出现 `dial tcp ...:8388: i/o timeout` → **共享凭据下的拥塞抖动**，不是封禁。

## 结论 / 建议

**能进池的**：`sg 38.180.***.***`、`us-dal 216.106.***.***`、`nl 5.61.***.***` —— 这三个出口独立、协议稳定、带宽够用，
以 `socks5://127.0.0.1:2210x` 形式喂给 new-api 即可（见 `docs/NEWAPI-HANDOFF.md`）。

**不建议进生产主池的**：DE（RTT 在 0.7–6.8 s 之间跳，探活能过但紧接着真实请求就 `rep=1`）、
US-NY（实测 7.2 s RTT，探活偶尔过、吞吐为 0）、其余 5 台（主机已下线）。

> R1 收尾时的最后一次验证：4 条清单里 SG/NL/US-DAL 三条稳定出网（出口 IP = 节点 IP），
> DE 在探活通过后 10 秒内再次 `rep=1` —— 所以 `refresh_pool.py` 的 `--max-rtt 1500` 只是
> **必要不充分**过滤，DE 这类节点建议直接删掉，不要指望它。

**诚实结论**：这是一个 **20 节点的白标小型农场**，能用但池子薄；优势是「零鉴权 + 永不轮换 = 一次收割长期有效」，
劣势是「全网用户共用同一批凭据 + 同一批 8388 端口 = 高峰期必然抢带宽」。

## 合规与风险

1. **凭证 ≠ 授权**。这些 VPS 与 Shadowsocks/OpenVPN 凭据属于 Jolt VPN 运营方（Jolt App Studio / Mudasser Khalid LLC）。
   把节点接入自己的生产代理池，等于无偿占用他人带宽与基础设施，属于**违反服务条款 + 未经授权的资源使用**。
   本仓库仅作为**逆向研究 / 协议还原 / 自建链路验证**的产物，**不要**直接商用或对外提供服务。
2. **凭据泄露面**：API Key 与 AES 密钥硬编码在 dex 里，任何拿到 APK 的人都能复现——但**不要**把本仓库的
   `nodes_decrypted.json` / `ovpn/*.ovpn` / `proxies.txt` 推上公开仓库（`.gitignore` 已排除）。
   另外 README / docs 里含**真实节点 IP**，若要开源请先统一打码（`samples/` 下已经是脱敏样例）。
3. **OpenVPN 配置含完整客户端证书与私钥**，等同于该节点的客户端身份，泄露 = 他人可冒用。
4. 建议优先把自己的代理池建在**自有或已授权**的基础设施上；本项目的价值在于**协议样本**与**白标 App 的通用破法**。

## 数据可信度标注

- `已验证`：harvest / probe / stress / demo 全部实际运行，输出见 `probe_result.json`、`stress_result.json`、`samples/`。
- `静态确认`：协议常量、AES 密钥、双 API 地址、OVPN 字段——均来自 `jadx_out/sources/com/joltapps/vpn/**`。
- `待验证`：OpenVPN 实际拨通能力（缺 TUN/root 环境）；demo 页面像素级渲染（本机无浏览器 MCP，仅 curl 端点验证）。
