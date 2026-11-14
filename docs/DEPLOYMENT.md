# FlowNote v0.3.4 部署指南

默认方案为 **`http://6.6.6.6/`**。从安装、面板 Token、访问日志权限到 Xray / 客户端分流的完整操作步骤均放在 [README 快速开始](../README.md#快速开始)，按顺序完成即可。无需域名、DNS、证书或面板订阅。6.6.6.6 是真实公网 IP，仅作为本地路由约定，必须在代理链路内截获。

## 本机交互式配置（推荐）

按官方脚本安装 3x-ui 后，运行 README 中带 `--setup` 的安装命令；已经升级到 v0.3.4 的用户执行 `sudo flownote-setup`。选择 `2`，确认检测出的面板地址、日志路径，输入不回显的 API Token 和真实 client email。向导需要 Python 3，仅使用标准库。成功后只需继续 README 的客户端规则和真实双账号验收。

默认检测 `/usr/local/x-ui`、`/etc/x-ui/x-ui.db` 和 `bin/xray-linux-*`，面板端口 / webBasePath 从设置读取；HTTPS 面板不降级或跳过验证。`--detect` 只读，`--xui-dir` / `--db` / `--core` 支持显式路径。自动应用要求运行中的本机 systemd `x-ui`、SQLite 及相同网络命名空间；非标准部署使用手动配置。

若没有持久化 `xrayTemplateConfig`，在面板 Xray 设置页保存一次现有配置再运行。确认前会生成 root 私有预览并运行内核 `run -test`；确认后在面板接口验证成功的前提下短暂停止 x-ui，备份数据库，事务更新单个模板设置，恢复 x-ui 并启动 FlowNote。流量统计不被整库替换。备份在 `/var/backups/flownote/`，包含敏感信息。失败时尝试恢复模板与原配置；日志 / ACL / 轮转文件可能保留。

向导会用生成的 HTTP / 历史采样配置替换已有 FlowNote 自定义配置（先备份），并关闭 Xray 日志地址掩码以保留来源 IP:端口。默认日志 `/var/log/flownote-xray/access.log` 使用专用组权限，生成每日七次保留的 logrotate 配置；需要系统安装 `logrotate`。使用已有日志时，文件需存在；无法读取时需要 `acl` 工具，轮转后的读取权限由管理员保留。日志勿放 `/root` 或 `/home`。

## 安装目录

| 路径 | 用途 |
| --- | --- |
| `/usr/local/bin/flownote-setup` | 交互式菜单入口 |
| `/usr/local/share/flownote/setup.py` | Python 3 标准库向导 |
| `/var/backups/flownote/` | 向导备份，仅 root 可读 |
| `/usr/local/bin/flownote` | 当前二进制 |
| `/usr/local/bin/flownote.previous` | 升级前二进制（已有安装时） |
| `/etc/flownote/config.toml` | 实际配置，升级保留 |
| `/etc/flownote/config.example.toml` | 当前 HTTP 模板 |
| `/etc/flownote/token` | 管理员填写的 API Token |
| `/usr/local/share/flownote/` | HTTP / HTTPS 路由片段、HTTPS 模板、安装说明和许可证 |
| `/etc/systemd/system/flownote.service` | systemd 单元 |
| `/var/lib/flownote/history/` | 可选账号查询采样，0700 / 0600 权限 |

首次安装创建 `flownote` 服务用户，不启动占位配置。单独安装不修改 Xray；`--setup` 打开向导，确认后才修改模板。客户端规则需自行配置。脚本校验固定版本 HTTPS 发布资产、SHA-256、精确包内路径、文件类型及二进制版本；归档清单与安装包同源，不是独立签名。

## 安装包与安装脚本

```bash
curl --proto '=https' --tlsv1.2 -fsSL -o install.sh https://github.com/youbilin/FlowNote/releases/download/v0.3.4/install.sh
less install.sh
sudo bash install.sh --version v0.3.4
# 只下载并校验，不修改系统：
bash install.sh --version v0.3.4 --download-only ./flownote-download
```

发布包支持 Linux amd64 / arm64，使用静态 musl。标准安装需要 systemd、Bash、curl、tar、sha256sum 和常见账户管理工具。也可从同版 Release 下载归档与 SHA256SUMS，在下载目录执行 `sha256sum --ignore-missing --check SHA256SUMS`，确认对应包显示 OK 后解压。

## 升级与回退

升级执行指定版本安装命令。已有配置、Token、证书和历史文件保留；活动服务短暂重启。安装器等待新服务保持活动，若快速失败则尝试恢复旧二进制。这不能代替浏览器真实查询验收。

已有 v0.3.1 HTTPS 配置无需改动就可升级；未写 `server.protocol` 时仍按 HTTPS 处理。要切换 HTTP，按 README 同时迁移配置与两端路由。新 HTTP 配置不能直接给旧版程序使用。

手动回退二进制前，先恢复与旧版相容的配置。若回退到 v0.3.1，HTTP 用户须恢复 HTTPS 域名、证书与 Xray / 客户端规则：

```bash
sudo systemctl stop flownote
sudo install -m 755 /usr/local/bin/flownote.previous /usr/local/bin/flownote.rollback
sudo mv /usr/local/bin/flownote.rollback /usr/local/bin/flownote
# 在此恢复备份的配置与两端路由，再启动：
sudo systemctl start flownote
```

## 可选 HTTPS 部署

需要浏览器独立验证服务身份时，使用自有域名和公开信任证书。模板：[config.https.example.toml](../deploy/config.https.example.toml)、[xray-https-snippet.json](../deploy/xray-https-snippet.json)。模板不写 protocol，兼容旧版默认 HTTPS；也可显式写 `protocol = "https"`。

1. 将 `server.domain` 改为小写 ASCII 查询域名，例如 `traffic.example.com`。
2. 通过 ACME 客户端申请证书，建议 DNS-01。无需查询域名 A / AAAA 指向服务器，但申请与续期仍需验证域名控制权。
3. 复制完整证书链与私钥到 `/etc/flownote/tls/`，不要放宽 ACME 客户端整个目录权限：

```bash
sudo install -d -o root -g flownote -m 750 /etc/flownote/tls
sudo install -o root -g flownote -m 640 /实际证书路径/fullchain.pem /etc/flownote/tls/fullchain.pem
sudo install -o root -g flownote -m 640 /实际证书路径/privkey.pem /etc/flownote/tls/privkey.pem
```

4. 配置证书路径，并保留 README 中的面板 Token、日志权限和历史配置。TLS 在 FlowNote 原生终止，不放普通 HTTP 反向代理在前面。
5. 合并 HTTPS 路由模板：查询域名 TCP 443 → traffic-query，UDP 443 → block，freedom redirect 仍为本机 8686，PROXY 版本仍为 2。模板中的说明字段不是完整 Xray 配置。
6. 客户端以 `DOMAIN,traffic.example.com,你的节点或策略组` 优先送入对应节点。若服务端依赖域名匹配，客户端应保留目标域名；本地提前解析成 IP、Fake-IP 映射丢失或不适当的 sniffing 均需实测，不能只添加域名规则便假设成功。
7. 用 `https://traffic.example.com/` 验证证书、SNI 和 Host。续期后同步证书文件并执行 `systemctl restart flownote`，证书不会热重载。不要跳过浏览器证书验证。

## 6. 双账号上线验收（必须）

HTTP / HTTPS 均需要真实 Xray 验收：不同账号 A / B 分别查询并对照面板，同一 NAT 并发、断线重连、切换账号、日志轮转，确认没有串号。检查日志来源语义、唯一 email、traffic-query 标签、读取权限、Mux 关闭和 PROXY v2 字节顺序。请求不能任意指定 email。

用外部主机确认 8686 不可访问，确认服务只监听回环；在 FlowNote 不运行时查询应失败，不能显示真实 6.6.6.6 的内容。HTTP 浏览器全程经过正确节点且不升级 HTTPS；HTTPS 则另测续期和证书链。已知来源冲突应拒绝查询，但延迟到达的冲突日志仍可能留下窗口，详见[设计边界](DESIGN.md)。

## 历史曲线与数据保留

面板接口提供累计计数，没有过去每天账单。FlowNote 只在用户查询时采样；缓存保留真实面板获取时间，默认每小时新增一个点，重置时断线，不回填。默认保留 30 天，允许 1–90 天、采样间隔 300–86400 秒。单账号最多 4096 点，单文件读取上限 512 KiB，最多 1024 个账号文件。

设置 `history.enabled = false` 可停止采样；已存文件不会自动消失。保留清理由有效查询触发，服务空闲或停止时文件可能继续留存。需要清空时，先 `systemctl stop flownote`，确认 `/var/lib/flownote/history` 是实际配置的采样目录，再删除其中的采样文件，最后重启。备份也属于用户数据。存储失败不影响当前流量查询。

## 故障排查

完整现象对照表在 [README](../README.md#常见问题)。先使用 `--check-panel` 区分上游 API 问题和来源关联问题，再检查服务 / Xray 日志和客户端生效规则。不要公开上传真实 Token、UUID、订阅地址或未脱敏的访问日志。

## 卸载与数据清理

v0.3.4 菜单 `5` 提供保留数据卸载和完全清理，分别要求输入 `UNINSTALL` / `DELETE`。完整路径和注意事项见 [README 卸载与清理](../README.md#卸载与清理)。卸载前移除客户端分流规则，卸载后在面板撤销不用的 Token。

先合并删除可核对的专用查询出站 / 路由，再测试候选配置、备份并事务更新单个模板设置；短暂重启 x-ui 验证恢复后才删除 FlowNote 程序 / 单元。失败或中断尝试恢复原模板并恢复原活动 FlowNote 服务。保留数据模式保留配置、证书、历史、账号、日志与备份。完全清理永久删除默认配置 / 历史 / 备份目录；专用日志仅在 Xray 不再使用时删除，否则保留日志、轮转与账号。自定义目录、共享日志 ACL、系统 journal 不清理。符号链接、挂载点或与 3x-ui 数据重叠的清理目录会被拒绝。
