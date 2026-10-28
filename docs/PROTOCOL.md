# Jolt VPN v4.9 b40 协议手册

> 目标：不依赖原 App，纯 HTTP 拿到完整节点池并解密。
> 所有常量均来自 `jadx_out/sources/` 反编译结果，**可逐行对照验证**。

---

## 1. 攻击面总览

```
APK (com.joltapps.vpn)
└── Retrofit  (network_call/api/ApiService.java)
    ├── base1: https://api.joltappstudio.com/      header key: Kxf18A***（已脱敏）
    └── base2: https://api.mudasserkhalidllc.com/  header key: E$uTzF***（已脱敏）
         └── GET api/getAllServers   → 20 条节点（10 shadowsocks + 10 openvpn）
              └── AESEncryptionUtil (crypto/AESEncryptionUtil.java)
                   └── ipaddress / encryption / password / server_content 四个字段全部 AES 加密
```

**没有登录、没有设备注册、没有请求签名、没有设备指纹**。唯一门槛是那个硬编码的 `key` 请求头。

---

## 2. 节点列表接口

```http
GET /api/getAllServers HTTP/1.1
Host: api.joltappstudio.com
key: Kxf18A***（已脱敏）
User-Agent: okhttp/4.12.0
```

响应：

```json
{
  "code": 200,
  "data": [
    {
      "country_name": "Spain",
      "city_name": "Madrid",
      "flag": "es",
      "ipaddress": "jCH+g8FMWkfGdiBE35y0Zw==",
      "port": 8388,
      "type": "free",
      "protocol": "shadowsocks",
      "tag": "New",
      "encryption": "WeXGR/TcxVVQnChWVf0mU6Q9csvAxzlCNBWAeSU6e1U=",
      "password": "m+PCt9n1+4i/Dpiy3h2NzQ=="
    }
  ]
}
```

要点：

| 观察 | 含义 |
|---|---|
| 只接受 GET，POST → `Cannot POST /api/getAllServers` | Express 路由，`Allow: GET,HEAD` |
| `Server: cloudflare` + `X-Powered-By: Express` | Cloudflare → Node/Express 后端 |
| 缺 `key` 头 → `{"code":401,"message":"No Authorization Key Found"}` | 判定依据是**请求头是否存在** |
| `key` 值错误 → `{"code":401,"message":"Invalid Authorization Key"}` | 值直接比对，无时效、无签名 |
| 两个 base 返回的节点集合逐条相同 | 主备冗余，不是两套池 |
| 加 `?type=premium` / `?protocol=...` 等参数 | 不影响返回，服务端忽略 |

> ⚠️ 响应可能**很慢**（实测 2.7–19.5 s）偶尔超时。`harvest.py` 内置 3 次重试 + 45 s 超时。

---

## 3. 字段解密

`crypto/AESEncryptionUtil.java`：

```java
ALGORITHM      = "AES"
TRANSFORMATION = "AES/CBC/PKCS5Padding"
SECRET_IV      = "y7Wn***（已脱敏）"          // 主 API
SECRET_IV2     = "x3Vm***（已脱敏）"          // 备 API
// 密钥（同文件 decrypted 分支里的字面量）
主: "93TR***（已脱敏）"        // 32 字节 → AES-256
备: "47DE***（已脱敏）"
```

选择逻辑（`IS_PRIMARY_API` from SharedPreferences，默认 `true`）：

| 场景 | Key | IV |
|---|---|---|
| 主 API | `93TR***（已脱敏）` | `y7Wn***（已脱敏）` |
| 备 API | `47DE***（已脱敏）` | `x3Vm***（已脱敏）` |

解密算法（伪代码）：

```python
plain = AES256CBC(key, iv).decrypt(base64decode(field)).unpad_pkcs5()
```

> 注意 `RemoteHelper.mRemoteResponseModel.getJvSecretIv()/getJvEncryption()` 可以从 Firebase Remote Config
> 动态覆盖 Key/IV（`id + size` 拼成 16 字节 IV / 32 字节 Key）。**当前线上返回空 → 走上面硬编码默认值**。
> 若日后接口开始返回 `BAD_PADDING`，去 Firebase Remote Config 里捞 `jv_secret_iv` / `jv_encryption` 的
> `id` 与 `size` 两段拼起来即可，算法不变。

### 字段语义

| 字段 | 加解密 | shadowsocks | openvpn |
|---|---|---|---|
| `ipaddress` | ✅ AES | 服务器 IP | 服务器 IP |
| `port` | ❌ 明文 | 8388 | `null`（端口写死在 ovpn 里） |
| `encryption` | ✅ AES | `chacha20-ietf-poly1305` | 缺失 |
| `password` | ✅ AES | SS 密码（12–16 位） | 缺失 |
| `server_content` | ✅ AES | 缺失 | 整份 `.ovpn` 文本（含 ca/cert/key/tls-crypt） |
| `flag` / `country_name` / `city_name` / `type` / `tag` | ❌ 明文 | — | — |

---

## 4. 最小实现（30 行）

```python
import base64, json, urllib.request
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BASE, KEY = "https://api.joltappstudio.com/", "Kxf18A***（已脱敏）"
AES_KEY, IV = b"93TR***（已脱敏）", b"y7Wn***（已脱敏）"

def dec(b64):
    ct = base64.b64decode(b64)
    d = Cipher(algorithms.AES(AES_KEY), modes.CBC(IV)).decryptor()
    pt = d.update(ct) + d.finalize()
    return pt[:-pt[-1]].decode()

req = urllib.request.Request(BASE + "api/getAllServers", headers={"key": KEY})
data = json.load(urllib.request.urlopen(req, timeout=45))["data"]
for n in data:
    print(n["protocol"], dec(n["ipaddress"]), n["port"],
          dec(n["encryption"]) if n.get("encryption") else "-",
          dec(n["password"]) if n.get("password") else "-")
```

输出（首条）：

```
shadowsocks 167.17.***.*** 8388 chacha20-ietf-poly1305 Y8***
```

---

## 5. OpenVPN 节点

`server_content` 解密后即**完整可用的 OpenVPN 客户端配置**：

```
client
dev tun
proto udp
remote 198.244.***.*** 1194
remote 198.244.***.*** 1195
remote-random
cipher AES-128-GCM
<ca> ... </ca>
<cert> ... </cert>
<key> ... </key>
<tls-crypt> ... </tls-crypt>
```

- `ca` 显示 `Easy-RSA CA`、签发时间 2026-09-25 → 运营方自建 PKI，**不是** OpenVPN Access Server 商业版。
- 端口约定：`1194`/`1195`（部分节点 `1194–1197`）。
- 证书 + `tls-crypt` 都在包里 → **拿到配置就能连，不需要账号密码**。
- 本机没有 root/TUN 环境，**未做实际拨通验证**（见 `docs/REPORT.md` 第 5 节）。

---

## 6. 必避坑

1. **本机 `curl` 编译时没带 SOCKS**：`curl --socks5 127.0.0.1:<死端口>` 会**静默直连**目标，不报错。
   验证代理时千万别用 `curl`，用 `socksutil.py`。这是本次排查掉了半小时的坑。
2. **别用域名当探测目标**：本机所在网络对 `ipinfo.io` / `ifconfig.me` 等域名有中间人劫持，
   直连和走隧道都返回同一个本地出口 IP，会造成"隧道是假的"误判。用 **IP 字面量**（如
   `http://208.95.112.1/json/`）或 **DNS over TCP 到 8.8.8.8** 交叉验证。
3. **两个 base 的延迟差异极大**：主 API 2.7–5.4 s，备 API 曾达 19.5 s。别把超时设成 10 s。
4. **加密字段不是 JSON 里的 base64 URL-safe**，是标准 base64（含 `+` `/` `=`），别用 urlsafe 解。
5. **`type` 只有 `free`/`premium` 两种取值，但对节点接口没有过滤作用**——两个层级同时返回，
   premium 节点（JP/NL/SG/US-NY）也能直接连。
6. **`id` 字段响应里不返回**，数据类里 `id` 恒为 0，不要拿它做唯一键；用 `(protocol, ip, port)`。
