# iPhone Bark 通知配置

更新时间：2026-11-05

## 1. 安装 Bark

在 iPhone App Store 安装 Bark。

打开 Bark 后：

1. 允许通知权限。
2. 复制 App 提供的第一段设备 Key。
3. 不要把 Key 发到公开群聊或提交到 Git。

默认 Bark 服务：

```text
https://api.day.app
```

如果使用自建 Bark Server，可在监控设置里修改服务地址。

## 2. 在项目中保存 Key

启动：

```powershell
.\.venv\Scripts\python.exe app.py
```

打开“监控设置 → Bark 通知”：

1. 服务地址保持 `https://api.day.app`，或填写自建服务地址。
2. 输入 Bark 设备 Key。
3. 点击“发送测试通知”。
4. 收到通知后点击“保存配置”。

Key 保存到 Windows Credential Manager：

```text
服务名：xmuty-gym-monitor
账户名：bark-device-key
```

普通 JSON、SQLite 和日志均不保存 Bark Key。

重新打开设置时，Key 输入框会保持为空。留空并保存不会覆盖已有 Key。

## 3. 测试通知

命令行测试：

```powershell
.\.venv\Scripts\python.exe app.py --send-test-notification
```

模拟空位通知：

```powershell
.\.venv\Scripts\python.exe app.py --simulate-notification
```

模拟通知标题带 `【测试】`，正文明确说明不是实际空位。

## 4. Bark 接口

项目使用 Bark Server V2 官方 POST 接口：

```text
POST /push
```

请求字段：

```json
{
  "device_key": "<从 Credential Manager 读取>",
  "title": "翔安健身房发现空位",
  "body": "场馆、日期、时段和剩余名额",
  "group": "厦大体育空位监控"
}
```

正式空位通知、系统异常通知和 Bark 测试通知均不附带跳转链接。

官方文档：

- <https://github.com/Finb/bark-server/blob/master/docs/API_V2.md>
- <https://github.com/Finb/Bark>

## 5. 重试行为

- 网络错误、HTTP 5xx：有限指数重试。
- HTTP 429：优先读取 `Retry-After`，否则指数退避。
- HTTP 4xx：不重试。
- 相同内容在短时间去重，避免重复推送。
- 正式场次不会因持续存在而重复提醒，状态由 SQLite 保存。

## 6. 修改或删除 Key

在监控设置里输入新 Key 并保存即可覆盖。

也可以通过 Windows Credential Manager 删除：

```text
Windows 控制面板 → 凭据管理器 → Windows 凭据
```

查找 `xmuty-gym-monitor`。

## 7. 安全说明

- 不将 Bark Key 写入代码。
- 不将 Bark Key 写入 `monitor_config.json`。
- 不记录 HTTP 请求头、设备 Key 或完整请求正文。
- 通知正文不包含账号、Cookie 或 Token。
