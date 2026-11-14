# 流量笺 · FlowNote v0.3.2 设计

## 1. 范围与名称

FlowNote，中文「流量笺」：用一张轻量的手记，把流量余量和有效期讲清楚。名称是本项目的工作品牌，不代表已完成商标或域名可用性核验。

面向拼节点普通用户，不面向面板管理员；已有节点、没有订阅功能，也能查询自己的用量。API Token 能力与面板订阅开关互不依赖。当前交付直接为 v0.3；v0.2 跳过、v0.4 不考虑，不实现 Cookie 登录兼容、Prometheus、跨 VPS 汇总、分组或主动提醒。

## 2. 数据链路与身份边界

默认链路为浏览器 `http://6.6.6.6/` → 指定账号节点 → Xray 精确 IP / TCP 80 路由 → 专用 freedom 出站 → PROXY v1/v2 + 原始 HTTP → 回环 FlowNote。服务先读 PROXY 头，再读取 HTTP，核对 Host，最后将来源 `ip:port` 与查询出站的 access log 关联，得到 client email。6.6.6.6 是真实公网 IP，仅作为约定入口，由两端规则在链路内截获，不能回退到真实地址。

可选 HTTPS 使用自有查询域名 TCP 443；PROXY 头之后才 TLS 握手，SNI 和 Host 同时校验。两种模式共享身份索引、面板 API、渲染与历史存储。
源码核查参考：[Xray freedom 实现](https://github.com/XTLS/Xray-core/blob/main/proxy/freedom/freedom.go) 的 `HeaderProxyFromAddrs(version, inbound.Source.RawNetAddr(), conn.RemoteAddr())`；[官方 freedom 文档](https://xtls.github.io/config/outbounds/freedom.html) 说明 redirect / proxyProtocol 和新版 finalRules。此核查不是对用户实际安装版本的运行验证。

- 不信任 URL 里的账号、X-Forwarded-For、Cookie 或请求正文来识别用户。
- 无法识别 → 403，不退回按 IP 猜测、不展示全体账号、不启用默认账号。
- 一个索引键在 TTL 内出现两个不同 email → 标记冲突，后续解析拒绝该键，直到过期。
- 面板返回 email 必须与查询值完全相等，错误或不一致 → 502。
- 每个 HTTP 连接只接收一个请求，关闭 keep-alive，减少页面在切换节点后的旧连接复用。

**不能把 ip:port 关联当作经过形式验证的身份认证。** 日志延迟、端口复用、Mux、CDN 或其它共享底层连接可能造成关联不唯一；如果冲突日志尚未到达，简单索引不能证明不存在冲突。当前冲突标记只解决已观察到的冲突，不能补救已经返回的响应。生产仅接受经双账号实机验收的直连、非复用拓扑，不支持 Mux/CDN；更复杂拓扑须有独立可信的逐连接身份通道，本版不做备用猜测。TLS 不会消除该限制。

## 3. 协议与信任模型

- `server.protocol` 只接受 `http` / `https`；缺省为 HTTPS，保留旧配置语义。新安装模板显式选 HTTP，Host 为 `6.6.6.6`。
- HTTP 允许规范 IPv4 字面量或小写 ASCII 域名，禁止 `[tls]`；HTTPS 要求域名及证书配置，拒绝 IP。两种模式均拒绝 `.local`、协议 / 路径 / 端口混入 Host 配置。
- 模式来自服务配置，不通过嗅探或 X-Forwarded-Proto 自动决定。HTTP 允许 Host 的可选端口 80，HTTPS 允许 443；错误端口 / Host / absolute-form 均拒绝。
- FlowNote 通过 Rustls 直接终止 TLS，启用库的安全默认 TLS 1.2 / 1.3，ALPN 仅 HTTP/1.1；HTTP 模式直接服务 HTTP/1.1，均无 HTTP/3。
- TLS 证书和私钥在启动时校验并加载；续期由外部 ACME DNS-01 完成，续期后重启。未申请证书、不自动修改 DNS、未部署真实域名。
- HTTPS 的 SNI / Host 必须匹配配置域名；TLS 不匹配不返回敏感页面。HTTP 无 SNI / 证书检查，不把回环监听描述为 TLS 保护。
- 仅对 HTTPS 响应（包含错误页）设置 HSTS 一年，HTTP 不发送 HSTS，也不重定向到 HTTPS；不使用 includeSubDomains / preload。所有响应 no-store/private、nosniff、no-referrer、DENY iframe、same-origin resource policy、禁用敏感权限。
- CSP 禁止所有外部资源和脚本，允许内嵌样式（含进度条样式）；不是严格禁止所有 inline CSS 的策略。
- 监听必须为回环，实际 peer 也检查回环。PROXY 头本身没有认证，**本机进程、同命名空间恶意租户和 root 属于可信边界之外**。回环不等于认证；不得 DNAT / 反代暴露，不应在不可信共享主机上部署。
- 面板仅允许回环 HTTP 或正常证书验证的 HTTPS，禁用重定向和环境代理，不提供跳过证书验证。只读 scope 兼容性需真实面板验证，不能擅自扩权。
- 日志中不保存查询结果，不直接记录账号/来源配对，不转发上游响应正文或业务错误文案；Xray 原始日志另行管理。

HTTP 本身无法验证服务身份或防篡改；已认证加密的代理隧道可保护隧道内的内容，但错误直连、到局域网代理的明文段或被控制的节点仍有风险。本机回环无需对公网开放低端口，但它不构成浏览器与 FlowNote 之间的独立 HTTPS。服务端在 TCP 80 查询规则之后拦截该 IP 的其他端口 / UDP；客户端仍必须确保该 IP 不走 DIRECT。

## 4. 模块与资源预算

| 模块 | 职责 / 限制 |
|---|---|
| config | 严格未知字段拒绝，域名、回环、超时、并发与面板 URL 验证 |
| proxy_proto | PROXY v1/v2，精确读取，不吞后续 HTTP / TLS 字节；支持 IPv4/IPv6 |
| tls | PEM 证书完整链与私钥加载，安全默认协议，HTTP/1.1 ALPN |
| logtail | 只读查询出站日志，首次从末尾开始，处理 inode 轮转/截断/半行；最大 16384 索引键，TTL 默认 600 秒 |
| panel | 按 email 缓存，默认 5 秒；异步互斥串行回源，避免同一账号并发击穿（代价：不同账号也排队）；最多 2048 项，64 KiB 响应体 |
| history | 可选查询采样；账号哈希文件名；默认 30 天 / 1 小时、最多 1024 个账号、每账号 4096 点 / 512 KiB 读取；权限 0700 / 0600、原子替换，写入失败不阻断当前查询 |
| render + ui | 转义动态文本，饱和加法避免流量溢出，无限/未激活语义，正常和错误页共用模板 |
| main | 默认 128 并发连接；PROXY 3 秒、HTTPS 握手 5 秒、HTTP 头 10 秒、整体 30 秒；HTTP 读缓冲 16 KiB |

整体超时包含身份等待、面板排队和读取；达到并发上限会断开新连接，不提供可保证的过载页面。默认 systemd MemoryMax=192M 仅为预算，不是性能压测结论。缓存不是真正全局 QPS 限流；大量有效不同账号仍可产生回源，未来若需求变化再评估，不纳入本版 v0.4 规划。

面板计数单位为字节，total=0 不限，expiryTime=0 不限，负值代表首次使用后时长。时间按配置时区展示；最后查询时间是渲染时间，不是面板采集时间。账号被停用/超限后如果 Xray 拒绝代理连接，页面不可达，不承诺解除这一限制。

## 5. 接口与界面

只支持 GET / HEAD；路径 `/`、`/json`；可选唯一 format 参数 `html|text|json`。浏览器 Accept 返回 HTML，curl 默认文本，`/json` 固定 JSON。拒绝任意账号参数和其它路径。错误按相同协商格式返回；HEAD 空正文；响应不含 UUID、subId、token。

JSON 是最小只读投影：email 标签、enable/status、up/down/used/total/remaining/percent_used、expiry_time_ms、last_online_ms、generated_at_ms，以及 history / history_kind。history 的每条记录仅含 at_ms、up、down，口径固定为 query_samples_cumulative_bytes。email 可能本身是个人邮箱，因此建议管理员使用无个人信息的 client 标签；本版没有“账号脱敏即绝对匿名”的承诺。

[UI.md](UI.md) 规定视觉、信息层级、移动端和状态矩阵。无 JS、无浏览器持久化存储、无外部图片资源，减少攻击面并避免共享节点流量加载第三方资源。低流量仅改变页面状态色，不做自动提醒；成功页面只展示数字、状态和采样曲线。

## 6. 验证与发布门槛

本机可复现测试：Rust 单元测试、真实 HTTP+PROXY 及临时自签测试证书的 TLS+PROXY 集成脚本、Playwright 合成页面视觉检查。集成脚本模拟面板和 Xray 日志 / PROXY 发送端，**不是真实 3x-ui/Xray 联调**。测试证书只在脚本客户端的独立信任库中受信任，不修改系统 CA；生产 HTTPS 仍需公有证书。

上线必须另外完成 部署指南的真实双账号、同 NAT、重连、日志轮转、外网端口验收；HTTPS 另测证书续期。重点确认：安装版本的 freedom 来源语义、访问日志格式、scope 权限、私网 finalRules 行为、TLS sniffing / Fake-IP / ECH 的分流兼容性。没有这些验收结果，不宣称可以直接安全上线。

## 7. 迁移与交付

旧 v0.1 压缩包不覆盖；保留用于回溯。0.3.2 发布包包含对应架构的静态 musl 二进制、部署示例、安装说明与许可证，不含 Token、私钥、真实日志或历史记录。源码仓库另含 Cargo.lock。仓库 README 提供项目概览及完整 HTTP 部署步骤，DEPLOYMENT.md 补充升级、回退和 HTTPS 配置；发布记录见 CHANGELOG。

## 8. 查询采样与发布

面板成功返回时记录观察时间，缓存保留该时间。每次有效查询由阻塞工作线程按账号读取自己的采样文件；小时采样默认值、时间窗口裁剪与点数上限控制增长。检测到计数下降时追加重置点；渲染器断开折线。并发响应到达存储层可能乱序，旧快照不得覆盖更新记录。缓存命中不制造额外点。

历史文件只含 timestamp / up / down，不含 Token 或原始账号字段；账号标签的 SHA-256 仅用于命名，不视为加密或不可关联性。持久化采用独占临时文件、0600、fsync 后原子 rename；读取校验文件类型、大小、序列顺序与非负计数。默认路径受 systemd StateDirectory 管理。过期清理按查询触发，没有后台定时任务，保留时间与删除办法见部署指南。

GitHub Actions 使用原生 amd64 / arm64 Linux runner 分别编译 musl 包，完成单元、HTTP/PROXY、TLS/PROXY、安装脚本与二进制版本检查后，汇总两个包及 SHA256SUMS，全部齐备才发布。Actions 使用固定提交引用；发布权限只授予最终发布任务。脚本固定版本并验证 HTTPS 下载、清单唯一条目、包内路径、文件类型和版本；SHA-256 清单不代替独立签名。首次安装等待管理员配置，升级保留配置和旧二进制。
