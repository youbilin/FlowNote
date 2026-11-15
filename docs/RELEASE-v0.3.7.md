# FlowNote v0.3.7

简化本机 3x-ui 配置，修复向导每次都停止面板的问题。

- 自动识别面板端口 / 访问路径，HTTPS 优先读取面板域名或证书的唯一明确域名；再次配置复用 Token。
- 查询路由已正确时不重启 3x-ui / Xray；FlowNote 配置和 Token 一致时也保持运行。首次添加或修复 Xray 配置才执行一次重启，确认前会提示节点可能断开。
- 保留已有显示、历史与性能设置。面板接口先用私有暂存配置检查，失败不替换活动配置或重启服务。
- 应用失败显示阶段与仅 root 可读的 apply.failure.json / apply.stderr.log；模板回退失败或诊断写入失败也继续尝试恢复 x-ui。

升级并打开菜单：

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/youbilin/FlowNote/releases/download/v0.3.7/install.sh | sudo bash -s -- --version v0.3.7 --setup
```

选择 2 自动配置。已有可用部署仅升级可去掉 --setup。安装器会重启活动的 FlowNote，不重启 x-ui；向导按上述规则判断是否重载。若旧版失败后面板已停止，先执行 sudo systemctl start x-ui 再运行新版。

提供 Linux amd64 / arm64 静态包、install.sh 和 SHA256SUMS。systemd 和面板事务 / 恢复流程以隔离回归验证；实际服务器仍需完成双账号查询验收。
