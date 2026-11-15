# v0.3.7 验证记录

日期：2026-11-15。Debian / WSL，Python 3.13，Rust 1.94.1。

- 84 组向导 / 卸载回归通过：HTTPS 域名与证书检测、已有 Token / URL 复用、保持旧内核出站形态、保留显示 / 历史 / 性能设置、重复配置不重启、Token / URL 单独变更只重启 FlowNote、只持久化缺失模板不重载，以及暂存 API 失败不改活动配置。
- 回退测试覆盖日志核对修改后失败、模板恢复冲突、诊断写入失败；各分支仍尝试恢复 x-ui。systemd 命令与面板应用使用隔离 SQLite 和模拟命令，未连接用户 VPS，不代表目标机器的双账号链路已经验收。
- 34 个 Rust 单元测试、9 组安装器检查、5 组真实 Xray v26.11.9 检查通过；fmt、clippy、shell 语法及 shellcheck 通过。
- 本地 release 构建通过 40 项 HTTP 和 42 项 HTTPS / PROXY 集成检查。

## v0.3.7 公开发布包复核

- 实现提交 `1c253a99950af6071181b8fdb9c697472c0fd749`；GitHub CI `43665416003`、双架构发布 `43665418189` 均成功。
- 从 GitHub 公开 Release 下载 amd64 / arm64 包、install.sh 和 SHA256SUMS，核对三个资产的 SHA-256；验证两种架构均为无解释器依赖的静态 ELF，包内包含 setup.py / setup.sh。
- 下载的 amd64 二进制报告 0.3.7，通过 40 项 HTTP、42 项 HTTPS / PROXY 集成检查；直接对包内向导运行全部 84 组回归与 5 组真实 Xray 检查，均通过。
- 使用下载的实际 Rust 程序和包内向导，对本机模拟面板验证暂存配置：有效 Token 成功且不重启；无效 Token 失败且活动配置 / Token 保持原样。系统服务命令仍为模拟，不操作主机服务。
- 包内 certificate_host 对真实 openssl 生成的单域名、多域名和通配符证书检测通过；实际 root PTY 进入卸载子菜单后返回退出，未修改主机配置。
- 下载的 install.sh 实际执行 --download-only，成功从公开 Release 下载并校验当前 amd64 包。

以下 v0.3.6 正式包测量保留为历史基线，本次未修改运行时调度或资源策略。

# v0.3.6 验证记录

日期：2026-11-15。Debian / WSL，Python 3.13，Rust 1.94.1。

- 69 组向导 / 卸载回归：实际日志优先、只读账号发现、默认自动输入与高级覆盖、依赖检测与安装、面板重启后的日志同步、管理 API 路由兼容、查询路由被遮蔽 / 地址掩码 / 日志关闭时拒绝启动，以及失败回退。
- 34 个 Rust 单元测试、9 组安装器检查、5 组真实 Xray v26.11.9 回归通过；fmt、clippy、shell 语法和 shellcheck 通过。
- Release 本地构建通过 40 项 HTTP 与 42 项 HTTPS / PROXY 集成检查，包含空闲超过一秒后延迟写入日志仍可唤醒关联、关闭历史仍返回当前流量且不创建历史目录。
- 新增 `python3 tests/performance.py /path/to/flownote --seconds 8`：临时日志、模拟本机面板、关闭历史，读取 /proc 的进程 CPU、RSS、线程和读取系统调用数，随后执行 30 次真实 PROXY / HTTP 查询。不修改 systemd 或用户 VPS。

测量只覆盖指定机器上的短时空闲和少量查询；不代表大规模并发或 Xray 整体资源消耗。systemd 的 MemoryMax=192M 是限制，不是实际预占内存。正式发布包的结果如下。

## v0.3.6 正式包测量与公开发布验证

[CI](https://github.com/youbilin/FlowNote/actions/runs/43614987137) 与 [Release](https://github.com/youbilin/FlowNote/actions/runs/43615007324) 均成功，amd64 / arm64 静态包已公开。

- 重新下载两个架构归档、install.sh 与 SHA256SUMS，三个资产摘要全部匹配；readelf 核对架构且均无动态解释器。
- 下载的 amd64 程序报告 0.3.6，再次通过 40 项 HTTP 和 42 项 HTTPS / PROXY 集成检查。
- 对下载包内的 setup.py 直接运行 69 组向导 / 卸载回归与 5 组真实 Xray 检查，均通过。真实 PTY 进入卸载子菜单后取消；未进行主机配置或删除。
- 公开安装脚本的 --download-only 实际远程下载与校验通过；未在用户 VPS 执行升级。

同一 Debian / WSL 机器（20 个逻辑 CPU），两版均使用 GitHub 下载的 amd64 静态 musl 包，同一测试脚本与配置，历史关闭，空闲窗口约 8 秒，随后串行执行 30 次 PROXY / HTTP 查询：

| 指标 | v0.3.5 | v0.3.6 |
|---|---:|---:|
| 空闲 RSS（KiB） | 3364 | 3368 |
| 查询后 RSS（KiB） | 4324 | 4168 |
| 空闲线程数 | 23 | 2 |
| 8 秒空闲读取调用 | 78 | 8 |
| 8 秒空闲 CPU 时间（秒） | 0.02 | 0.0 |
| 查询中位耗时（ms） | 53.77 | 27.55 |
| 查询最大耗时（ms） | 54.81 | 32.4 |

旧版线程数随 CPU 数和阻塞任务变化，另一次同机测量为 22 个；这不表示单核 VPS 也会减少相同数量的线程。CPU 时间读取自 /proc，0.00 秒只表示该短窗口内低于计时精度，不能解释为永远不占 CPU。RSS 为进程驻留内存，未计算 3x-ui / Xray；本机面板模拟器不计入。延迟是合成请求测试结果，不代表公网端到端耗时。两版原本都仅为几 MiB，本次主要减少线程和空闲唤醒，没有增加常驻服务。

---

# v0.3.5 验证记录

日期：2026-11-14。Debian / WSL，Python 3.13，Rust 1.94.1。

- 56 组向导 / 卸载回归通过：新增首次预检使用私有日志、正式日志检查在停服前执行、检查失败不写模板 / 不停止面板、诊断文件 0600 且终端不泄露原始秘密，以及 finalRules 重试只匹配明确的字段不支持错误。
- 9 组安装器检查、34 个 Rust 单元测试、cargo fmt --check、shell 语法和 shellcheck 通过。
- 从 Xray 官方 v26.11.9 Release 下载 Linux amd64 内核，以同一发布的 SHA2-256 核对摘要。归档 SHA-256 为 b651f7e1d9966ee2c1b1ee1bf8b52c72771824d3065dce96bbc8bcc19ed95f82。
- `python3 tests/setup_xray.py /实际测试内核路径`：5 组真实 Xray 检查通过，复现默认日志目录不存在时的旧错误、验证临时日志预检和准备正式日志后的完整检查、确认其他配置错误仍被拒绝及诊断文件私有。
- 真实内核检查使用隔离的临时配置与文件，未启动代理监听、修改面板数据库或执行用户 VPS 上的服务操作。安装向导的 systemd / SQLite 应用与回退通过模拟回归验证；目标服务器仍需真实双账号验收。


## v0.3.5 公开发布验证

[CI](https://github.com/youbilin/FlowNote/actions/runs/43609131863) 与 [Release](https://github.com/youbilin/FlowNote/actions/runs/43609153525) 均通过，原生 amd64 / arm64 安装包已公开。

- 重新下载两架构归档、install.sh 和 SHA256SUMS，所有摘要匹配；readelf 确认架构正确、无动态解释器。
- 下载的 amd64 二进制报告 0.3.5，通过 37 项 HTTP 与 39 项 HTTPS / PROXY 集成检查。
- 直接对包内 setup.py 运行全部 56 组向导回归与 5 组真实 Xray 回归，通过；进入实际 PTY 卸载子菜单并取消，通过，未执行主机配置或删除操作。
- 实际公开安装脚本的 --download-only 下载与校验通过。README 与包内说明已更新；未连接用户服务器执行升级或配置。

---

# v0.3.4 验证记录

2026-11-14，Debian / WSL。本地卸载回归使用临时 SQLite 与文件、模拟 systemd / Xray / 用户管理命令，不修改真实主机服务。

- `tests/setup.py`：48 组通过，新增查询配置反向合并、只恢复匹配日志键、重复安装备份检索、自定义 / 默认出站 / balancer 引用拒绝、固定路径 / 符号链接 / 挂载点保护、保留数据与完全清理、取消零写入、Xray 失败 / Ctrl-C 回退、仍在使用日志时保留账号、非标准账号保护。
- `tests/installer.py`：9 组通过。
- Rust fmt / clippy --all-targets、34 个单元测试、调试构建、37 项 HTTP 与 39 项 HTTPS / PROXY 集成检查通过。三个 shell 脚本通过 shellcheck。
## v0.3.4 公开发布验证

2026-11-14：[CI](https://github.com/youbilin/FlowNote/actions/runs/43605129974) 与 [Release](https://github.com/youbilin/FlowNote/actions/runs/43605289289) 全部通过，包含原生 Linux amd64 / arm64 构建及公开发布。

- 重新下载两个归档、install.sh 与 SHA256SUMS，全部资产摘要匹配；readelf 确认架构与静态程序，无动态解释器。
- 下载的 amd64 二进制版本为 0.3.4，37 项 HTTP 与 39 项 HTTPS / PROXY 检查再次通过。
- 实际包内 setup.py 在真实 PTY 进入卸载子菜单并返回，未选择任何删除操作；将 48 组向导 / 卸载回归直接运行于下载的 setup.py，全部通过，主机命令仍使用模拟实现。
- 实际公开 install.sh 以 `--version v0.3.4 --download-only` 从 GitHub 下载、校验并保存包成功。
- 未在用户 VPS 执行卸载、删除用户数据或修改真实 3x-ui。模拟回归不替代目标服务器运行验证。


---

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
