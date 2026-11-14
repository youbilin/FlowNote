# FlowNote v0.3.5

修复默认安装 3x-ui 后，首次配置 FlowNote 时 Xray 检查失败且无法查看具体原因的问题。

- 初次预检使用私有临时访问日志，避免正式日志目录还未创建就失败；确认后准备日志并检查真实候选，通过后才重启面板。
- 不再把任何检查失败都视为 finalRules 版本问题；仅在内核明确报告不支持此字段时提供兼容重试。
- 检查失败会显示分类原因和 root 私有诊断文件位置，保留原始 stdout / stderr，便于定位实际环境问题。
- 日志路径不确定可直接回车；客户端 email 是 3x-ui 已有客户端标识（例如 alice），不要求真实邮箱，不会发送邮件。

升级并运行交互菜单：

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/youbilin/FlowNote/releases/download/v0.3.5/install.sh | sudo bash -s -- --version v0.3.5 --setup
```

选择 2 配置 HTTP 入口。已有配置和 Token 在升级时保留，应用变更前仍需确认；原节点、订阅开关和面板登录设置保留。卸载与清理菜单继续可用。

提供 Linux amd64 / arm64 静态包、install.sh 与 SHA256SUMS。安装包发布前由工作流运行 Rust、向导、安装器和 HTTP / HTTPS 集成检查。本地另外用官方 Xray v26.11.9 复现并验证日志检查修复；这不替代用户服务器的实际双账号验收。
