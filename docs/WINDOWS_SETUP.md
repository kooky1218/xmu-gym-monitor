# Windows 后台部署说明

更新时间：2026-11-05

## 1. 安装依赖

```powershell
cd D:\Codex++\data\2026-11-02\x20\outputs\xmuty-gym-reader
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. 配置

启动 GUI：

```powershell
.\.venv\Scripts\python.exe app.py
```

打开“监控设置”，设置日期、时段、检查间隔和 Bark Key。日期和时段列表
留空时，分别表示当前可见全部日期和整个日期。

确认 `config\monitor_config.json` 中：

```json
"enabled": true
```

运行前确认 Windows 微信已登录，并让“厦大体育”小程序窗口保持存在。程序
只通过 UI Automation 读取页面，不读取微信 Cookie。

## 3. 登录后自动运行（当前推荐）

本项目已安装用户启动项：

```text
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
  厦大健身房空位监控.lnk
    -> tools\LaunchMonitorDaemon.exe
    -> pythonw.exe app.py --daemon
```

下次登录 Windows 后会自动启动。现在也可以双击项目根目录：

```text
启动后台监控.lnk
```

守护进程行为：

- 持有 `data/monitor.lock` 单实例锁；
- 每 5 分钟重新加载配置并执行一次只读检查；
- GUI 与后台通过 `data/miniprogram_bridge.lock` 串行访问 UIA；
- 某一轮失败后继续等待下一轮；
- 微信退出或小程序登录失效时无法读取，但不会崩溃或误报空位。

项目还提供前台界面：

```text
启动小程序监控.lnk
  -> tools\LaunchGymMonitor.exe
  -> pythonw.exe app.py
```

## 4. Windows 任务计划程序（备用）

默认每 5 分钟执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_scheduler.ps1
```

指定开始时间和间隔：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_scheduler.ps1 `
  -TaskName "XMU Gym Monitor" `
  -StartAt "2026-11-05 22:00" `
  -IntervalMinutes 5
```

登录时启动并以 5 分钟间隔重复：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_scheduler.ps1 `
  -AtLogon
```

启用 WakeToRun：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_scheduler.ps1 `
  -WakeToRun
```

安装器：

- 使用当前 Windows 用户；
- 使用最低权限；
- 设置 `MultipleInstancesPolicy=IgnoreNew`；
- 任务窗口隐藏；
- 通过 `pythonw.exe` 运行；
- 最多运行 15 分钟；
- 使用交互式用户令牌，因此锁屏时仍可运行；
- 需要用户已登录，不适用于用户注销后的无人值守。

本机实测中，任务可手动执行且返回码为 `0`，但 Windows 会在管理员重新启用
后很快把任务状态改回 `Disabled`。因此当前生产入口使用第 3 节的启动文件夹
守护进程，任务计划程序脚本保留为备用。

如果当前账号无权创建任务，`schtasks.exe` 会返回权限错误。本机实际安装时
使用管理员 PowerShell 注册当前用户的 `InteractiveToken` 任务。任务本身仍
以最低权限运行。

只验证 XML 生成、不实际注册任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\install_scheduler.ps1 `
  -AtLogon `
  -WakeToRun `
  -DryRun
```

## 5. 卸载计划任务

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\uninstall_scheduler.ps1
```

指定名称：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\uninstall_scheduler.ps1 `
  -TaskName "XMU Gym Monitor"
```

## 6. 手动运行

```powershell
.\scripts\run_monitor_once.cmd
```

或：

```powershell
.\.venv\Scripts\python.exe app.py --run-once
```

日志：

```text
logs/monitor.log
```

单次任务会记录以下退出码：

| 退出码 | 含义 |
|---:|---|
| `0` | 正常 |
| `2` | 需要认证 |
| `3` | 另一个实例正在运行 |
| `4` | 配置错误 |
| `5` | 读取失败 |
| `6` | 通知失败 |

## 7. 锁屏、睡眠、休眠和关机

| 状态 | 任务是否可运行 | 说明 |
|---|---|---|
| 已登录且锁屏 | 理论上可以 | 常驻进程属于交互会话；UIA 实际行为尚未实测 |
| 已登录但睡眠 | 不会 | 常驻进程会被系统挂起 |
| 休眠 | 不会 | 恢复后可继续等待下一轮，但休眠期间不能监控 |
| 用户注销 | 不会 | 启动项只在用户登录后运行 |
| 关机 | 不会 | 需要开机并登录 |
| 重启后未登录 | 不会 | 登录 Windows 后由启动文件夹拉起 |

WakeToRun 只向系统发出唤醒请求：

- 不是所有电脑都支持；
- 不能从完全关机状态启动；
- 可能唤醒整台电脑；
- 网络连接需要额外时间；
- 唤醒后仍可能因认证失效而无法读取。

如果需要关机后持续监控，应使用常开的 Windows 主机、NAS、云服务器或学校
提供的正式 API 服务，而不是依赖本机任务计划程序。

## 8. 并发与恢复

- 守护进程通过 `data/monitor.lock` 保证单实例。
- GUI 与后台通过 `data/miniprogram_bridge.lock` 串行访问 UIA。
- 桌面端和后台任务都通过 `MiniProgramUiBridge.exe` 读取可访问文本。
- 小程序窗口不存在时本轮失败，下一轮检查继续尝试。
- 登录失效时停止空位通知并进入冷却后的异常提醒。
- 所有运行记录写入 SQLite。

## 9. UI Automation 错误

如果看到：

```text
未找到“厦大体育”小程序窗口，请先打开并保持登录
```

请先确认：

- `WeChatAppEx.exe` 的“厦大体育”窗口存在；
- 窗口没有被微信彻底移除；
- 小程序仍处于登录状态。

如果提示“没有可读取的控件文本”，通常是微信页面还没加载完或小程序 UI
结构升级。下一轮会重试，但持续失败时需要更新 `MiniProgramUiBridge.exe`
和页面解析器。
