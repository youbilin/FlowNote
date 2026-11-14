# FlowNote v0.3.3 · 交互式配置菜单

已有标准 3x-ui 安装，无需手填默认路径：安装后运行 `sudo flownote-setup`，或在安装命令后加入 `--setup`。

- 自动检测本机面板目录、SQLite 数据库、Xray 内核、真实端口与访问路径。
- 不回显输入 API Token，使用真实 client email 核对流量查询权限；无需启用面板订阅。
- 先检查候选配置，再经终端确认后备份、合并查询出站 / 路由、设置日志权限并启动服务。重启 x-ui 可能短暂中断连接。
- 失败或 Ctrl-C 尝试恢复单个模板与 FlowNote 设置，不整库回滚流量统计。日志 / ACL / 轮转修改可能保留。已有自定义 FlowNote 配置会先备份再替换为生成配置。
- 自动配置适用于本机 systemd + SQLite；Python 3 标准库即可。模板未持久化时，先在面板 Xray 设置保存一次。客户端分流仍需单独添加。

默认入口仍为 `http://6.6.6.6/`。简约流量界面、日期曲线与原 HTTPS 功能保持兼容。备份保存在 root-only `/var/backups/flownote/`，请勿公开。专用日志轮转需要系统 logrotate。

验证包含 34 项 Rust 单元、37 项 HTTP、39 项 HTTPS、26 组向导与 9 组安装脚本检查。集成检查使用合成环境，不代表用户真实 Xray 已完成双账号验收。

资产包含 Linux amd64 / arm64 静态 musl 包、install.sh 和 SHA256SUMS。完整安装、菜单与客户端配置见仓库 README。
