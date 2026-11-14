FlowNote v0.3.1 提供更简约的流量查询页、日期采样曲线和 Linux 预编译安装包。

- 页面集中展示剩余、已用、上传、下载、总配额、到期时间与状态，支持手机和深色模式。
- 可选按查询时间记录累计上传 / 下载曲线；不回填历史、不冒充精确每日账单。新模板默认 30 天 / 小时采样，旧配置保持关闭。
- Linux amd64 / arm64 静态 musl 包，无需目标机器安装 Rust。
- 安装脚本自动选架构，验证 SHA-256、包路径和二进制版本，保留现有配置、Token、证书与旧二进制。

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/youbilin/FlowNote/releases/download/v0.3.1/install.sh | sudo bash -s -- --version v0.3.1
```

首次安装后，请配置 `/etc/flownote/config.toml`、域名证书、面板 Token 与 Xray 路由，再启动服务。安装和双账号验收见 [部署指南](https://github.com/youbilin/FlowNote/blob/main/docs/DEPLOYMENT.md)。

预编译包经过各自原生架构构建与测试；真实 3x-ui / Xray 拓扑仍须实机验收。SHA256SUMS 用于文件完整性校验，不是独立签名。

0.3.0 用户可直接升级二进制和服务单元；需要曲线时手动添加文档中的 `[history]` 配置。回退 0.3.0 前移除该新增段。
