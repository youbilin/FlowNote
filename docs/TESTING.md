# v0.3.1 验证记录

日期：2026-11-14。构建环境：本机 Debian/WSL，Rust 1.94.1；Windows 原生默认 MSVC 缺少 link.exe，因此没有将 Windows 原生编译冒充成功。部署目标为 Linux。

## 已执行
- `cargo fmt --check`：通过。
- `cargo clippy --locked -- -D warnings`：通过。
- `cargo test --locked`：33 个单元测试通过，0 失败。
- `cargo build --locked`：Linux 调试构建通过。
- `python3 tests/e2e.py target/debug/flownote`：35 项真实 TLS / PROXY 集成断言通过，模拟面板与日志。
- Playwright CLI：桌面 1440px、手机 390px、最小宽度 320px；390 / 320 的 scrollWidth 等于 viewport width，无横向溢出。检查浅色、深色、曲线坐标、低流量、不限配额和错误页。截图保存在本地 `output/playwright/`（不含真实数据）。

- `python3 tests/installer.py`：8 组离线安装脚本检查，覆盖正常包、摘要不符、重复摘要、路径穿越、符号链接、版本错误、已有输出保护、架构与参数拒绝。
- `shellcheck scripts/install.sh scripts/package.sh`：通过。

## 集成测试覆盖
PROXY v1/v2、TLS 证书验证、错误/缺失 SNI、Host 与 absolute-form 校验、延迟日志、缺失来源与错误出站、账号参数拒绝、不信任转发头、HTML/文本/JSON、HEAD 空正文、方法/路径拒绝、缓存并发合并、日志截断与轮转、已知来源冲突、上游账号错配/缺失/负计数/非法 JSON/超大响应、安全响应头、无 UUID/subId 输出、非 PROXY 连接拒绝和无私密内容 favicon。另检查真实累计值采样、缓存不重复记点、按账号隔离、磁盘持久化与历史损坏后仍返回当前流量。单元测试覆盖保留裁剪、乱序快照、计数重置断线与旧配置兼容。

## 不代表已验证
未连接用户的真实 3x-ui/Xray；未签发公有证书、未配置真实 DNS、未修改 VPS 或部署服务；未做性能/渗透压测；无 Mux/CDN 兼容性保证。仍须执行 DEPLOYMENT.md 的实机双账号上线验收，尤其同 NAT、端口/连接复用与日志延迟。

预览 HTTP 服务仅在本机回环临时运行、只提供合成页面，已在检查后停止；不是生产明文入口。

仓库展示用的合成截图另存于 `docs/assets/`。GitHub Actions 的通过状态以仓库实际运行结果为准，不由本地测试记录代替。

## 发布验证

Release 工作流在原生 Linux amd64 / arm64 runner 构建静态 musl 包，分别运行测试与预览，检查 `--version` 后打包。最终发布任务只有在两个架构均成功后才生成 SHA256SUMS 并公开 Release。结果以 GitHub Actions 实际记录为准。

本地测试不会以 root 身份安装到真实系统。安装脚本测试通过临时模拟下载验证安装前检查；首次安装与升级时的 systemd 行为仍需管理员按部署指南在目标服务器验收。

2026-11-14 发布实测：[v0.3.1 Release 工作流](https://github.com/youbilin/FlowNote/actions/runs/43570680870) 的 amd64、arm64 和发布任务全部通过。公开发布后重新下载两个归档与 install.sh，SHA256SUMS 三项均通过；readelf 确认 X86-64 / AArch64 且均无动态解释器。下载后的 amd64 二进制 `--version` 为 0.3.1，再次通过 35 项 TLS/PROXY 集成检查。发布版安装脚本从 GitHub 实际下载、校验并保存 amd64 离线包成功；未在用户真实服务器执行 root 安装。
