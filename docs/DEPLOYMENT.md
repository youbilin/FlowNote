# FlowNote 部署指南

**给拼节点的普通用户，一张清晰、私密的流量手记。**

v0.3.0：连接自己的节点 → 打开 `https://traffic.你的域名/` → 查看当前账号的剩余流量、上传下载、配额和有效期。**不需要开启 3x-ui 面板订阅功能，也不需要用户登录或填写账号。**

项目原名 `xui-traffic-probe`；二进制现为 `flownote`。跳过 v0.2，不规划 v0.4。单 VPS 查询，不做管理后台、订阅服务、多机汇总或提醒系统。

> 上线前必须完成下方双账号实机验收。当前身份识别依赖 Xray 来源与访问日志一致，不适用于 Mux、CDN / 反向代理共用来源、多个账号共享同一底层连接的场景。HTTPS 保护传输，但不能修复错误的账号关联。

## 查询界面

- 剩余流量主卡、已用比例、账号状态、有效期与最近在线。
- 手机 / 桌面自适应、系统深色模式、低流量 / 到期 / 停用提示和友好错误页。
- 服务端渲染，无 JS、无远程字体、无第三方图片或统计脚本；刷新遵循短期缓存。
- 同时保留文本、JSON；不会返回 UUID、subId 或面板 token。
- [UI 设计说明](UI.md) · [架构与安全边界](DESIGN.md) · [更新记录](../CHANGELOG.md) · [本地测试记录](TESTING.md)

## 工作方式

```text
用户浏览器 --HTTPS（经过自己的代理）--> Xray
                  | 域名 TCP 443 精确路由
                  v
        freedom redirect + PROXY v2 头
                  v
      127.0.0.1:8686 FlowNote
      先读 PROXY → TLS 握手 → 核对 SNI / Host
                  |
      来源 ip:port + access.log → email
                  |
      面板只读 API → 当前账号流量 → HTML / JSON / 文本
```

TLS 在 FlowNote 自身终止，不加会破坏来源关联的普通 HTTP 反向代理。只监听回环地址；**不需要也不应开放 VPS 公网 8686 端口**。原型里的第三方公网“魔法 IP”和 `.local` 域名方案不再推荐。

## 前置条件

1. Linux VPS 上已经运行 3x-ui / Xray，FlowNote 和 Xray 在同一主机、同一网络命名空间。
2. 面板确实支持 API Token 和 `GET /panel/api/clients/traffic/{email}`；API 与订阅功能无关。若没有此接口，本版不做旧面板 Cookie 兼容，也不要因此开启订阅。
3. 一个你拥有的独立查询域名和有效的公开信任证书。下文 `traffic.example.com` 仅为占位符，不能直接用于生产。
4. 查询域名走指定节点，禁用此场景下的 Mux；Xray access log 开启，且该连接记录有唯一的 client email 标签。

## 部署

### 1. 域名与证书

推荐自有子域名 `traffic.example.com`，DNS-only 的 A / AAAA 指向自己的 VPS（不要套 CDN）。流量查询本身由 Xray 域名路由截获，服务器公网不需要运行这个查询网站。DNS 的作用包含客户端解析兼容，**仅设置 DNS 并不能保证查询走代理**。

用你已有的 ACME 客户端通过 **DNS-01** 申请该域名证书；服务不自动申请或续期证书。DNS-01 无需为查询功能开放 80 / 443，DNS API 凭据仅交给 ACME 客户端，限制权限。

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin flownote
sudo install -d -o root -g flownote -m 750 /etc/flownote /etc/flownote/tls
# 将 YOUR_* 换成 ACME 客户端实际生成的证书完整链与私钥路径
sudo install -o root -g flownote -m 640 YOUR_FULLCHAIN_PEM /etc/flownote/tls/fullchain.pem
sudo install -o root -g flownote -m 640 YOUR_PRIVATE_KEY_PEM /etc/flownote/tls/privkey.pem
```

证书必须包含查询域名，浏览器正常验证证书；不要让用户忽略证书警告。续期后通过 ACME deploy hook 原子安装新文件，再 `systemctl restart flownote`。本版启动时加载证书，不支持热重载。首次部署后与续期后均检查浏览器的证书有效期。

### 2. 面板 API Token

在支持此功能的面板安全设置中创建 token，优先使用可访问此接口的最小只读权限。**不要自动提升为 admin**：若只读 scope 不支持，先核对面板版本、接口、webBasePath 与权限；确需更高权限时由管理员评估泄露影响。

```bash
# 通过安全编辑器写入 token，避免将真实 token 粘进 shell 历史
sudo install -o root -g flownote -m 640 /dev/null /etc/flownote/token
sudoedit /etc/flownote/token
```

程序优先读取 `XUI_API_TOKEN`，其次 `panel.token_file`，最后 `panel.token`。建议 token 文件，不要提交密钥。面板在本机时用回环 HTTP；跨主机必须用证书正常验证的 HTTPS，不提供 `accept_invalid_certs` 开关。

### 3. 编译和配置

```bash
cargo build --release --locked
sudo install -m 755 target/release/flownote /usr/local/bin/flownote
sudo install -o root -g flownote -m 640 deploy/config.example.toml /etc/flownote/config.toml
sudoedit /etc/flownote/config.toml
sudo install -m 644 deploy/flownote.service /etc/systemd/system/flownote.service
```

修改 `server.domain`、证书路径、`xray.access_log`、`panel.base_url`（含 webBasePath）。没有默认生产域名或默认 token。`[debug] fake_email` 等旧配置会被拒绝，不会静默忽略。

服务用户需要有 access log 及所有父目录的读取 / 遍历权限。用 ACL 或专用只读组授权，并让日志轮转后保留权限；**不要用 root 跑服务，不要将日志或私钥 chmod 777**。本例 systemd 启用了 `ProtectHome`，请将证书放在 `/etc/flownote/tls` 而非 root 家目录。

### 4. Xray 入口

参见 [配置片段](../deploy/xray-snippet.json)。这是合并说明，不是完整配置，不可直接替换整个面板 Xray 配置。

1. 启用 `log.access`，路径与 FlowNote 一致。
2. 将 `traffic-query` 的 freedom 出站追加到 outbounds（**不要排到第一项成为默认出站**），redirect 到 `127.0.0.1:8686`，启用 `proxyProtocol: 2`。
3. 在其它规则之前插入：查询域名 TCP 443 → `traffic-query`；同域名 UDP 443 → blackhole，避免 QUIC 旁路。若使用片段的 `block` 标签，确认已有对应 blackhole 出站。
4. 某些新版 Xray 的 freedom 会默认阻止私网 / 回环目标。若重定向被阻止，仅在该查询出站的 `settings.finalRules` 放行 TCP `127.0.0.1:8686`（见片段说明），不要全局放开私网。
5. 保存并重启 Xray。

客户端也要加精确域名规则，优先于 GEOIP、DIRECT、广告拦截等规则。例如 Clash / Mihomo：

```yaml
rules:
  - DOMAIN,traffic.example.com,你的节点或策略组
  # ...原有规则
```

使用真实节点组名称；不能把多个不同账号随机负载均衡到同一查询入口。浏览器使用本地 DNS、Fake-IP、TUN 或把目标解析成 IP 时，可能丢失服务端域名匹配信息。应优先保留域名传给 Xray；必要时在**现有入站**合并 TLS sniffing（`destOverride: ["tls"]`，按版本配置 `routeOnly`），不要直接覆盖整段入站配置。ECH 隐藏 SNI 时不能依赖嗅探，仍须保留目标域名路由。按实机验收结果确认，不能承诺“域名自动解决所有分流问题”。

### 5. 联调与启动

先验证面板 API（执行后退出，不开启监听）：

```bash
sudo -u flownote /usr/local/bin/flownote /etc/flownote/config.toml --check-panel '真实的-client-email'
# 输出含当前账号数据；只在管理员终端执行，不发送给普通用户
sudo systemctl daemon-reload
sudo systemctl enable --now flownote
journalctl -u flownote -f
```

让真实客户端连上节点，打开 `https://traffic.example.com/`。直接向 8686 发送普通 curl 请求会被拒绝，这是预期行为：该端口要求 PROXY 头然后 TLS，不是普通 HTTPS 监听。

### 6. 双账号上线验收（必须）

- 两个账号来自不同网络和同一 NAT 网络时分别测试；同时查询，各自只看到自己的数据。
- 管理员本机对照 Xray 真实 access log 与 PROXY 来源，确认来源一致且账号唯一；不把日志发到公共渠道。
- 禁用 Mux / CDN 后，测试断开重连、切换账号、客户端复用连接与端口复用；任何串号即停止上线。
- 轮转 / 截断 access log，确认新查询可恢复；服务启动前已有日志不会回放。
- 证书可信且匹配域名，过期 / 不匹配证书不能被用户绕过；续期后服务加载新证书。
- 公网无法连 8686；不能通过普通反代或防火墙 DNAT 暴露它；不要允许代理用户绕过查询路由直接访问回环服务。

## 使用与排错

浏览器：`https://traffic.example.com/`；文本：`curl https://traffic.example.com/`；JSON：`curl https://traffic.example.com/json`。这些 curl 同样须经过相应代理，例如 `curl --proxy socks5h://127.0.0.1:1080 https://traffic.example.com/json`（调整本机端口）。

允许 `?format=html|text|json`，拒绝其它查询参数；没有按 email / UUID / subId 查人的接口。HEAD 不返回响应体。账号用尽、过期或停用后，代理本身可能无法接入，因此**不能保证这些用户还能打开查询页**；相应状态 UI 是对仍可查询场景的正确展示，不是绕过 Xray 认证的方案。

| 现象 | 检查 |
|---|---|
| 超时 / 连接断开 | 客户端是否走节点，域名是否保留，规则顺序，UDP/QUIC，Xray 是否阻止回环重定向 |
| 证书错误 | 域名 / 证书完整链 / 有效期，续期后是否重启服务；不要忽略错误 |
| 403 | 缺少日志、轮转权限丢失、无 email、来源冲突或不支持的共享连接场景 |
| 421 | Host 不匹配，或有人把入口当正向代理使用 |
| 502 | 面板接口 / token 权限 / webBasePath / HTTPS 证书 / 面板账号返回不一致 |
| 页面旧数据 | 面板上报延迟 + 默认 5 秒服务端缓存；不是实时计量 |

默认日志只记启动与故障，不记录账号和来源配对；`RUST_LOG=debug` 会增加诊断信息，排错后恢复。Xray access log 仍属于敏感日志，需单独做好权限和保留期限。

## 开发与验证

```bash
cargo fmt --check
cargo test --locked
cargo build --locked
python3 tests/e2e.py target/debug/flownote # Linux + OpenSSL，临时自签证书仅供本机测试
cargo run --locked -- --preview output/preview
```

预览命令输出 9 种纯合成状态页面，可直接打开 `output/preview/index.html`；与生产共用渲染器，不启动服务或连接面板。实际测试范围和未验证项见 [设计文档](DESIGN.md)。

## v0.1 迁移

旧压缩包保留作为历史原型；不要继续用其 HTTP 魔法 IP 配置。安装新二进制和 `flownote.service`，使用新配置模板和独立配置目录；完成域名 / 证书 / Xray 路由及双账号验收后，再停用旧的 `xui-traffic-probe.service`。同一时刻只能有一个服务占用 8686；切换前安排短暂停机。新路径为 `/etc/flownote`，新环境变量为 `FLOWNOTE_CONFIG`，原有 token 可由管理员重新安装到新位置。
