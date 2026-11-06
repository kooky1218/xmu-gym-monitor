# 厦大体育健身房只读数据系统

这是一个面向厦门大学翔安校区爱秋体育馆健身房的只读监控程序。它从
Windows 微信里已登录的“厦大体育”小程序读取页面状态，使用 PySide6
提供桌面展示界面，并通过 Bark 向 iPhone 发送开放提醒。

当前范围：

- 自动从首页只读导航到“翔安校区健身房”；
- 读取日期级“预定 / 暂无”状态；
- 日期出现“预定”时自动进入选场页，逐个日期读取时间段和容量分数；
- 计算个人/包场剩余名额；
- 区分认证失效、业务失败、网络失败和响应格式异常；
- 为实时、缓存和失败结果输出统一诊断元数据；
- 成功后原子保存历史快照；
- 网络失败时明确标注并显示历史缓存；
- 按指定日期、时段和最低名额监控空位；
- SQLite 持久化状态并跨重启去重；
- 通过 Bark 向 iPhone 发送空位提醒；
- Windows 登录后启动常驻守护进程，每 5 分钟只读检查；
- 桌面界面启动后自动刷新，同时保留手动刷新按钮；
- 最小化或关闭窗口时隐藏到 Windows 右下角托盘，后台监控继续运行；
- 手动刷新和日志查看；
- 不提交订单、不处理验证码、不读取或重放 Cookie。
- 日期级“预定”只表示预约入口开放，不等同于已确认具体时间仍有空位。

## 下载与安装

GitHub 仓库：

<https://github.com/kooky1218/xmu-gym-monitor>

从 GitHub Releases 下载：

```text
xmu-gym-monitor-v1.0.0-windows.zip
```

解压后在 PowerShell 中运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_windows.ps1
```

安装完成后可双击桌面的“厦大健身房空位监控”。后台监控会在 Windows
登录后自动运行。

## 项目性质

本项目是非官方、Windows 专用、只读研究工具，与厦门大学及其体育场馆系统
没有隶属关系。使用者必须自行保证账号、数据和使用方式符合学校规定。项目
不提供抢预约、自动下单、验证码处理或登录绕过能力。

## 目录结构

```text
xmuty-gym-reader/
├─ docs/
│  ├─ API_ANALYSIS.md
│  ├─ FEASIBILITY_REPORT.md
│  ├─ AUTH_DIAGNOSTIC_REPORT.md
│  ├─ DATA_SOURCE_REPORT.md
│  ├─ BACKGROUND_FEASIBILITY.md
│  ├─ MONITOR_GUIDE.md
│  ├─ IOS_NOTIFICATION_SETUP.md
│  ├─ WINDOWS_SETUP.md
│  └─ TEST_REPORT.md
├─ cache/
│  └─ latest_snapshot.json       # 成功后生成，不保存凭据
├─ config/
│  ├─ monitor_config.json
│  └─ monitor_config.example.json
├─ data/
│  └─ monitor_state.sqlite3
├─ logs/
│  ├─ app.log
│  ├─ monitor.log
│  └─ auth_diagnostic.jsonl
├─ src/
│  ├─ api/
│  │  ├─ __init__.py
│  │  ├─ cache.py
│  │  └─ stadium_reader.py
│  ├─ platform/
│  │  └─ windows_state.py
│  ├─ monitor/
│  │  ├─ availability_monitor.py
│  │  ├─ change_detector.py
│  │  ├─ config.py
│  │  ├─ miniprogram_reader.py
│  │  └─ miniprogram_ui_reader.py
│  ├─ notification/
│  │  ├─ bark_notifier.py
│  │  ├─ credential_store.py
│  │  └─ messages.py
│  ├─ service/
│  │  └─ background_worker.py
│  ├─ ui/
│  │  ├─ __init__.py
│  │  ├─ main_window.py
│  │  └─ monitor_settings.py
│  ├─ __init__.py
│  └─ main.py
├─ tests/
│  ├─ test_cache_and_metadata.py
│  ├─ test_availability_monitor.py
│  ├─ test_change_detector.py
│  ├─ test_bark_notifier.py
│  ├─ test_background_worker.py
│  ├─ test_monitor_settings.py
│  ├─ test_stadium_reader.py
│  └─ test_ui_smoke.py
├─ scripts/
│  ├─ install_scheduler.ps1
│  ├─ run_monitor_once.cmd
│  └─ uninstall_scheduler.ps1
├─ tools/
│  ├─ run_auth_diagnostic.py
│  ├─ run_auth_diagnostic.ps1
│  └─ run_auth_diagnostic_task.cmd
├─ .gitignore
├─ app.py
├─ requirements.txt
└─ README.md
```

## 环境

- Windows
- Python 3.10+
- `requests`
- `PySide6`
- `keyring`

安装：

```powershell
cd D:\Codex++\data\2026-11-02\x20\outputs\xmuty-gym-reader
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动桌面界面

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -m src.main
```

也可以使用统一入口：

```powershell
.\.venv\Scripts\python.exe app.py
```

当前桌面程序和后台任务都使用 `MiniProgramStadiumReader`。读取前请保证：

1. Windows 微信已登录；
2. “厦大体育”小程序窗口仍存在且登录有效；
3. 页面可以停留在首页、场馆列表或翔安校区健身房详情。

程序不会弹出 Chrome 登录页，也不会读取微信 Cookie。页面读取成功时数据
来源标记为 `mini_program_live`；失败时历史快照标记为 `cache`，不会伪装成
实时数据。

## 空位监控与 iPhone 通知

启动 GUI 后点击“监控设置”：

1. 日期列表留空时监控小程序当前可见的全部日期。
2. 时段列表留空时监控整个日期；只有明确选择时段才做具体时间匹配。
3. 设置检查间隔、最低剩余名额和通知冷却。
4. 安全保存 Bark Key。
5. 发送测试通知并启用监控。

无 GUI 单次运行：

```powershell
.\.venv\Scripts\python.exe app.py --run-once
```

测试 Bark：

```powershell
.\.venv\Scripts\python.exe app.py --send-test-notification
```

模拟空位通知：

```powershell
.\.venv\Scripts\python.exe app.py --simulate-notification
```

模拟消息明确标记为测试，不写入正式空位状态。

当前机器已在 Windows 启动文件夹创建：

```text
厦大健身房空位监控.lnk
  -> tools\LaunchMonitorDaemon.exe
  -> .venv\Scripts\pythonw.exe app.py --daemon
```

登录 Windows 后会自动启动常驻后台监控。守护进程每 5 分钟读取一次配置并
执行只读检查；登录失效时继续等待，用户重新登录小程序后自动恢复。

桌面快捷方式：

```text
厦大健身房空位监控.lnk
  -> tools\LaunchGymMonitor.exe
  -> pythonw.exe app.py
```

如果快捷方式缺失，可重新生成带自定义图标的桌面入口：

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\install_desktop_shortcut.ps1 `
  -ImagePath ".\my-icon.jpg" `
  -Circular
```

托盘图标使用同一个圆形哑铃图标：

- 双击：重新打开监控界面；
- 右键：打开、立即刷新或退出程序；
- 只有选择“退出程序”才会真正结束后台界面进程。

Windows 任务计划程序脚本仍保留作为备用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_scheduler.ps1

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\uninstall_scheduler.ps1
```

本机实测中 Windows 会持续把计划任务标记回 `Disabled`，因此当前生产入口
改用启动文件夹守护进程。守护进程可以在锁屏时继续运行，但不能在用户注销、
微信退出或小程序登录失效时保证读取。

详细文档：

- `docs/MONITOR_GUIDE.md`
- `docs/IOS_NOTIFICATION_SETUP.md`
- `docs/WINDOWS_SETUP.md`
- `docs/TEST_REPORT.md`

## 命令行走廊

只读取并输出原始场馆详情：

```powershell
.\.venv\Scripts\python.exe -m src.api.stadium_reader --details-only
```

读取完整健身房快照：

```powershell
.\.venv\Scripts\python.exe -m src.api.stadium_reader
```

如果本机设置了不可用的 `HTTP(S)_PROXY`，可为该次调用加
`--no-system-proxy`。这会忽略当前进程继承的代理变量，不会修改系统代理：

```powershell
.\.venv\Scripts\python.exe -m src.api.stadium_reader `
  --details-only `
  --no-system-proxy
```

可以显式提供已获授权的 `venue_id` 和 `user_range`：

```powershell
.\.venv\Scripts\python.exe -m src.api.stadium_reader `
  --venue-id "<approved venue id>" `
  --user-range "<approved range>"
```

命令行退出码：

- `0`：读取成功；
- `1`：业务、网络或解析失败；
- `2`：需要认证。

## 认证与数据来源诊断

运行一个固定场景：

```powershell
.\.venv\Scripts\python.exe -m tools.run_auth_diagnostic `
  --scenario A `
  --target-date 2026-11-03 `
  --output "logs\auth_diagnostic.jsonl"
```

场景：

- `A`：微信主窗口显示；
- `B`：微信主窗口最小化；
- `C`：微信完全退出；
- `D`：Windows 锁屏并由任务计划程序执行。

`target-date` 仅用于实验记录。当前详细接口路径不接收日期参数，日期是在
`getInterval` 的返回结构中由用户选择。

PowerShell 包装器：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\tools\run_auth_diagnostic.ps1 `
  -Scenario A
```

每次运行都会记录：

```text
data_source
fetched_at
cache_age
http_status
business_status
request_success
parse_success
error_type
```

诊断脚本不使用缓存，以隔离当前网络请求的真实结果。

## 接入正式认证

实现 `AuthenticationAdapter`，在 `configure(session)` 中配置经校方批准的
认证方式：

```python
class ApprovedAuthAdapter:
    @property
    def label(self) -> str:
        return "校方批准的认证"

    def configure(self, session) -> None:
        # 从受控凭据存储中取得凭据并写入 session。
        # 不得打印、记录或提交 Cookie/Token。
        ...
```

然后注入：

```python
reader = StadiumReader(auth_adapter=ApprovedAuthAdapter())
snapshot = reader.read_gym_snapshot()
```

不要将 Cookie、Token 或密码硬编码到 Python、配置文件、日志或测试数据中。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试覆盖：

- 场馆详情响应解析；
- 日期、时段和场地解析；
- 剩余名额和服务状态派生；
- 认证失效识别；
- 实时与历史缓存来源标记；
- 历史缓存失败回退；
- 两接口读取链路；
- PySide6 界面离屏冒烟测试（安装 PySide6 后执行）。

2026-11-05 实际验证结果：

```text
Ran 80 tests
OK
```

- PySide6 `6.12.0` 桌面事件循环离屏启动成功，退出码 `0`。
- 真实交互桌面扫描返回 `mini_program_live`。2026-11-06 页面识别到
  `11月06日`、`11月07日`，两天状态均为“暂无”。
- 桌面界面点击刷新后显示两个真实日期行，来源为
  `小程序实时页面（mini_program_live）`。
- 后台单次任务返回 `NO_NEW_AVAILABILITY`，匹配 2 个日期，通知 0 条。
- Windows 登录启动守护进程已完成连续多轮 5 分钟自动检查。
- 2026-11-06 在“厦大体育”窗口最小化时完成真实读取，窗口保持最小化。

## 已知限制

1. 日期页的“预定”只表示预约入口开放，具体时段仍需进入选场页确认。
2. 选场页的容量网格解析是尽力而为；未识别时不会虚构剩余人数。
3. 当前没有验证 Windows 锁屏状态下的真实运行结果。
4. 微信退出、用户注销或小程序登录失效时无法自动重新登录。
5. 本项目没有验证码处理、预约提交或订单自动化能力。
6. 小程序 UI 结构变化可能导致读取失败，需要重新校准解析器。
