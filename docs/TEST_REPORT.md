# 小程序只读监控测试报告

测试日期：2026-11-05

## 1. 测试原则

- 只读取“厦大体育”小程序可访问页面文字。
- 不导出、记录或重放微信 Cookie、Token、密码。
- 不处理验证码。
- 不调用 `chooseVerify` 或 `addOrder`。
- 不点击“确认预约”、支付或任何订单按钮。
- 低频运行，计划间隔为 5 分钟。

## 2. 自动测试

执行命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

结果：

```text
Ran 82 tests
OK
```

覆盖内容包括：

- 场馆详情和选场页文本解析；
- “暂无 / 预定”日期级状态；
- 自动点击“预定”进入选场页；
- 逐个日期切换并解析 `HH:MM-HH:MM` 时间段；
- `mini_program_live` 来源；
- UI Automation 桥输出和窗口不存在错误；
- 首页 → 场馆预约 → 翔安校区健身房自动导航；
- 登录失效识别；
- 日期级开放不虚构剩余名额；
- 选择场次页 `selected/capacity` 解析；
- 正式空位通知去重和冷却；
- 手动刷新直接触发 Bark 空位通知；
- 缓存不触发正式通知；
- Bark 测试；
- Bark 通知不携带 URL；
- PySide6 离屏冒烟测试。

## 3. 真实小程序只读扫描

运行时间：2026-11-05 18:24:40

结果：

```json
{
  "ok": true,
  "data_source": "mini_program_live",
  "page_kind": "detail",
  "venue": "翔安校区健身房",
  "dates": [
    {
      "date": "2026-11-05",
      "action_text": "暂无",
      "is_open": false
    },
    {
      "date": "2026-11-06",
      "action_text": "暂无",
      "is_open": false
    }
  ],
  "parse_success": true
}
```

HTML 源码确认“暂无 / 预定”来自 `is_subscribe` 条件；本次没有点击任何无法
预约的日期，也没有尝试构造订单。

## 4. 桌面界面刷新

启动桌面界面并触发“刷新数据”后，界面实际显示：

```text
读取成功（小程序实时页面）
校区：翔安校区
场馆：翔安校区健身房
数据来源：小程序实时页面（mini_program_live）
页面：detail / UI desktop_uia_bridge
日期：2026-11-05、2026-11-06
开放状态：暂无预约
```

刷新按钮会新建工作线程，真实调用 `MiniProgramStadiumReader`，不是读取模拟
数据，也不是只显示缓存。

### 2026-11-06 当前页面复核

```text
场馆：翔安校区健身房
日期：11月06日（今天）、11月07日（周六）
状态：两天均为“暂无”
可预约时间段：当前没有
```

因此界面不会虚构具体时间。出现“预定”后，新逻辑会自动进入选场页，读取
`时间段 / 已选人数 / 容量 / 剩余名额 / 开放状态`；多个日期会逐个切换读取。

### 最小化读取

2026-11-06 14:40:35 将“厦大体育”最小化后执行只读扫描：

```text
结果：ok=true
来源：mini_program_live
日期：2026-11-06、2026-11-07
解析：成功
读取后窗口状态：仍为最小化
```

### 锁屏读取

2026-11-06 17:27:59 执行真实 Windows 锁屏测试。读取前后均为：

```text
workstation_locked=true
logon_ui_running=true
"厦大体育"窗口：最小化
reader_exit_code=0
data_source=mini_program_live
parse_success=true
```

成功读取 2026-11-06 和 2026-11-07。只要 Windows 用户仍处于登录会话且电脑
没有睡眠，锁屏不会阻止 UI Automation 读取。

## 5. 后台单次任务

结果：

```json
{
  "exit_code": 0,
  "status": "NO_NEW_AVAILABILITY",
  "error_type": null,
  "message": null,
  "data_source": "mini_program_live",
  "matched_count": 2,
  "notification_count": 0
}
```

解释：

- 后台成功读取真实页面；
- 匹配当前可见两个日期；
- 两个日期均不可预约；
- 没有发送空位通知。

## 6. 后台运行方式

Windows 计划任务曾成功创建并手动返回码 `0`：

```text
XMU Gym Monitor
LogonType = InteractiveToken
RunLevel = LeastPrivilege
MultipleInstancesPolicy = IgnoreNew
```

但这台机器会在管理员重新启用后很快把任务状态改回 `Disabled`。为避免
“显示已安装但实际不会定时运行”，旧任务已删除，改用启动文件夹常驻进程：

```text
Startup\厦大健身房空位监控.lnk
  -> tools\LaunchMonitorDaemon.exe
  -> pythonw.exe app.py --daemon
```

实测守护进程已启动，首轮返回：

```text
NO_NEW_AVAILABILITY
exit_code=0
matched=2
notified=0
```

第二轮在 5 分钟后自动执行并被日志记录：

```text
2026-11-05 18:39:49 | NO_NEW_AVAILABILITY
matched=2 notified=0
```

守护进程持有 `data/monitor.lock` 单实例锁，每 5 分钟重新加载配置并执行
一次只读检查。GUI 与后台并发访问 UIA 桥时，还会通过
`data/miniprogram_bridge.lock` 串行化。

## 7. Bark

Windows Credential Manager 中已存在 Bark Key。测试过程只检查
“configured/missing”，没有读取、打印或落盘 Key。

本次因为没有可预约日期，没有发送正式空位通知。

## 8. 未完成或需持续观察

1. 睡眠或休眠会暂停进程，当前版本不能在睡眠期间监控或提醒。
2. 尚未观察到真实“预定”页面，因此选场页解析只有合成固定数据测试。
3. 小程序登录失效后的自动恢复，目前是下一轮任务重试加 Bark 异常提醒，
   不是自动输入账号密码。
4. 微信 UI 结构升级后可能需要重新校准控件选择器和解析规则。
