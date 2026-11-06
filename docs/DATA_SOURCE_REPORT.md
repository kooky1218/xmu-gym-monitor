# 数据来源与执行路径报告

更新日期：2026-11-05

## 1. 当前实际读取链路

当前生产读取不再使用独立 Chrome 登录，也不重放微信 Cookie。实际链路为：

```text
PySide6 刷新 / Windows 计划任务
  -> MiniProgramStadiumReader.read_gym_snapshot()
  -> MiniProgramUiReader.capture()
  -> MiniProgramUiBridge.exe
  -> Windows UI Automation
  -> 厦大体育小程序可访问文本
  -> parse_detail_dates() / parse_choose_slots()
  -> SnapshotCache.save()
  -> 表格展示或 AvailabilityMonitor
  -> Bark 通知
```

桥程序只读取可访问文本，不读取微信进程内存，不导出 Cookie、Token、密码，
也不解密网络流量。

## 2. 页面状态如何解释

场馆详情页源码使用：

```text
is_subscribe == 0 -> “预定”
is_subscribe != 0 -> “暂无”
```

因此当前解析器把“预定”解释为日期级预约入口开放，把“暂无”解释为当前
不提供预约入口。

必须区分：

| 状态 | 能确认的事实 | 不能确认的事实 |
|---|---|---|
| 日期显示“预定” | 该日期可以进入选场流程 | 某个具体时段一定有余量 |
| 选场格显示 `3/95` | 该可见格至少显示 92 个名额差 | 未显示锁定原因时仍不能推断后台最终名额 |
| 日期显示“暂无” | 当前详情页没有预约入口 | 不需要继续尝试提交订单 |

日期出现“预定”后，reader 会自动进入选场页，逐个日期读取时间段和容量分数。
只有选场页无法解析时才退回日期级通知，正文明确写“预约入口开放”，不会写
“剩余 1 个名额”。

## 3. 实际数据来源标记

成功读取小程序页面时：

```json
{
  "data_source": "mini_program_live",
  "request_success": true,
  "parse_success": true,
  "http_status": null,
  "business_status": null,
  "ui_source": "desktop_uia_bridge",
  "page_kind": "detail"
}
```

历史快照加载后改为：

```json
{
  "data_source": "cache",
  "cache_age": 123
}
```

`mini_program_live` 与原来的 `network_live` 都允许触发正式空位变更检查；
`cache`、`mock`、`unknown` 永远不会触发正式空位通知。

## 4. 缓存与失败回退

缓存由 `SnapshotCache` 原子写入，不保存任何认证材料。

- 成功读取后保存最新页面状态。
- 读取失败时 GUI 可以显示历史快照。
- 历史快照使用橙色表格，并显示原始获取时间和缓存年龄。
- 没有缓存时清空表格，不保留旧结果冒充实时数据。
- 后台监控不会把缓存送入 `ChangeDetector` 的正式通知分支。

## 5. 当前真实测试结果

2026-11-05 18:24:40 在交互桌面运行完整读取：

```text
data_source = mini_program_live
page_kind = detail
venue = 翔安校区健身房
dates = 2026-11-05, 2026-11-06
states = 暂无预约, 暂无预约
parse_success = true
```

2026-11-05 通过桌面刷新按钮再次读取：

```text
读取成功（小程序实时页面）
来源：mini_program_live
页面：detail
界面：desktop_uia_bridge
```

后台单次任务：

```json
{
  "exit_code": 0,
  "status": "NO_NEW_AVAILABILITY",
  "data_source": "mini_program_live",
  "matched_count": 2,
  "notification_count": 0
}
```

## 6. 认证依赖

读取依赖：

1. Windows 当前用户已登录。
2. Windows 微信进程仍在运行。
3. “厦大体育”小程序窗口存在。
4. 小程序内部登录态仍有效。

不依赖：

- Chrome 或 Edge 独立登录；
- 从微信复制 Cookie；
- 导出或重放动态签名；
- 自动识别验证码。

如果小程序窗口关闭、微信退出、Windows 用户注销或小程序登录失效，读取会
失败。计划任务会在后续轮次继续尝试；用户重新登录后可以自动恢复读取，
但程序不会保存账号密码，也不会替用户重新登录。
