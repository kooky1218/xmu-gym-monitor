# 三个高校体育场馆自动化项目对比研究

研究日期：2026-11-02
研究方法：浅克隆仓库后直接检查 README、许可证、文件结构和源代码。
说明：本文只比较架构和工程模式，不复制凭据、Token、登录绕过、验证码
识别或预约提交实现。

## 1. 固定审查版本

| 项目 | 默认分支提交 | 提交日期 | 许可证 | 技术路线 |
|---|---|---|---|---|
| [zskfree/SZU_Sports](https://github.com/zskfree/SZU_Sports) | `7bd16f82f1ce513babb737e68f077a2e80439776` | 2026-07-17 | MIT | Tampermonkey 用户脚本，在已登录网页内发请求 |
| [G-dab/SJTUAppointment](https://github.com/G-dab/SJTUAppointment) | `29f19f438458bf148f205b69a63bc62edc27a675` | 2024-10-13 | 仓库未提供 LICENSE | Python + Selenium/Firefox + 验证码 OCR |
| [MinhZou/FudanCourtReservation](https://github.com/MinhZou/FudanCourtReservation) | `f50a13779f48df2cf6bcf814786bab2d9f44677e` | 2024-09-28 | MIT | Python + Selenium/Chrome + requests + 外部验证码平台 |

许可证结论：

- SZU 和复旦项目是 MIT，但直接复制代码仍需保留版权与许可声明。
- SJTU 仓库根目录没有 LICENSE 文件，README 也没有授予复用许可。即使代码
  公开可读，也不能据此推定可以复制或再分发。
- 本报告只提炼设计思想，不复制任何仓库代码。

## 2. 证据口径

本文使用两种描述：

- **代码实现**：已经由具体文件与代码路径确认。
- **README 宣称**：只代表作者文档说明，必须再与代码核对。

## 3. SZU_Sports

### 3.1 项目结构

```text
SZU_Sports/
├─ src/
│  ├─ SZU_Sports.js
│  └─ HZAU_Sports.js
├─ docs/
├─ README.md
└─ LICENSE
```

没有 Python/Node 包清单。运行依赖是 Tampermonkey 用户脚本环境。

来源：

- `src/SZU_Sports.js:1-18`
- README 的“项目结构”和“开发与安装”

### 3.2 前端页面管理

**代码实现：**

- 脚本只匹配深圳大学场馆预约页面。
- 创建悬浮按钮、侧边控制面板和弹层。
- 包含桌面与移动端检测、暗色/亮色主题、输入校验、键盘快捷键和日志框。
- 页面完全由用户脚本注入，不是独立桌面应用。

来源：

- 匹配规则和依赖：`src/SZU_Sports.js:1-18`
- 设备检测：`src/SZU_Sports.js:23-38`
- 页面样式和 UI：`src/SZU_Sports.js:40-392`
- 面板事件：`src/SZU_Sports.js:1660-1766`
- 初始化入口：`src/SZU_Sports.js:2344-2450`

可借鉴点：

- 配置区与执行区分离。
- 配置校验前置，错误直接显示在日志中。
- 桌面和移动端布局不同，但状态模型一致。

不应照搬点：

- 把业务 UI 注入目标站点，维护成本高且与页面 DOM 强绑定。
- 当前项目的 PySide6 已经比注入页面更适合独立后台和日志管理。

### 3.3 数据读取机制

**代码实现：**

- 查询使用同源 `fetch()`，依赖浏览器当前页面已有的会话 Cookie。
- 先用 `getOpeningRoom.do` 读取可预约场地，再解析 `text`、`CDMC`、
  `CGBM`、`WID` 等字段。
- 请求设置了超时、请求节流、错误分类和退避重试。
- 这不是“独立认证接口”，而是复用用户已经登录的页面上下文。

来源：

- 请求节流：`src/SZU_Sports.js:536-575`
- 带超时请求：`src/SZU_Sports.js:1938-1979`
- 数据读取与结构化：`src/SZU_Sports.js:1981-2097`
- `credentials: 'same-origin'`：`src/SZU_Sports.js:1950`

### 3.4 状态管理

**代码实现：**

- 有一个 `Storage` 封装，依次尝试 `localStorage`、`sessionStorage` 和
  内存 Map。
- 保存值带版本号和时间戳，默认 7 天过期。
- 定时任务状态可持久化，页面刷新后恢复。
- 在任务开始前约 30 秒主动刷新页面，以保持浏览器会话和恢复状态。

来源：

- 存储管理器：`src/SZU_Sports.js:394-488`
- 定时任务持久化与恢复：`src/SZU_Sports.js:989-1077`
- 页面刷新恢复：`src/SZU_Sports.js:2406-2430`

可借鉴点：

- 配置文件需要版本号、保存时间和过期规则。
- 刷新页面或重启程序后应能恢复“非敏感任务配置”。

不应照搬点：

- 页面刷新保活只适用于浏览器脚本，不适用于当前 Python 服务。
- 不应把登录 Cookie 放入这类持久化配置。

### 3.5 定时任务与服务器时间

**代码实现：**

- 使用浏览器 `setTimeout` 做页面内定时，依赖页面保持打开。
- 定时时间来自本机 `Date.now()`。
- SZU 脚本没有服务器时间校准逻辑。
- HZAU 脚本另有多点采样 `HEAD Date` 响应头的服务器时间校准。

来源：

- SZU 定时器：`src/SZU_Sports.js:989-1077`
- HZAU 时间校准：`src/HZAU_Sports.js:319-375`

结论：

- SZU 的“定时”不是操作系统级任务，不能替代 Windows 任务计划程序。
- 当前项目已经有 Windows 任务计划程序，不应再引入页面内 `setTimeout`
  作为主调度器。

### 3.6 日志和异常恢复

**代码实现：**

- 页面日志最多保留 50 条，之后移除最旧条目。
- 日志只存在 DOM，不写文件，页面刷新会丢失。
- 网络错误分为限流、服务端错误、认证错误、客户端错误、超时和未知错误。
- 429、5xx、网络错误、超时使用不同退避时间；认证和客户端错误不重试。
- 连续失败计数只在达到阈值时输出警告，没有持久化故障状态。

来源：

- 错误分类和重试策略：`src/SZU_Sports.js:490-534`
- 智能失败计数：`src/SZU_Sports.js:577-596`
- 页面日志：`src/SZU_Sports.js:1901-1924`

可借鉴点：

- 认证错误立即停止，不做无意义重试。
- 429/5xx/网络错误分别处理。
- 日志要有上限，防止界面无限增长。

不应照搬点：

- 当前项目已有 RotatingFileHandler，持久化能力更强。
- SZU 的固定重试上限混在 `fetchWithTimeout` 中，策略与传输层耦合过深。

### 3.7 预约与通知

**代码实现：**

- 确实实现了预约请求、批量轮询、重复预约识别、企业微信通知。
- README 声明只用于学习，但代码包含完整预约执行路径。
- 源码中存在硬编码的外部 Webhook 地址和签名密钥，这是不应沿用的安全
  反模式。

来源：

- 预约提交：`src/SZU_Sports.js:2099-2194`
- 主轮询流程：`src/SZU_Sports.js:2198-2341`
- 通知与外链配置：`src/SZU_Sports.js:643-700`

本项目不复制上述预约、签名或通知凭据。

## 4. SJTUAppointment

### 4.1 项目结构

```text
SJTUAppointment/
├─ main.py
├─ template.json
├─ SJTUAppointment/
│  ├─ config.py
│  ├─ SJTUAppointment.py
│  ├─ SJTUVenueTabLists.py
│  └─ utils/
│     ├─ captcha_rec.py
│     └─ messages.py
└─ README.md
```

没有 `requirements.txt`、`pyproject.toml` 或 LICENSE。README 手工列出
`selenium`、`pillow`、`pytesseract`、`requests` 和外部浏览器驱动。

来源：

- README “环境配置”
- `main.py:1-10`
- `SJTUAppointment/SJTUAppointment.py:1-11`

### 4.2 前端页面管理和浏览器自动化

**代码实现：**

- 使用 Selenium Firefox/geckodriver。
- 默认无头，`--head` 切换为可见浏览器。
- 通过 ID、class name 和 CSS selector 操作预约站点。
- 依次登录、搜索场馆、选项目、日期、时段并确认。

来源：

- 浏览器和日期生成：`SJTUAppointment/SJTUAppointment.py:13-38`
- 打开页面：`SJTUAppointment/SJTUAppointment.py:41-46`
- 场馆与日期操作：`SJTUAppointment/SJTUAppointment.py:78-133`
- 主流程：`SJTUAppointment/SJTUAppointment.py:146-159`

这是真实 Selenium 实现，不是 README 夸大。

### 4.3 数据读取机制和状态管理

**代码实现：**

- 数据不是通过稳定 JSON API 读取，而是直接寻找 DOM 中的
  `unselected-seat` 元素。
- 状态主要是 `ordered_flag` 和 `tryTimes` 两个内存字段。
- `book()` 在成功后停止，失败则刷新页面继续循环。
- 没有结构化数据模型、缓存、日志状态机或显式认证适配器。
- 日期以“从今天起 N 天”生成，不是固定日期。

来源：

- 状态字段：`SJTUAppointment/SJTUAppointment.py:13-31`
- 日期偏移：`SJTUAppointment/SJTUAppointment.py:33-38`
- 时段 DOM：`SJTUAppointment/SJTUAppointment.py:109-133`
- 循环：`SJTUAppointment/SJTUAppointment.py:146-159`

### 4.4 定时任务和服务器时间

**代码实现：**

- 没有调度器或独立定时任务模块。
- README 中的“运行”是立即进入 Selenium 循环。
- 多处使用固定 `sleep`，没有服务器时间校准。

结论：SJTU 项目不适合作为当前项目定时架构参考。

### 4.5 日志与异常恢复

**代码实现：**

- 使用基础 `logging.basicConfig` 写入 `sport.log`。
- 没有日志轮转。
- 登录最多尝试 10 次。
- 预约循环捕获异常后只打印并延迟，没有分类、退避或任务状态。
- 所有日志级别基本为 INFO。

来源：

- 日志配置：`main.py:61-74`
- 登录重试：`SJTUAppointment/SJTUAppointment.py:49-76`
- 预约异常：`SJTUAppointment/SJTUAppointment.py:146-159`

### 4.6 认证方式

**代码实现：**

- 明文学号和密码保存在 `SJTUAppointment/config.py` 中。
- 使用 Tesseract OCR 识别登录验证码。
- 成功后继续使用同一 WebDriver 会话。
- README 明确说明了账号密码配置以及验证码识别。

来源：

- 凭据占位：`SJTUAppointment/config.py:1-6`
- 自动登录和验证码：`SJTUAppointment/SJTUAppointment.py:49-76`
- OCR：`SJTUAppointment/utils/captcha_rec.py:1-15`

结论：

- 这条路线依赖自动化登录和验证码识别，本阶段不采用，也不能移植到当前
  微信小程序认证场景。
- 仓库没有许可证，更不应复制实现。

### 4.7 桌面交互与通知

**代码实现：**

- 命令行参数或 JSON 任务文件。
- 成功时播放 Windows `winsound.Beep`，通过方糖 API 通知。
- 没有 GUI。

来源：

- CLI 和声音：`main.py:12-58`
- 通知请求：`SJTUAppointment/utils/messages.py:1-12`

可借鉴点仅限于“配置文件作为任务输入”和“任务完成后通知”的思路。

## 5. FudanCourtReservation

### 5.1 项目结构

```text
FudanCourtReservation/
├─ main.py
├─ configs/user_configs.yaml
├─ chromedriver/
├─ scripts/client.py
├─ utils/
│  ├─ chaojiying.py
│  ├─ image_process.py
│  └─ send_email.py
└─ readme.md
```

没有依赖清单。`scripts/client.py` 实际导入 `yaml`、`apscheduler`、
`beautifulsoup4`、`lxml`、`requests`、Selenium、NumPy、OpenCV、Pillow
等，安装成本明显高于 README 描述。

来源：

- 导入：`scripts/client.py:10-42`
- 配置：`configs/user_configs.yaml:1-10`

### 5.2 前端页面管理和浏览器自动化

**代码实现：**

- Selenium Chrome 无头模式登录 CAS。
- 登录后导出 Cookie，再用 `requests` 读取 HTML。
- 预约确认时再次启动 Chrome，注入 Cookie，处理动态验证码，然后提交。
- 这是浏览器自动化和直接 HTTP 的混合架构。

来源：

- 登录并导出 Cookie：`scripts/client.py:146-177`
- requests 读取资源：`scripts/client.py:179-214`
- 注入 Cookie 后打开订单页：`scripts/client.py:280-350`

安全评价：

- 源码通过日志输出完整 Cookie。这是严重反模式，不能效仿。
- Cookie/Token 不应出现在普通日志中。

证据：

- `scripts/client.py:167-170`

### 5.3 数据读取机制

**代码实现：**

- `get_resource()` 用 requests 请求 HTML。
- BeautifulSoup 解析 `site_table`，提取开始时间和资源 ID。
- `get_status()` 同样解析 HTML 表格，提取订单 ID。
- 它不是 JSON API 客户端，解析依赖 HTML 结构。

来源：

- 资源读取：`scripts/client.py:179-214`
- 订单状态：`scripts/client.py:352-382`

对当前项目的含义：

- 当前项目直接解析 JSON 更稳定，不需要退化为 HTML DOM。
- 只有正式 API 不可用时，才考虑浏览器 DOM/HTML 作为高成本兼容层。

### 5.4 状态管理和定时任务

README 宣称：

- 定时任务；
- 多进程多线程；
- 多用户；
- 捡漏模式。

代码核对：

- `main.py` 导入 `BlockingScheduler`，但实际入口直接调用
  `scheduled_job()`；APScheduler 代码被注释。
- `scheduled_job()` 实际按时间段启动多个 `multiprocessing.Process`，
  不是持久化 cron 任务。
- `main.py` 只读取 `configs['user1']`，没有多用户循环。
- “捡漏”实际由重复查询资源及重试流程组成。

来源：

- 调度器导入和未使用代码：`main.py:8-24`
- 多进程启动：`scripts/client.py:521-547`
- 单用户配置：`main.py:15-20`

因此 README 的“定时任务、多用户、调度能力”只能部分确认：

- 多进程：**代码确认**
- 多线程资源查询：**代码确认**
- 多用户：**未实现为通用流程**
- APScheduler 定时：**代码中未启用**

### 5.5 服务器时间处理

**代码实现：**

- 使用本机 `datetime.now()`。
- 将预约日期设为“当前时间 + 2 天”。
- 将阶段运行截止时间设为“当前时间 + 5 分 40 秒”。
- 没有服务端 `Date` 头采样，也没有网络 RTT 校准。

来源：

- 日期和截止时间：`scripts/client.py:124-127`
- 每次执行重新计算：`scripts/client.py:443-447`

结论：

- 复旦项目的服务器时间处理弱于 HZAU。
- 当前项目若未来需要精确按时刷新，应参考 HZAU 的采样方法，而不是复旦
  的本机时间偏移。

### 5.6 日志和异常恢复

**代码实现：**

- 使用 `logging.basicConfig` 输出到控制台，不带文件轮转。
- 出错后常重新执行 Selenium 登录并刷新 Cookie。
- 部分循环使用随机等待。
- 有无限重试型流程，缺少统一退避上限和认证失败熔断。

来源：

- 日志配置：`scripts/client.py:44`
- 异常重新登录：`scripts/client.py:460-470`
- 轮询和随机等待：`scripts/client.py:472-519`

当前项目已有更清楚的异常分类和本地日志持久化，但可以借鉴其
“认证失效后停止当前流程并重建上下文”的状态意识，不能借鉴其 Cookie
日志和无限重试。

### 5.7 认证、验证码和通知

**代码实现：**

- YAML 中保存账号和密码。
- 登录时自动填表并点击。
- 使用超级鹰等外部平台识别点选验证码。
- 邮件工具里存在硬编码发件人和占位密码。

来源：

- 登录：`scripts/client.py:146-177`
- 动态验证码：`scripts/client.py:216-340`
- 邮件：`utils/send_email.py:6-25`

本阶段明确不采用、不移植这部分。

## 6. 横向架构对比

| 维度 | SZU_Sports | SJTUAppointment | FudanCourtReservation | 对当前项目的判断 |
|---|---|---|---|---|
| 页面管理 | 用户脚本注入 DOM，`SZU_Sports.js:40-392,1660-1766` | Selenium 操作原生网页，`SJTUAppointment.py:41-159` | Selenium 登录 + HTML 解析，`client.py:146-350` | 保留 PySide6，不改为网页注入 |
| 数据读取 | 同源 fetch + JSON，`SZU_Sports.js:1938-2097` | DOM 席位元素，`SJTUAppointment.py:109-133` | requests 抓 HTML + BeautifulSoup，`client.py:179-214` | 当前 JSON reader 更优 |
| 状态管理 | 版本化 Storage + 定时恢复，`SZU_Sports.js:394-488,989-1077` | 两个内存布尔/计数，`SJTUAppointment.py:13-31` | Manager dict + 多进程共享，`client.py:120-127` | 借鉴版本化配置，保留现有缓存与元数据 |
| 定时任务 | 页面内 setTimeout 和刷新恢复 | 无调度器 | APScheduler 导入但未启用，实际 multiprocessing | Windows Task Scheduler 更适合当前项目 |
| 服务器时间 | SZU 未校准；HZAU 多点 HEAD 采样，`HZAU_Sports.js:319-375` | 本机时间和固定 sleep | 本机时间 + 2 天 | 可后置借鉴 HZAU |
| 日志 | DOM 50 条，不持久 | 单文件，无轮转 | 控制台，无轮转且泄露 Cookie | 当前轮转日志更成熟 |
| 异常恢复 | 分类、退避、认证停止，`SZU_Sports.js:490-596` | 固定 sleep 和循环 | 重登 + 随机等待 + 无限循环 | 借鉴 SZU 分类，不借鉴无限重试 |
| 桌面交互 | 网页悬浮面板 | CLI | CLI | 保留 PySide6 |
| 浏览器自动化 | 无 WebDriver，依赖当前页面 | Selenium Firefox | Selenium Chrome + requests | 当前只读阶段不应引入 |
| 认证方式 | 复用用户已登录页面 Cookie | 账号密码 + OCR | 账号密码 + Cookie 提取 + 付费验证码 | 三者均不能形成正式独立认证 |
| 验证码处理 | 无 | OCR | 外部识别平台 | 明确不采用 |
| 预约提交 | 有 | 有 | 有 | 当前项目继续禁止 |

## 7. 与当前项目的逐项对照

### 7.1 已完成，无需重复开发

| 模块 | 当前实现 | 判断 |
|---|---|---|
| HTTP 只读客户端 | `src/api/stadium_reader.py:420-741` | 已完成，优于三个项目的预约耦合代码 |
| 场次解析 | `parse_stadium_details`、`parse_intervals` | 已完成 |
| 认证适配器边界 | `AuthenticationAdapter`、`NoAuthentication`，`stadium_reader.py:82-105` | 结构正确，但尚无正式实现 |
| 缓存与元数据 | `src/api/cache.py:24-83`、`stadium_reader.py:459-741` | 已完成，三者均无同类设计 |
| 桌面 UI | `src/ui/main_window.py:48-405` | 已完成，应保留 |
| 异常分类 | `authentication_required`、`transport_error` 等 | 已完成 |
| 日志持久化 | `src/main.py:13-33` | 已完成，强于三个参考项目 |
| Windows 调度 | `tools/run_auth_diagnostic_task.cmd` | 已完成可行性验证 |

### 7.2 可优化

| 优化项 | 参考来源 | 原因 |
|---|---|---|
| 配置版本和过期策略 | SZU `Storage` | 当前只有快照，没有版本化用户配置 |
| 失败结果持久化 | SZU 错误分类思路 | 当前诊断 JSON 有记录，但服务层没有正式运行历史模型 |
| 重试策略模块化 | SZU 错误分类 + 退避 | 当前主要是单次失败，尚无集中重试策略 |
| 服务器时间校准 | HZAU `syncServerTime` | 仅在未来需要精确定时刷新时有价值 |
| 任务结果通知 | SJTU/复旦 | 可作为后续可选通知适配器 |
| UI 和任务配置复用 | SZU 配置管理 | 可用独立 JSON/YAML 配置层，禁止存凭据 |

### 7.3 不建议开发

| 不建议项 | 理由 |
|---|---|
| 把业务 UI 注入目标 H5 | 当前有独立 PySide6，无需绑定网页 DOM |
| 自动 OCR 验证码 | 违反本阶段约束，也与正式授权方向相反 |
| 从微信或 Chromium 导出 Cookie 供后台重放 | 凭据安全、合规和会话稳定性都不可接受 |
| 页面内无限轮询作为后台主调度 | Windows Task Scheduler 更可靠 |
| 用 Selenium 代替现有 JSON API | 速度更慢、资源更高、DOM 更易变 |
| 复制三个仓库的预约/通知代码 | 本阶段只读，且不能复制认证逻辑 |

## 8. 技术方案评估

### 8.1 是否值得增加 Playwright？

**当前不建议作为核心依赖。**

原因：

1. 当前数据接口已经能返回结构化 JSON，直接 HTTP 更轻量。
2. 当前阻塞点是正式认证，不是页面渲染。
3. Playwright 无法自然继承 Windows 微信小程序的 WebView 会话。
4. 用 Playwright 自动填账号或验证码会重新落入本阶段明确禁止的认证
   自动化。
5. 国内校园站点的 WebView、证书、代理和无头浏览器兼容性可能增加维护
   成本。

可以考虑的受限场景：

- 校方明确提供一个普通网页登录流程；
- 登录由用户在可见浏览器中完成，程序只保存经批准的短期会话；
- Playwright 仅用于 DOM 验证或端到端回归测试，不用于绕过访问控制。

在这些前提满足前，Playwright 的收益不足以抵消依赖和安全风险。

### 8.2 是否值得增加浏览器 DOM 读取模块？

**当前没有必要。**

当前 JSON reader 已能区分 HTTP/业务/解析状态，DOM 读取会更脆弱。

可保留一个未来的“诊断型 DOM adapter”：

- 只在 API 结构变化时用于人工排查；
- 不进入默认生产路径；
- 不读取页面中的 Cookie/Token；
- 必须标记 `data_source=dom`，不能冒充 API 实时数据。

### 8.3 是否值得保留 PySide6 架构？

**值得保留。**

理由：

- 三个参考项目中只有 SZU/HZAU 有交互面板，但都依附目标网页。
- PySide6 可以控制日志、缓存、数据来源和认证状态，不受目标页面改版
  直接影响。
- 当前界面已支持实时/历史数据区分。

需要优化的是 UI 与业务层的依赖方向，而不是替换框架。

### 8.4 如何把后台服务与桌面界面彻底解耦？

建议增加一个最小应用服务层：

```text
UI / CLI / Task Scheduler
          |
          v
StadiumQueryService
  - 读取
  - 缓存决策
  - 认证状态
  - 诊断元数据
          |
          v
StadiumReader + AuthenticationAdapter + SnapshotCache
```

具体约束：

1. `StadiumReader` 不导入 PySide6。
2. UI 只调用 `StadiumQueryService.read_once()`，不直接管理解析和缓存。
3. 计划任务调用同一服务入口，不实例化 UI。
4. 结果使用普通数据类/字典传递，不在 worker 之间传 QObject。
5. 日志、缓存路径、认证适配器由组合根注入，UI 不读取环境凭据。
6. CLI 和桌面共享同一份错误码与诊断 metadata。

这会把当前 `RefreshWorker -> StadiumReader` 的直接连接替换为
`UI -> QueryService -> Reader`，但不必重写现有 reader 或界面。

### 8.5 如何改善认证失败后的异常处理？

建议显式的认证状态机：

```text
not_configured
authenticated
expired
forbidden
unknown
```

行为：

- `authentication_required`：立即停止当前任务，不重试；
- 标记 `needs_reauth=true`；
- 保留上次成功快照，显示为历史数据；
- 计划任务返回非成功语义词，例如 `AUTH_REQUIRED`；
- 在日志中记录时间、接口、HTTP/业务状态，不记录凭据；
- 只有新的获准认证完成后才清除 `needs_reauth`；
- 可增加指数退避和熔断，但认证失败不参与重试。

SZU 的错误分类和复旦的“重建上下文中断”思路可以提供概念参考，但不应
复制其认证实现。

### 8.6 服务器时间处理

HZAU 的实现值得作为未来参考：

- 多次 `HEAD` 请求；
- 读取 HTTP `Date` 头；
- 用客户端往返时间降低采样误差；
- 选择最小 RTT 的样本；
- 明确区分本机时间和校准时间。

但当前项目是只读数据读取，不涉及抢预约，暂时不需要引入高频时间同步。
若以后增加计划刷新，可先实现低频、带缓存的 `ServerClock`，并只作为
辅助信息，不作为绕过权限的手段。

## 9. 推荐目标架构

```text
src/
├─ api/
│  ├─ stadium_reader.py       # 只负责 HTTP + 解析
│  └─ cache.py                # 只负责快照持久化
├─ services/
│  ├─ stadium_query.py        # 读取、缓存和结果编排
│  ├─ auth_state.py           # 认证状态机
│  └─ retry_policy.py         # 网络/服务错误退避
├─ ui/
│  └─ main_window.py          # 只处理展示和用户操作
├─ jobs/
│  └─ read_once.py            # Task Scheduler 入口
└─ auth/
   └─ approved_adapter.py     # 正式授权后实现，不保存明文密码
```

这是建议架构，不是本阶段已经修改的代码。

## 10. 优先级改进清单

### P0：认证边界和数据语义

1. 增加 `StadiumQueryService`，统一 UI/CLI/计划任务的调用入口。
2. 增加认证状态机，认证失败立即停止并标记 `needs_reauth`。
3. 增加 `RetryPolicy`，仅对网络/5xx/限流重试，认证与业务错误不重试。
4. 为 Task Scheduler 增加结构化退出码和运行记录。

收益：不改变现有读取和 UI，显著降低后台误判和无效重试。

### P1：可维护性和配置

5. 把场地、刷新频率、日志上限、缓存路径抽到版本化配置。
6. 把快照元数据版本从单一字段扩展为明确的 `schema_version` 和
   `metadata_version`。
7. 增加“最近成功 / 最近失败 / 认证状态”运行摘要。
8. 增加低频服务器时间偏移诊断，只记录，不参与权限判断。

收益：让后台任务可审计，降低配置散落。

### P2：可选增强

9. 若校方明确提供正式认证，再实现 `ApprovedAuthAdapter`。
10. 若确有官方网页登录流程，再评估 Playwright 作为辅助认证/回归测试。
11. 增加可选通知适配器（邮件、企业微信），但不硬编码任何 Webhook。
12. 增加 API schema 合约测试和响应样本脱敏测试。

## 11. 最终结论

三个项目都不能直接解决当前项目的独立认证问题：

- SZU 复用浏览器已登录会话；
- SJTU 自动填写账号密码并识别 OCR 验证码；
- 复旦自动登录、提取 Cookie 并接入付费验证码平台。

最值得借鉴的是：

- SZU 的配置版本、错误分类、请求节流和页面状态恢复思想；
- HZAU 的服务器时间多采样和最小 RTT 校准；
- 复旦的多进程组织只能作为概念观察，其 README 能力大于实际启用代码。

当前项目应继续坚持：

- JSON API 优先；
- PySide6 独立桌面界面；
- 只读优先；
- 明确缓存来源和年龄；
- Windows Task Scheduler 作为后台入口；
- 正式认证适配器介入后，才讨论无人值守读取。

不建议现在引入 Playwright、浏览器 DOM 读取或自动验证码。认证问题应用
正式授权方案解决，不能用浏览器自动化替代访问控制。
