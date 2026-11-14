# v0.3.3 验证记录

日期：2026-11-14。Debian / WSL，Rust 1.94.1，Python 3.13。本地及公开发布验证如下。

- Rust fmt / clippy --all-targets、34 个单元测试及调试构建通过。
- 37 项 HTTP / PROXY、39 项 HTTPS / PROXY 集成检查通过，使用合成面板与日志。
- `python3 tests/setup.py`：26 组通过，覆盖 SQLite 白名单、实际面板地址、运行环境 / 数据库 / 命名空间核对、模板保留与冲突拒绝、Xray 候选检查、私有文件、单设置事务、备份 / 并发保护、面板失败、启动失败和 Ctrl-C 回退。
- `python3 tests/installer.py`：9 组通过，含 `--setup` 与离线模式冲突、无交互终端拒绝、向导文件的包内清单检查。
- 向导测试只使用临时文件与模拟主机命令，不修改当前主机服务；未在用户真实 VPS 执行自动安装 / 配置，仍需双账号验收。

## v0.3.3 公开发布验证

2026-11-14：[CI](https://github.com/youbilin/FlowNote/actions/runs/43601806730) 全部通过；[Release 工作流](https://github.com/youbilin/FlowNote/actions/runs/43601943499) 的原生 amd64、arm64 与发布任务全部通过，v0.3.3 已公开发布。

- 从公开 Release 重新下载两个归档、install.sh 和 SHA256SUMS，三个资产摘要全部匹配；readelf 确认 X86-64 / AArch64 且均无动态解释器。
- 两个包均包含 setup.py / setup.sh；实际下载的 amd64 二进制版本为 0.3.3，再次通过 37 项 HTTP 与 39 项 HTTPS / PROXY 集成检查。
- 实际发布的 setup.py 帮助与 PTY 菜单通过，进入客户端规则页并正常退出；没有执行主机配置。
- 实际发布的 install.sh 以 `--version v0.3.3 --download-only` 从 GitHub 远程下载、校验并保存包成功。
- 未在用户真实 VPS 执行 root 安装或修改 3x-ui；向导的应用 / 回退检查使用模拟主机命令与临时 SQLite，真实双账号验收仍由目标环境完成。

---

# v0.3.2 验证记录

日期：2026-11-14。Debian / WSL，Rust 1.94.1。

- cargo fmt / clippy --all-targets：通过。
- cargo test --locked：34 个单元测试通过，含 HTTP / 旧 HTTPS 兼容与错误混合配置拒绝。
- cargo build --locked：通过。
- e2e.py --http：37 项通过，不生成证书，验证真实 TCP / PROXY / HTTP、Host / 端口、无 HSTS 及转发头不能改变传输模式。
- e2e.py：39 项 HTTPS 检查通过，含证书 / SNI 与按协议校验的 Host / HSTS。
- bash -n / shellcheck：两个发布脚本通过。
- installer.py：8 组通过，包内清单包含新增 HTTPS 模板和路由片段。

两种模式共用账号隔离、延迟 / 冲突日志、并发缓存、日志轮转、异常上游、页面 / JSON / 文本 / HEAD、历史持久化与损坏回退检查。使用模拟面板和 Xray 发送端，仍需 README 中的真实双账号验收。

## v0.3.2 公开发布验证

2026-11-14：[CI](https://github.com/youbilin/FlowNote/actions/runs/43586884263) 全部通过；[Release 工作流](https://github.com/youbilin/FlowNote/actions/runs/43597862401) 的原生 Linux amd64、arm64 与发布任务全部通过，[v0.3.2](https://github.com/youbilin/FlowNote/releases/tag/v0.3.2) 已公开。

- 重新从公开 Release 下载两个归档、install.sh 和 SHA256SUMS：清单中的三个文件校验全部通过。
- 两个归档的文件清单、文件类型、HTTP / HTTPS 模板与 HTTP 路由片段检查通过。
- readelf 确认分别为 X86-64 / AArch64，均无动态解释器。
- 实际下载的 amd64 程序报告 `flownote 0.3.2`，再次通过 37 项 HTTP 与 39 项 TLS / PROXY 集成检查。
- 实际下载的发布版 install.sh 以 `--version v0.3.2 --download-only` 从 GitHub 下载、校验并保存 amd64 离线包成功。没有在用户服务器执行 root 安装，也未把模拟集成测试视为真实 Xray 验收。

UI 沿用 v0.3.1 布局，仅更新版本号。此前视觉和发布记录如下。

---

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
