# 脱敏说明（先读这个）

本仓库是**研究归档**，发布前经过自动脱敏。目标：留全部**方法与结构**，去掉全部**活凭据**。

## 被脱敏的（拿不到就别想直接跑）

| 类别 | 处理方式 | 说明 |
|---|---|---|
| API 请求头 Key（两条） | `Kxf18A***（已脱敏）` | 换成明文就能拉节点，所以必须去掉 |
| 字段解密 AES Key / IV（主备各一套） | `93TR***（已脱敏）` | 同上 |
| 节点 IP | `38.180.***.***` | 前两段保留，用于说明机房/ASN |
| Shadowsocks 密码 | `Y8***` | 12–16 位随机串 |
| `ss://` 链接的 userinfo | `<REDACTED-USERINFO>` | base64(method:password) 里含密码 |
| OpenVPN 的 `ca` / `cert` / `key` / `tls-crypt` | `...REDACTED...` | OVPN 是纯证书认证，泄露证书等于交出节点身份 |

## 被保留的（这些才是研究价值）

- 完整协议路径：`GET /api/getAllServers`、双 base URL、鉴权**机制**（单请求头、服务端直接比对字符串）
- 加解密**算法与流程**：`AES/CBC/PKCS5Padding`、字段→密文映射、主备切换逻辑
- 节点池**画像**：10 SS + 10 OVPN、端口约定（8388 / 1194-1197）、加密方式（chacha20-ietf-poly1305 / AES-128-GCM）
- 全部工程代码：收割 / 生成 / 拨测 / 压测 / 看板 / 一键刷新
- 实测数据：存活率、RTT 分布、单流与聚合吞吐、ASN 归属、稳定性采样结论
- 全部踩坑与排错表（本仓库最大的复用价值）

## 怎么在本地还原成可用版本

```bash
cp jolt_secrets.example.py jolt_secrets.py   # 按 docs/PROTOCOL.md 第 2–3 节从 APK 里提常量，填进去
pip install cryptography
python harvest.py                            # 需要能连上 joltappstudio.com
```

`jolt_secrets.py` 已在 `.gitignore` 里，**填完也不要提交**。

## 为什么这么做

1. **第三方基础设施**：节点与凭据属于 Jolt VPN 运营方（Jolt App Studio / Mudasser Khalid LLC），
   公开活凭据 = 协助他人无偿占用其带宽，也可能构成对运营方的实际损害。
2. **OpenVPN 证书含客户端私钥**：公开等于公开节点身份，任何人都能冒用。
3. **研究价值不在凭据**：凭据会轮换、节点会下线；可复用的是**方法**（白标 App 的通用破法）与**判据**
   （怎么区分"探活通"和"真能用"）。

本仓库的代码是完整可运行的 —— 只差你自己从 APK 里把那几个常量提出来（这也正是逆向的练习部分）。
