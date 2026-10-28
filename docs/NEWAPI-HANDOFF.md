# new-api 对接交接包 · Jolt VPN 节点池

> 面向对接方（运维 / 后端）。读完这份就能自己跑起来，不需要看逆向细节。
> 逆向过程看 `docs/REPORT.md`，协议细节看 `docs/PROTOCOL.md`。

---

## 0. 你能拿到什么

| 交付物 | 路径 | 说明 |
|---|---|---|
| 代理池（socks5 清单） | `proxies.txt` | 每行 `socks5://127.0.0.1:2210X`，**只含拨测通过的节点** |
| sing-box 配置 | `singbox.json` | 10 个本地 socks5 入站 → 各自一个 SS 出站 |
| 端口映射 | `portmap.json` | 端口 ↔ 国家/城市/层级/服务器，给看板与排错用 |
| OpenVPN 配置 | `ovpn/*.ovpn` | 10 份完整配置，可导入任意 OpenVPN 客户端 |
| 一键刷新 | `refresh_pool.py` | 收割 → 生成 → 重启 → 拨测 → 落 `proxies.txt` |
| 看板 | `demo_server.py` | 存活 / 出口 IP / RTT / 带宽，人眼可查 |

**当前实测可用**（2026-10-29）：

| 端口 | 出口 | 国家 | RTT | 单流 | 6 并发 |
|---|---|---|---|---|---|
| 22108 | 38.180.***.*** | 🇸🇬 SG | 139–196 ms | 1.8–8.7 Mbps | 15.2 Mbps |
| 22105 | 216.106.***.*** | 🇺🇸 US | 428–447 ms | 7.5–7.9 Mbps | 36.7–41.1 Mbps |
| 22107 | 5.61.***.*** | 🇳🇱 NL | 745–884 ms | 4.1–4.7 Mbps | 15.4–16.7 Mbps |
| 22102 | 170.101.***.*** | 🇩🇪 DE | 2264–6751 ms | ~0 | 不可用（建议从池里剔掉） |

> 端口号由 `gen_singbox.py --base-port 22100` 决定，节点顺序变化时端口会跟着变——**永远从
> `proxies.txt` 或 `/api/nodes` 读，不要硬编码端口**。

---

## 1. 环境准备

```powershell
pip install cryptography                       # 唯一 Python 依赖
# sing-box（不自动下载，手动放好）：
#   https://github.com/SagerNet/sing-box/releases/download/v1.14.4/sing-box-1.14.4-windows-amd64.zip
#   解压到 tools\singbox\sing-box-1.14.4-windows-amd64\sing-box.exe
```

首次运行：

```powershell
python refresh_pool.py --restart --rounds 2
```

它会依次：`harvest.py` → `gen_singbox.py` → （配置变了才）重启 sing-box → `probe.py` → 写 `proxies.txt`。

`--max-rtt`（默认 **1500 ms**）会把长期高延迟节点从 `proxies.txt` 里剔掉 —— 实测 DE 节点常在
2200–6800 ms 且吞吐为 0，探活显示"在线"但没有实用价值，必须过滤，否则会污染代理池的加权分配。

---

## 2. 接进 new-api（三种方式，任选）

### 方式 A：`TRYINGOPEN_PROXY_FILE`（推荐）

new-api 的代理池读 `relay/channel/tryingopen/proxy_pool.go` 里 `TRYINGOPEN_PROXY_FILE` 指定的文件，
逗号分隔可给多个文件，支持整行 `#` 注释，**不支持行尾注释**（解析器对整行做 `url.Parse`）。

```powershell
# 注意：必须用绝对路径，且必须能被 new-api 进程读到
setx TRYINGOPEN_PROXY_FILE "D:\reverse\JoltVPN_4.9\proxies.txt"
# 重启 new-api 生效
```

`proxies.txt` 形如：

```
# Jolt VPN 代理池 · 2026-10-29T07:23:59+0800
# 写入 3/10（探活存活 4，RTT>1500ms 剔除 1）
# 22105 United States/Dallas 216.106.***.*** rtt=444.5ms
# 22107 Netherlands/Amsterdam 5.61.***.*** rtt=779.0ms
# 22108 Singapore/Singapore 38.180.***.*** rtt=165.5ms
socks5://127.0.0.1:22105
socks5://127.0.0.1:22107
socks5://127.0.0.1:22108
```

**协议支持已核对源码**（`common/proxy_url.go:34-38`）：new-api 只接受
`http` / `https` / `socks5` / `socks5h` 四种 scheme —— `socks5://` 正好在白名单里，可直接用。
如果目标域名在本机 DNS 被污染（国内常见），把 scheme 换成 `socks5h://` 让 **远端解析**，
避免 local-resolve 拿到脏 IP。本仓库的探针走的就是远端解析（SOCKS5 `ATYP=3` 域名形式）。

> **Docker 部署注意**：new-api 容器里的 `127.0.0.1` 不是宿主机。要么把 sing-box 也放进同一个
> 容器/同一个 network namespace，要么 `gen_singbox.py` 里把 `listen` 改成 `0.0.0.0` 并把
> `proxies.txt` 的 `127.0.0.1` 换成 `host.docker.internal`（Windows/Mac）或宿主机网关 IP。

### 方式 B：`TRYINGOPEN_PROXIES`（临时/最少改动）

```powershell
setx TRYINGOPEN_PROXIES "socks5://127.0.0.1:22108,socks5://127.0.0.1:22105,socks5://127.0.0.1:22107"
```

缺点：节点变化要手动改，不推荐长期用。

### 方式 C：Clash / mihomo 订阅

```powershell
python demo_server.py --port 8944
# 订阅地址（Clash）：http://127.0.0.1:8944/sub/clash
# 订阅地址（ss://）： http://127.0.0.1:8944/sub
```

把 `/sub/clash` 喂给 mihomo，由 mihomo 暴露 `mixed-port: 7890`，再让 new-api 指向
`socks5://127.0.0.1:7890`。好处：mihomo 自带 url-test 自动剔除坏节点，不需要你自己维护列表。

---

## 3. 三层验收（照着做，别跳）

```powershell
# 第 1 层：节点列表能拉到、能解密
python harvest.py
#   期望输出：合计 20 个唯一节点：shadowsocks 10 · openvpn 10

# 第 2 层：socks5 层通
python probe.py --rounds 2
#   期望：存活 >= 3/10，exit_ip 与节点 IP 一致

# 第 3 层：真实业务路径（从 new-api 里发一个请求）
#   在 new-api 后台 → 渠道 → 选一个走代理池的渠道 → 测试
#   或直接：
curl --socks5-hostname 127.0.0.1:22108 https://ipinfo.io/ip
#   ⚠️ 本机自带的 curl 编译时未带 SOCKS 支持，--socks5 会被静默忽略并直连！
#      要验证请用 python：python -c "import socksutil;print(socksutil.http_get('127.0.0.1',22108,'http://208.95.112.1/json/?fields=query',8)[0][-60:])"
```

**判断标准**：

| 现象 | 含义 |
|---|---|
| `probe.py` 输出 `exit_ip` == 节点 IP | ✅ 真在走隧道（不是本地直连） |
| `proxies.txt` 里每行都带 `socks5://` | ✅ 格式对，new-api 能解析 |
| new-api 侧日志出现 `all N proxies unavailable` | 池里节点全挂了 → 重跑 `refresh_pool.py` |

---

## 4. 运维 SOP

| 频率 | 动作 | 命令 |
|---|---|---|
| 每 6 h | 全量刷新（宿主机存活会变，列表本身不变） | `python refresh_pool.py --restart --rounds 2` |
| 每 24 h | 看一眼看板，确认存活数与出口 IP 没突变 | `python demo_server.py --port 8944` |
| 发现延迟集体上 2000ms+ | 该批节点被高峰占用 → 临时把 DE 这类高延迟端口从文件里注释掉 | — |
| new-api 大量 429 / 超时 | 不是节点问题，是上游风控；代理池只是通道 | 查 new-api 侧日志 |

Windows 定时任务（每 6 小时）：

```powershell
schtasks /create /tn "JoltPoolRefresh" /tr "python D:\reverse\JoltVPN_4.9\refresh_pool.py --restart --rounds 2" /sc hourly /mo 6 /ru SYSTEM /f
schtasks /query /tn "JoltPoolRefresh" /v /fo list
```

**幂等性**：`refresh_pool.py` 每次都会重写 `singbox.json`；配置字节不变就**不重启** sing-box（避免抖断连接）。
`proxies.txt` 每次整体覆写，不会累积旧记录。

---

## 5. 排错表

| 症状 | 根因 | 处置 |
|---|---|---|
| `probe.py` 全 `rep=1 (general failure)` | 节点宿主机挂了 | 重跑 `harvest.py`（列表可能会换 IP）；仍全挂说明该批节点整体停服 |
| `curl --socks5` 返回本地 IP | 本机 curl 没编 SOCKS | 用 `socksutil.py` 或 Windows `System32\curl.exe` |
| 隧道看板显示在线但客户端连不上 | new-api 在容器里，`127.0.0.1` 指容器自己 | 见 §2-A 的 Docker 注意 |
| `AES decrypt` 抛 `BAD_PADDING` | 运营方通过 Firebase Remote Config 换了 Key/IV | 抓 `jv_secret_iv` / `jv_encryption`，把 `id`+`size` 拼起来替换 `harvest.py` 里的常量 |
| `harvest.py` 双源都超时 | Cloudflare 慢/抖（实测备 API 可达 19.5 s） | 加大 `--timeout`；或只留主 API |
| sing-box 起不来 | 端口被占（22100–22109） | `netstat -ano \| findstr 2210`，换 `--base-port` |
| `print` 抛 `UnicodeEncodeError` | Windows 控制台 GBK | 已在 `winfix.py` 处理；若自己写脚本要 `import winfix` |
| demo 打开是别人的页面 | 端口被占（本机 8942 有 node.exe） | 换 `--port`，本仓库默认 8944 |

---

## 6. 边界与风险（必读）

1. **合规**：节点与凭据属于 Jolt VPN 运营方（Jolt App Studio / Mudasser Khalid LLC，VPS 在 GTHost /
   M247 / OVH / Scalaxy）。接入自己的业务池 = 无偿占用他人基础设施 + **违反服务条款**。
   建议只用于**协议研究 / 内网联调**，不要对外提供服务。
2. **凭据敏感**：`nodes_decrypted.json`、`ovpn/*.ovpn`、`proxies.txt` 含完整凭据（OVPN 还含客户端私钥），
   **禁止提交公开仓库**。`.gitignore` 已排除，自行加目录前先看一眼。
3. **池子薄**：可用 3–4 个出口，且全站用户共用同一批凭据与同一批 8388 端口，**高峰期必然抢带宽**。
   别把它当主池，当补充池 / 备用池。
4. **无 SLA**：运营方随时可能换 Key、改 AES 常量、迁移宿主机。`harvest.py` 一旦报解密失败，
   说明协议变了，需要重新逆向（预留工作量）。
5. **未验证项**：OpenVPN 侧未做实际拨通（本机缺 TUN/root）。`ovpn/*.ovpn` 只是**导出了配置**，
   不代表链路验证过。
