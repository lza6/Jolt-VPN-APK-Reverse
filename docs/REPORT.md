# Jolt VPN v4.9 b40 逆向报告（R1）

时间：2026-10-29 · 目标：`Jolt VPN v4.9 b40 (Premium by @ElaMods).apk`（29,031,851 B）
包名：`com.joltapps.vpn` · 版本名：`4.9`（`JoltVPN~v-4.9_release`）· 破解版（ElaMods）

---

## 1. 侦察路径（实际走过的顺序）

| 步 | 手段 | 产出 |
|---|---|---|
| 1 | `unzip` 解包 → 4 个 dex（8.8 / 8.9 / 10.1 / 1.0 MB） | `x/` |
| 2 | 提取 dex 全量字符串表（217,834 条唯一） | `dex_strings.txt` |
| 3 | 正则扫 `https?://` | 149 条，过滤广告 SDK（inmobi/vungle/ads）后剩 2 条自家域名 |
| 4 | 扫 `api/...` 路径 | 命中 `api/getAllServers`、`api/android/config.php` |
| 5 | 探活两个域名 | 根路径 404（Express），`/api/getAllServers` 返回 `401 No Authorization Key Found` |
| 6 | 试请求头：`Authorization` / `apiKey` / `X-Api-Key` / `?key=` | 全返回 `No Authorization Key Found` |
| 7 | 试 `key:` 头 | 返回变成 `Invalid Authorization Key` → **头名确认为 `key`** |
| 8 | `jadx 1.5.1` 反编译 12,421 个类 | `jadx_out/sources/` |
| 9 | 读 `network_call/api/ApiService.java` | 拿到 **两条硬编码 key + 两个 base URL** |
| 10 | 用 key 请求 | `200`，20 条节点，4 个字段为密文 |
| 11 | 读 `crypto/AESEncryptionUtil.java` | 拿到 **AES-256-CBC 的 Key/IV（主备各一套）** |
| 12 | 解密 | 全部 20 条成功，IP/加密方式/密码/OVPN 全文 |

**总耗时**：从解包到全量解密约 40 分钟，无 Frida、无 MITM、无模拟器。这是白标 VPN 里**最省事**的一类。

### 关键代码

`com/joltapps/vpn/network_call/api/ApiService.java`

```java
public interface ApiService {
    @Headers({"key:Kxf18A***（已脱敏）"})
    @GET("api/getAllServers") Call<ServerDataResponse> getServersData();

    @Headers({"key: E$uTzF***（已脱敏）"})
    @GET("api/getAllServers") Call<ServerDataResponse> getServersDataSecondary();
}
```

`com/joltapps/vpn/network_call/repo/ServerDataRepository.java`

```java
public static final String KEY_1 = "y7Wn***（已脱敏）";           // SECRET_IV 的前 8 位
public static final String SECONDARY_KEY_1 = "x3Vm***（已脱敏）"; // SECRET_IV2 的前 9 位
```

`com/joltapps/vpn/crypto/AESEncryptionUtil.java`

```java
SECRET_IV  = "y7Wn***（已脱敏）";   SECRET_IV2 = "x3Vm***（已脱敏）";
// 主 key: "93TR***（已脱敏）"
// 备 key: "47DE***（已脱敏）"
```

> 反编译里 `AESEncryptionUtil` 的 key 是**内联在方法体里的字符串常量**，jadx 直接给出；连脱壳都不用。
> （`getUnsafeOkHttpClient()` 里还塞了 `TrustManager` 全信任 + `HostnameVerifier` 全通过 —— 这种 App 的
> 传输安全形同虚设，中间人抓包会比静态分析更慢。）

---

## 2. 应用架构判定

| 组件 | 判定 | 依据 |
|---|---|---|
| SS 内核 | **shadowsocks-android 系（`libsslocal.so` + `libtun2socks.so` + `libredsocks.so`）** | `lib/arm64-v8a/`，另带 `assets/acl/bypass-china.acl` |
| OVPN 内核 | **OpenVPN for Android（`de.blinkt.openvpn` 包名，`libopenvpn.so` 6.5 MB）** | 反编译里存在 `de.blinkt.openvpn.*` 全套类 |
| 网络层 | Retrofit2 + OkHttp（`api/getAllServers`） | `network_call/retrofit/RetrofitInstance.java` |
| 配置下发 | **Firebase Remote Config**（可远程改 Key/IV/广告开关） | `helper/RemoteHelper.java` |
| 变现 | AdMob + InMobi + Vungle + OneSignal | `assets/ads.txt`、`androidx` 广告类 |
| 测速 | 第三方库 `pk.farimarwat.speedtest`（`api/android/config.php` 属于它，**不是节点接口**） | `pk/farimarwart/.../SpeedTestServices.java` |

> 顺手排掉一个误判：`api/android/config.php` 看着像节点配置接口，实际是 speedtest 库的测速配置，
> 与节点池无关（GET/POST 均 404）。

---

## 3. 节点池真实画像

### 3.1 拓扑

20 个节点 = 10 个 Shadowsocks `:8388` + 10 个 OpenVPN `UDP:1194/1195`，**同一批宿主机双协议并存**
（同一个 `ipaddress` 在 SS 和 OVPN 两种 protocol 里各出现一次）。宿主机分属 4 家：

```
GTHost   AS63023  (DE / ES / FR / US-DAL)      x4
M247     AS9009   (SG / JP / US-NY)            x3
OVH      AS16276  (CA / GB)                    x2
Scalaxy  AS58061  (NL, ISPIRIA 代管)            x1
```

统一特征：全站 SS 端口都是 `8388`、全站加密方式都是 `chacha20-ietf-poly1305`、密码 12–16 位随机串、
OVPN 用同一套 `Easy-RSA CA`（签发 2026-09-25）。→ **典型白标一键部署脚本产物**（4 家 VPS 上批量拉起）。

### 3.2 存活（三重交叉验证）

| 验证层 | 手段 | 结果 |
|---|---|---|
| L3 | ICMP ×2 | 5 台有回包（DE/NL/SG/US-DAL/US-NY），5 台 100% 丢包（ES/FR/GB/CA/JP） |
| L4 | 本机 TCP connect :8388 | 5 台 open（ES 不通但其余一致） |
| L7 | SOCKS5 → SS 握手 → `ip-api` | **4 台通**（SG/US-DAL/NL/DE），US-NY 握手被拒，5 台主机不通 |
| 交叉 | 从 **SG 节点内部**再探那 6 台失败节点的 8388/1194/22/443 | 全 `rep=1`（只有 ES:443 通） → **不是本地网络问题，是宿主机真的下线** |

结论：**4/10 可用（40%）**，US-NY 属于「宿主机活着但 Shadowsocks 服务已停」。

### 3.3 稳定性

- 连续 6 次采样（30 s 间隔）节点 IP 集合 md5 全部相同（`4746368f`）→ **不轮换、不新增**。
- 多次解密得到的 SS 密码完全一致 → **凭证不轮换**。
- 轻载拨测 3 轮：SG/NL/US-DAL/DE 均 100% 在线。
- **高并发压测时 SG 出现 `dial tcp 38.180.***.***:8388: i/o timeout`**（单流 6/6 成功、探活偶发失败）
  → 这是**共享凭据下的端口拥塞**，不是 IP 被封（同 IP 的 ICMP 一直 62–74 ms，很稳）。

含义：**配置层极稳，链路层会抖**。做池子要按"最低可用集"设计，别假设 10 个都能用。

---

## 4. 实测性能

环境：中国出口直连 → sing-box 1.14.4（Windows amd64）→ 各节点独立 socks5 入站。

| 节点 | RTT P50 | 单流 (2 MB) | 6 并发聚合 | 并发成功 |
|---|---|---|---|---|
| SG 38.180.***.*** | 139–196 ms | 1.81 – 8.70 Mbps | 15.22 – 15.25 Mbps | 6/6 |
| US-DAL 216.106.***.*** | 428–447 ms | 7.47 – 7.93 Mbps | **36.66 – 41.07 Mbps** | 6/6 |
| NL 5.61.***.*** | 745–884 ms | 4.13 – 4.74 Mbps | 15.41 – 16.72 Mbps | 6/6 |
| DE 170.101.***.*** | 2264–6751 ms | 0.00 | — | 0/6（全部源超时） |

区间是多次跑的跨度，不是误差：SG 的波动来自共享凭据下的抢占（同一时段单流从 8.7 掉到 1.8）。

压测源最终定型为 `http://speedtest.ams1.nl.leaseweb.net/10mb.bin`（3/3 节点可用），
备选 `leaseweb ubuntu 镜像` / `thinkbroadband 5MB` / `speed.cloudflare.com/__down`。

> 两个踩坑（都会直接导出错误结论）：
> 1. 一开始用 `speedtest.tele2.net` / `cachefly` 当压测源，4 个节点只有 1 个能拉，差点误判成"节点全废"。
> 2. `speed.cloudflare.com/__down` 首轮是最好用的（DAL 7.44 Mbps），但**被反复压了约 1 小时后全部超时**
>    —— 出口 IP 被 Cloudflare 侧限流了。这本身是个信号：**这批共享出口 IP 的"名誉"已经被用脏了**。
> 换了 leaseweb 源后 SG/DAL/NL 立刻恢复 6/6。**测速源选不对，会得出完全相反的结论。**

---

## 5. 未做 / 未破

| 项 | 状态 | 原因 | 需要什么 |
|---|---|---|---|
| OpenVPN 实际拨通 | ⏳ 待验证 | OpenVPN 需要 TUN 设备 + 路由接管，Windows 侧需管理员 + wintun/TAP 驱动；WSL 侧 `openvpn 2.6.19` 已装且 `/dev/net/tun` 存在，但 `sudo` 需要密码 | 管理员权限 / WSL root |
| OVPN → SOCKS 桥 | ⏳ 待验证 | 同上，还需要 `tun2socks`/`hev-socks5-tunnel` 把 tun 流量转 socks | 同上 |
| Firebase Remote Config 值 | ⏳ 待验证 | Key/IV 有远程覆盖通道，但当前线上返回空、走默认值；未去拉 Firebase 配置项 | 抓 `firebaseinstallations` + `/v1/projects/.../remoteConfig` |
| 换 IP / 抗封策略 | 无需 | 本次观察到 IP 不轮换，无客户端侧 IP 池逻辑 | — |

---

## 6. 排查踩坑清单（下次直接跳过）

1. **本机 `curl` 不支持 SOCKS**（`curl --version` 的 `Protocols:` 里没有 socks）。用 `--socks5` 指向死端口
   仍然直连成功且不报错 —— 这是最容易造出"假阳性"的坑。**验证代理一律用 `socksutil.py`。**
2. **本机网络存在 TLS 中间人**：`ip.seeip.org` 报 `SEC_E_WRONG_PRINCIPAL`、`ipinfo.io`/`ifconfig.me`
   直连与走隧道返回**同一个本地出口 IP**（183.250.230.8）。→ 探测目标必须用 **IP 字面量**
   （`http://208.95.112.1/json/`）或 **DNS over TCP 8.8.8.8**（直连 131 ms vs 走隧道 664 ms，能区分路径）。
3. **sing-box `route.rules` 的 `inbound` 字段是有效的**，可以一个进程开 N 个 socks 入站分别路由到 N 个
   出站；已用 `21001→ss1(DE)`、`21005→ss5(US)`、`21007→ss7(NL)`、`21009→ss9(SG)` 逐一验证映射正确。
4. **Windows 控制台默认 GBK**：脚本里打 emoji/中文会在 `print` 时抛 `UnicodeEncodeError`，
   被 `subprocess` 拉起时尤其容易踩（demo 的 /refresh 就因此静默失败过一次）。已用 `winfix.py` 统一修。
5. **端口误判**：本机 `8942` 已被另一个 node.exe 占用（`0.0.0.0:8942`），Python 绑 `127.0.0.1:8942`
   会"看似成功"但请求落到谁身上取决于绑定优先级。demo 默认端口已改 `8944`。
6. **jadx 的 `-r` 是 `--no-res`（不导出资源）**，不是 "导出资源"。要拿 `AndroidManifest.xml` 得用
   `jadx --no-src -d res_out <apk>`。本仓库的协议还原**不需要** manifest，所以没受影响。

---

## 7. 证据文件

| 文件 | 内容 |
|---|---|
| `nodes_decrypted.json` | 20 个节点的明文（IP / 加密方式 / 密码 / 来源） |
| `jolt_primary.json` / `jolt_secondary.json` | 原始 API 响应（密文，可复算） |
| `ovpn/*.ovpn` | 10 份解密后的完整 OpenVPN 配置 |
| `probe_result.json` | 逐节点拨测：存活 / 出口 IP / RTT / 可用率 / 错误栈 |
| `stress_result.json` | 单流 + 并发压测明细 |
| `snapshot_series.json` | 6 次采样，用于证明节点列表静止 |
| `samples/asn_lookup.json` | 10 个 IP 的 ISP / ASN / 反解 |
| `singbox.log` | sing-box 运行日志（含 `dial tcp ...:8388: i/o timeout` 原始记录） |
