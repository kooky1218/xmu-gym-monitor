# 厦大体育健身房认证依赖诊断报告

> 历史说明：本文记录 2026-11-02 的独立 HTTP 方案。该方案无法复用微信
> 小程序登录态；2026-11-05 的生产 reader 已改为只读 UI Automation，
> 当前结论请以 `BACKGROUND_FEASIBILITY.md` 和 `DATA_SOURCE_REPORT.md` 为准。

测试日期：2026-11-02
目标场馆：翔安校区爱秋体育馆健身房
目标参数：`stadium_id=16`，`category_id=8`
目标预约日期：2026-11-03（诊断元数据，不是 `getInterval` 请求字段）

## 1. 测试目标

本阶段只验证认证依赖和数据来源，不测试预约提交。

每个场景运行同一个命令：

```powershell
.\.venv\Scripts\python.exe -m tools.run_auth_diagnostic `
  --scenario <A|B|C|D> `
  --target-date 2026-11-03 `
  --output "logs\auth_diagnostic.jsonl"
```

诊断脚本：

- 不配置认证适配器；
- 不读取微信 Cookie、Token 或密码；
- 不读取本地缓存；
- 只调用 `getStadiumDetails` 和后续只读读取链路；
- 若详情接口认证失败，就停止，不构造 `getInterval` 参数；
- 将每次结果追加到 `logs/auth_diagnostic.jsonl`。

由于当前执行环境注入了不可用的 `127.0.0.1:9` 代理变量，诊断脚本
显式使用 `trust_env=False`，避免把本地代理故障误判为认证故障。

## 2. 场景与结果

### A. 微信已登录并保持窗口显示

运行时间：2026-11-02 11:28:03
执行方式：Python 诊断脚本直接运行

观察条件：

- `Weixin.exe` 进程数量：5；
- `WeChatAppEx.exe` 进程数量：14；
- 同时通过 Windows UI 自动化确认微信主窗口被激活；
- 原始记录中还包含一个由 WebView 创建、处于最小化状态的“微信”窗口；
  主窗口本身的记录为 `Weixin.exe / visible=true / minimized=false`。

请求结果：

```text
HTTP status:       200
business status:   0
request_success:   true
parse_success:     false
data_source:       unknown
error_type:        authentication_required
message:           登录信息失效，请返回并重新进入
```

结论：Python 请求即使和已登录微信同时运行，也没有取得数据。

### B. 微信已登录但窗口最小化

运行时间：2026-11-02 11:31:03
执行方式：Python 诊断脚本直接运行

观察条件：

- `Weixin.exe` 进程数量：5；
- `WeChatAppEx.exe` 进程数量：8；
- 微信主窗口：`visible=true / minimized=true`；
- 微信没有退出。

请求结果：

```text
HTTP status:       200
business status:   0
request_success:   true
parse_success:     false
data_source:       unknown
error_type:        authentication_required
message:           登录信息失效，请返回并重新进入
```

结论：最小化不会改变 Python 请求结果。

### C. 微信完全退出

运行时间：2026-11-02 11:30:00
执行方式：终止当前 `Weixin.exe` 和 `WeChatAppEx.exe` 后运行诊断脚本

观察条件：

```text
wechat_process_count: 0
wechat_appex_count:   0
wechat_windows:       []
```

请求结果：

```text
HTTP status:       200
business status:   0
request_success:   true
parse_success:     false
data_source:       unknown
error_type:        authentication_required
message:           登录信息失效，请返回并重新进入
```

结论：退出微信前后结果相同。当前 Python reader 没有从微信进程继承了任何
可用认证状态，因此微信是否运行不是当前失败差异的原因。

测试后已重新启动微信。

### D. Windows 锁屏，由任务计划程序执行

计划任务：

```text
TaskName: XMU_Gym_ReadOnly_Diag
RunAsUser: <current-user>
LogonMode: Interactive only
Task: tools/run_auth_diagnostic_task.cmd
```

运行时间：2026-11-02 11:32:10
执行方式：锁屏后使用 `schtasks /Run` 触发

锁屏/运行观察：

```text
workstation_locked: true
logon_ui_running:   true
wechat_process_count: 5
wechat_appex_count:   8
wechat main window:   minimized=true
Task Scheduler result: 0
```

请求结果：

```text
HTTP status:       200
business status:   0
request_success:   true
parse_success:     false
data_source:       unknown
error_type:        authentication_required
message:           登录信息失效，请返回并重新进入
```

结论：任务计划程序可以在锁屏时执行 Python 只读脚本，但当前脚本仍然无法
获得认证，因此不能无人值守读取真实数据。

测试完成后已删除临时计划任务，避免其在预定的 23:59 再次执行。

## 3. 汇总

| 场景 | 微信状态 | 锁屏 | HTTP | 业务状态 | 数据来源 | 认证结果 |
|---|---|---|---:|---:|---|---|
| A | 进程运行，主窗口显示 | 否 | 200 | 0 | unknown | 失败 |
| B | 进程运行，主窗口最小化 | 否 | 200 | 0 | unknown | 失败 |
| C | 进程完全退出 | 否 | 200 | 0 | unknown | 失败 |
| D | 进程运行，计划任务执行 | 是 | 200 | 0 | unknown | 失败 |

四组结果完全一致。

## 4. 对认证链路的解释

当前代码并没有从微信进程读取登录状态：

1. `NoAuthentication.configure()` 是空操作。
2. `requests.Session()` 使用自己的 Cookie 容器，默认容器为空。
3. Python 进程和微信 WebView 进程之间没有共享内存、浏览器容器或认证
   bridge。
4. 因此调用服务端时，服务端看到的是一个全新的匿名 HTTP 客户端。
5. 微信正在运行、最小化或退出都不会改变 Python 自己的会话。

这解释了为什么 A、B、C 的结果相同。

实际获取授权的路径只能是：

- 校方提供正式 Bearer Token、OAuth、客户端证书或服务账号；
- 由授权方定义可安全保存和刷新的会话；
- 或者继续在微信 H5 内使用，不建设脱离微信的自动读取服务。

不能把“复用微信本地 Cookie”作为正式方案，本阶段也没有执行该操作。

## 5. 实验限制

- 场景 A 的旧版汇总字段把 WeChatAppEx 的窗口也计入“微信窗口”；主窗口
  状态以同次窗口明细中的 `Weixin.exe` 记录为准。
- 没有有效授权会话，所以四组场景都在 `getStadiumDetails` 阶段终止，
  没有实际验证有效登录后的 `getInterval` 成功数据。
- 锁屏期间无法可靠通过 UI 自动化检查画面，使用了 `LogonUI.exe` 与桌面
  状态联合判定，且任务结果与诊断 JSON 均成功落盘。
