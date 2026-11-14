# FlowNote v0.3.6

减少查询工具的后台开销，简化标准 3x-ui 安装配置。

- 单线程异步调度，日志空闲检查从 100 ms 降为 1 s，查询立即唤醒；读取缓冲复用为 16 KiB。
- 新配置默认关闭历史曲线；关闭时没有历史采样文件读写。当前上传、下载、配额和到期时间继续显示，曲线可手动开启。
- 标准向导只需 API Token 和确认：自动选面板地址、实际日志、验证账号，--advanced 提供覆盖。
- 确认后按需安装 logrotate / acl。面板重启后检查实际查询路由和日志路径，再验证读取权限，避免服务启动但账号无法识别。

已经能够查询的服务器，只升级程序即可，无需重新运行配置向导：

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/youbilin/FlowNote/releases/download/v0.3.6/install.sh | sudo bash -s -- --version v0.3.6
```

升级保留原配置和 Token，活动 FlowNote 服务短暂重启，x-ui 不会被安装器重启。旧配置已开启历史的，需在 /etc/flownote/config.toml 的 [history] 中设置 enabled = false 并重启 flownote 才会关闭；历史文件不会自动删除。新安装在上述命令末尾加 --setup。

提供 Linux amd64 / arm64 静态包、install.sh 和 SHA256SUMS。MemoryMax=192M 是上限，不是实际预占内存；测量方法与发布验证见 docs/TESTING.md。目标服务器的双账号关联仍需按 README 验收。
