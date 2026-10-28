# new-api 对接交接书（可直接粘给下一个会话）

两种用法：

- **A. 你要人工点几下**（最快，5 分钟）→ 看 §1
- **B. 交给另一个 Claude 会话去做**（改代码/建任务/排错）→ 把 §2 整段粘给它

---

## §1 人工接入（不动代码）

前提：本机已经跑起来过 `python refresh_pool.py --restart --rounds 2`，`proxies.txt` 里至少有 1 条。

### 步骤

1. **确认代理池活着**

   ```powershell
   cd C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\逆向产物\JoltVPN_4.9
   python probe.py --rounds 1
   type proxies.txt
   ```

   `proxies.txt` 长这样（每行一条，`#` 开头是注释，**不支持行尾注释**）：

   ```
   # Jolt VPN 代理池 · <时间>
   # 写入 3/10（探活存活 4，RTT>1500ms 剔除 1）
   socks5://127.0.0.1:22105
   socks5://127.0.0.1:22107
   socks5://127.0.0.1:22108
   ```

2. **让 new-api 读到它**（环境变量，改完必须重启 new-api）

   ```powershell
   setx TRYINGOPEN_PROXY_FILE "C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\逆向产物\JoltVPN_4.9\proxies.txt"
   ```

   也可以临时用 `TRYINGOPEN_PROXIES`（逗号分隔，一次性）：

   ```powershell
   setx TRYINGOPEN_PROXIES "socks5://127.0.0.1:22105,socks5://127.0.0.1:22107,socks5://127.0.0.1:22108"
   ```

3. **重启 new-api**，到后台看代理池卡片是否出现（来源名 = 文件名，即 `proxies.txt`）。

4. **验收**：后台点一次「测试」类操作，或看日志里是否出现 `tryingopen` 选用该池的记录。
   最强验收是用 python 直连节点验证（**不能用 curl，见 §3 坑 1**）：

   ```powershell
   python -c "import socksutil;print(socksutil.http_body(socksutil.http_get('127.0.0.1',22108,'http://208.95.112.1/json/?fields=query,country',10)[0]))"
   # 期望：{"country":"Singapore","city":"Singapore","query":"38.180.***.***"}
   ```

5. **挂定时任务**（每 6 小时刷新，宿主机存活会变）

   ```powershell
   schtasks /create /tn "JoltPoolRefresh" /tr "python C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\逆向产物\JoltVPN_4.9\refresh_pool.py --restart --rounds 2" /sc hourly /mo 6 /ru SYSTEM /f
   ```

---

## §2 粘给下个会话的指令（整段复制）

```text
任务：把本地 Jolt VPN 节点池接进 new-api。你只做对接与验证，不要改逆向脚本的协议逻辑。

## 已确认的环境事实（不要重新逆向、不要重新论证可行性）
- 工作目录：C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\逆向产物\JoltVPN_4.9
- new-api 源码：C:\Users\Administrator.DESKTOP-EGNE9ND\Desktop\公益服务网关\new-api
- 代理池形态：本机 sing-box 起 10 个 socks5 入站（127.0.0.1:22100..22109），
  每个入站固定路由到一个 Shadowsocks 节点；sing-box 配置在同目录 singbox.json。
- 可用清单：proxies.txt，只写「拨测存活 且 RTT<=1500ms」的节点，由 refresh_pool.py 生成。
- 实测稳定出口 3 个：22105(US-Dallas) / 22107(NL) / 22108(SG)；
  22102(DE) 探活能过但真实请求立刻失败，22109(US-NY) RTT 7s+，这两个不要用。
- 一键刷新：python refresh_pool.py --restart --rounds 2
  （收割→生成配置→配置变了才重启 sing-box→拨测→重写 proxies.txt）

## new-api 侧事实（已核对源码，不要猜）
- 代理来源：relay/channel/tryingopen/proxy_pool.go
  - 环境变量 TRYINGOPEN_PROXY_FILE：文件路径，逗号分隔可给多个文件
  - 环境变量 TRYINGOPEN_PROXIES：逗号分隔，兜底
  - 文件解析：逐行 bufio.Scanner → 跳过空行和 # 开头的整行 → 其余整行 url.Parse
    ⇒ 不支持行尾注释，注释只能整行
  - 来源卡片名 = filepath.Base(file)
- URL 白名单：common/proxy_url.go 的 parseProxyURL 只接受
  http / https / socks5 / socks5h —— socks5 合规可用
- 国内 DNS 可能污染 → 需要远端解析时用 socks5h://

## 你要做的
1. 读上面两个文件确认现状（读，不要改）。
2. 跑一次 python probe.py --rounds 1，确认 proxies.txt 有条目且每条 socks5 都能出网
   （验证必须用 python socksutil，禁止用 curl，本机 curl 没编 SOCKS 会静默直连导致假阳性）。
3. 设置 TRYINGOPEN_PROXY_FILE 指向绝对路径的 proxies.txt，重启 new-api。
4. 按 docs/NEWAPI-HANDOFF.md §3 的三层验收逐条过，把实际命令与输出贴出来。
5. 若 new-api 在 Docker 里：127.0.0.1 指容器自身。要么同 network namespace，
   要么把 gen_singbox.py 的 listen 改 0.0.0.0 并把清单里的 127.0.0.1 换成宿主机可达 IP。
   这条必须先跟我确认再动手。
6. 只在必要处改代码；改完必须给出「改了哪个文件、为什么、怎么回归验证」。

## 禁止
- 不要改 harvest.py / probe.py 的协议与判定逻辑（已验证过，改了要重新取证）
- 不要提交 nodes_decrypted.json / ovpn/ / proxies.txt / jolt_secrets.py（gitignore 已排除）
- 不要把节点用于对外提供代理服务（第三方基础设施，仅内网联调用）
- 不要用 curl 验证 socks 代理
```

---

## §3 三个必须知道的坑

1. **本机 `curl` 编译时没带 SOCKS**（`curl --version` 的 Protocols 列表里没有 socks）。
   `curl --socks5 127.0.0.1:<甚至一个死端口>` 会**静默直连目标并返回 200**，造成假阳性。
   验证一律用 `python` + `socksutil.py`，或 `C:\Windows\System32\curl.exe`。

2. **本机网络对 `ipinfo.io` / `ifconfig.me` 有 TLS 中间人**：直连和走隧道都返回同一个本地出口 IP
   （`183.250.230.8`），会让人误判「隧道是假的」。探测目标请用 **IP 字面量**
   （`http://208.95.112.1/json/?fields=query,country,city`）。

3. **端口不是固定的**：`gen_singbox.py --base-port` 决定起始端口，节点顺序变化时端口跟着变。
   **永远从 `proxies.txt` 或看板 `/api/nodes` 读，不要硬编码 22105/22107/22108。**

---

## §4 备选接入方式：Clash / mihomo

不想自己维护清单，就把节点当订阅喂给 mihomo，让它做 url-test：

```powershell
python demo_server.py --port 8944
# Clash 订阅： http://127.0.0.1:8944/sub/clash
# ss:// 订阅：  http://127.0.0.1:8944/sub
```

mihomo 起 `mixed-port: 7890` 之后，new-api 指 `socks5://127.0.0.1:7890` 一条即可。
好处：坏节点 mihomo 自己会剔，`proxies.txt` 可以直接不要。
坏处：多一层进程、故障面更大。
