# 厦大体育健身房 H5 接口分析

分析日期：2026-11-02
目标小程序：厦大体育（`wx81a2b2fa90759cb7`，运行时版本 58）
目标场馆：翔安校区爱秋体育馆健身房（`stadium_id=16`，
`category_id=8`）

## 1. 证据等级

本文使用以下标记区分证据来源：

- **【源码确认】**：由 H5 页面或 `common.js` 的调用代码直接确认。
- **【实际验证】**：在 2026-11-02 通过独立只读 HTTP 请求观察到。
- **【推断】**：由字段名、页面渲染逻辑或同类接口推测，缺少有效登录态
  下的完整响应证明。

本次没有使用、提取或记录用户 Cookie，没有调用 `chooseVerify`、
`addOrder`，也没有尝试识别或绕过验证码。

## 2. 分析对象

已检查以下公开 H5 资源：

- `https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/public/static/js/common.js`
- `https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/view/stadium/detail.html`
- `https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/view/stadium/choose.html`
- `https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/view/stadium/confirm.html`

健身房详情页实际 URL：

```text
https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/view/stadium/detail.html?id=16&category_id=8
```

## 3. 公共请求封装

### 3.1 基础地址【源码确认】

```text
https://xdty.xmu.edu.cn/bdlp_h5_fitness_test/public/index.php
```

`common.js` 中的 `before_param_url` 保存该地址，业务请求最终拼接为：

```text
before_param_url + endpoint_path
```

### 3.2 请求方法和编码【源码确认】

`request()` 的默认参数为：

```text
postType = "POST"
```

页面将普通 JavaScript 对象作为 jQuery `$.ajax({data: ...})` 的 `data`
传入。jQuery 在这种情况下默认发送：

```http
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
```

源码没有为普通业务请求设置自定义 `Content-Type`。

### 3.3 响应信封【源码确认】

普通接口使用如下 JSON 信封：

```json
{
  "status": 1,
  "info": "提示文本",
  "data": {}
}
```

页面消费的状态：

| `status` | 页面行为 | 只读客户端处理 |
|---|---|---|
| `1` | 正常业务成功分支 | 解析 `data` |
| `0` | 显示 `info`；登录失效时跳转登录 | 若 `info` 含登录/失效语义，抛出认证异常；否则视为业务失败 |
| `-1` | 打开登录提示 | 抛出认证异常 |
| `-100` | 仅显示提示 | 视为非成功状态 |

注意：不同页面使用的成功判断不统一。详情页和选场页显式判断
`status == 1`；确认页多处只判断 `if (rs.status)`，因此不能仅根据
JavaScript 真值语义认定所有非零状态都代表成功。

### 3.4 身份认证链路【源码确认】

源码中存在两套请求模式：

1. 旧模式：依赖浏览器 Cookie 会话，页面代码不显式添加认证 Header。
2. 新模式：当 URL 中的客户端版本参数满足条件时，请求会额外加入：

```text
timestamp
h5_token
uid
```

其中 `h5_token` 由客户端 WebView bridge 的 `goToNativePage` 处理器返回；
源码没有给出可在 Python 中独立生成它的算法。

源码中出现的会话相关名称包括 `PHPSESSID`、`BJYSESSION`、
`COOKIE_IS_APP_UI` 和 `schoolKey`。本项目没有读取或保存这些值。

## 4. 接口详情

## 4.1 获取场馆详情

```http
POST /index/Stadium/getStadiumDetails
Content-Type: application/x-www-form-urlencoded
```

### 请求参数

| 字段 | 类型 | 必需 | 来源 |
|---|---|---:|---|
| `id` | 整数或可转成整数的字符串 | 是 | 页面查询参数 `id` |

健身房请求示例：

```text
id=16
```

### 响应

顶层信封中的 `status`、`info`、`data` 已由源码确认。

`data` 中页面直接消费的字段：

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `name` | 字符串 | 场馆名称 |
| `details` | 字符串 | 场馆简介 |
| `location` | 字符串 | 校区/位置 |
| `phone` | 字符串 | 联系电话 |
| `facilities` | 字符串 | 场地设施 |
| `services` | 字符串 | 场地服务 |
| `cover` | 字符串 | 封面 URL |
| `category_id` | 整数 | 当前项目分类 |
| `user_range` | 字符串或整数 | 后续 `getInterval` 所需范围参数 |
| `albums` | 字符串数组 | 相册资源 |
| `next_url` | 字符串 | 下一页路径，默认 `/stadium/choose.html` |
| `venue` | 数组 | 场馆项目和可选日期 |

`venue[]` 的页面消费字段：

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `category_id` | 整数 | 项目分类，用于匹配 `category_id=8` |
| `name` | 字符串 | 项目名称，如“健身房” |
| `list` | 数组 | 日期入口 |

`venue[].list[]` 的页面消费字段：

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `week` | 字符串 | 相对日期标签 |
| `date` | 字符串 | 显示日期 |
| `is_subscribe` | 整数 | 页面用 `0` 表示可进入选择页 |
| `venue_id` | 整数或数字字符串 | 下一接口的关键参数 |

### 实际验证

2026-11-02 对匿名客户端执行了一次：

```http
POST /index/Stadium/getStadiumDetails
Content-Type: application/x-www-form-urlencoded

id=16
```

响应头包含：

```text
HTTP/1.1 200 OK
Content-Type: application/json; charset=utf-8
```

响应体：

```json
{
  "status": 0,
  "info": "登录信息失效，请返回并重新进入",
  "data": []
}
```

该结果证明：

- 接口在无需登录时仍可到达，但业务层拒绝返回场馆数据。
- 业务失败可能使用 HTTP 200，不能只检查 HTTP 状态码。
- 当前匿名环境缺少服务端认可的登录会话。

由于没有有效授权会话，本次无法实际确认 `data` 内各字段的具体 JSON
类型；上表中的类型均来自 JavaScript 使用方式，标记为推断。

## 4.2 获取预约日期和时间段

```http
POST /stadium/interval/getInterval
Content-Type: application/x-www-form-urlencoded
```

### 请求参数

| 字段 | 类型【推断】 | 必需 | 来源 |
|---|---|---:|---|
| `venue_id` | 整数或数字字符串 | 是 | 场馆详情 `venue[].list[].venue_id` |
| `stadium_id` | 整数 | 是 | 当前健身房为 `16` |
| `user_range` | 字符串或整数 | 是 | 场馆详情 `data.user_range` |
| `category_id` | 整数 | 是 | 当前健身房为 `8` |

请求示例：

```text
venue_id=<详情接口返回>
stadium_id=16
user_range=<详情接口返回>
category_id=8
```

### 顶层响应字段

以下字段由 `choose.html` 的 Vue 初始化和赋值逻辑确认存在并被消费：

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `date_list` | 数组 | 日期标签 |
| `column_list` | 数组 | 场地列 |
| `time_slot_list` | 数组 | 按时间段分组的具体场次 |
| `personal_num` | 整数 | 个人预约容量 |
| `team_num` | 整数 | 包场容量 |
| `add_auth` | 布尔或整数 | 是否允许添加随行人员 |
| `venue_appointment_min_num` | 整数 | 最少预约人数限制，`0` 表示关闭 |
| `confirm_time` | 字符串 | 随行人员确认时限 |
| `neighbor` | 未知 | 页面保存但本分析未发现后续渲染用途 |
| `is_can_choose` | 整数 | 非 `0` 时允许选择场次 |
| `is_can_choose_tips` | 字符串 | 不允许选择时的提示 |

### `date_list[]`

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `week` | 字符串 | 星期或“今天”标签 |
| `date` | 字符串 | 用户界面日期 |
| `date_int` | 字符串 | 与 `time_slot_list[].date` 关联的日期键 |

### `column_list[]`

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `column_id` | 整数或字符串 | 场地唯一键 |
| `name` | 字符串 | 场地名称 |

### `time_slot_list[]`

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `date` | 字符串 | 与 `date_list[].date_int` 匹配 |
| `week` | 字符串 | 星期 |
| `week_name` | 字符串 | 相对日期名称 |
| `time_range` | 字符串 | 时间段，如 `18:00-19:00` |
| `slots` | 数组 | 该时间段内的场地状态 |

### `time_slot_list[].slots[]`

| 字段 | 类型【推断】 | 用途 |
|---|---|---|
| `column_id` | 整数或字符串 | 场地键，用于与 `column_list` 对应 |
| `area_name` | 字符串 | 场地名称 |
| `interval_id` | 整数或字符串 | 场次唯一键 |
| `price` | 数字或数字字符串 | 当前健身房显示免费时通常为 `0` |
| `status` | 枚举字符串 | 页面已处理 `available`、`unavailable`、`locked` |
| `selected` | 整数 | 当前已选/已预约人数 |
| `lock_reason` | 字符串 | 不可选或锁定原因 |

### 名额和开放状态

页面渲染：

```text
selected / personal_num
```

并在：

```text
selected >= personal_num
```

时将该场次标记为不可选。因此剩余名额可计算为：

```text
remaining_personal = max(personal_num - selected, 0)
remaining_team = max(team_num - selected, 0)
```

这是【推断】的派生值，不是响应中的原始字段。

只读原型还派生：

```text
is_open =
    is_can_choose != 0
    and status == "available"
    and remaining_personal > 0
```

其中 `is_open` 是本项目定义的统一布尔值，不是服务端字段。

### 实际验证状态

没有对 `getInterval` 发出未经授权的高频试参请求。由于
`getStadiumDetails` 在匿名状态下不返回 `venue_id` 和 `user_range`，
无法在不猜测参数的情况下构造一次有意义的 `getInterval` 调用。

因此：

- 参数名称和调用顺序：**【源码确认】**
- 响应字段被页面消费：**【源码确认】**
- 具体 JSON 类型和完整响应样例：**【推断/未验证】**
- 有效登录状态下的成功响应：**尚未验证**

## 4.3 校验选中场次

```http
POST /index/stadium/chooseVerify
Content-Type: application/x-www-form-urlencoded
```

请求参数：

| 字段 | 类型【源码调用方式】 | 说明 |
|---|---|---|
| `stadium_id` | 整数或字符串 | 健身房为 `16` |
| `selected` | JSON 字符串 | 选中场次对象数组 |
| `venue_id` | 整数或字符串 | 场馆项目 ID |
| `is_academy` | 整数 | `1` 个人预约，`2` 包场 |
| `ids` | 逗号分隔字符串 | 随行人员 ID，可为空 |

页面只判断响应 `status` 是否为真，不读取具体 `data` 结构。该接口已不在
只读原型中实现，因为它属于预约前校验流程。

## 4.4 获取场馆预约配置

```http
POST /index/Stadium/getVenueConfig
Content-Type: application/x-www-form-urlencoded
```

请求参数：

| 字段 | 类型【推断】 |
|---|---|
| `stadium_id` | 整数/字符串 |
| `venue_id` | 整数/字符串 |
| `category_id` | 整数/字符串 |

页面消费 `data.info`：

| 字段 | 页面判断 |
|---|---|
| `needRemark` | 等于 `1` 时要求备注 |
| `isCanAppoint` | 预约权限布尔值 |
| `isCanAppointMsg` | 禁止预约时的说明 |
| `phone` | 已绑定手机号 |
| `verify_phone` | 是否要求绑定手机号 |

成功响应只在 `status == 1` 时处理。有效登录响应尚未实际验证。

## 4.5 获取验证码

```http
GET /index/index/captcha
```

源码使用查询参数：

| 字段 | 类型【源码确认】 | 说明 |
|---|---|---|
| `r` | 数字字符串 | 随机数 |
| `t` | Unix 秒时间戳 | 请求时间 |
| `sign` | 十六进制 MD5 字符串 | 客户端生成的请求签名 |

源码生成的签名还把 `uid` 纳入计算。本项目不实现验证码请求、签名生成、
验证码识别或自动填写。

该接口返回图片，不是 JSON。`addOrder` 提交时需要用户输入验证码。

## 4.6 创建预约订单

```http
POST /index/Stadium/addOrder
Content-Type: application/x-www-form-urlencoded
```

页面提交字段：

| 字段 | 说明 |
|---|---|
| `stadium_id` | 场馆 ID |
| `venue_id` | 项目 ID |
| `stadium_name` | 场馆名称 |
| `project_name` | 项目名称 |
| `is_academy` | `1` 个人预约，`2` 包场 |
| `academy_name` | 学院/单位信息 |
| `mark` | 备注 |
| `details` | 选中场次 JSON 字符串 |
| `uids` | 随行人员 ID |
| `captcha` | 用户输入的验证码 |
| `category_id` | 分类 ID |
| `is_vip` | VIP/套餐卡标记 |
| `pay_type` | 非 VIP 时可能出现的支付方式 |
| `remark` | 场馆要求备注时的说明 |

该接口会创建真实订单，本阶段明确未调用。

## 5. 调用关系

```text
detail.html
  -> POST /index/Stadium/getStadiumDetails
       -> 取得 name/location/user_range/venue[].list[].venue_id

choose.html
  -> POST /stadium/interval/getInterval
       -> 取得日期、场地列、时段和名额
  -> 可选 POST /index/stadium/check_add_auth
       -> 添加随行人员
  -> POST /index/stadium/chooseVerify
       -> 预约前场次校验

confirm.html
  -> POST /index/Stadium/getVenueConfig
       -> 预约限制和手机号要求
  -> GET /index/index/captcha
       -> 验证码图片
  -> POST /index/Stadium/addOrder
       -> 创建真实预约订单
```

只读原型只实现：

```text
getStadiumDetails -> getInterval
```

## 6. 独立后台程序成立条件

当前能够确认“有可调用的 HTTP 接口”，但不能确认“这些接口被正式允许
作为第三方独立 API 使用”。

若获得学校或系统维护方授权，独立程序还需要：

1. 经批准的认证适配器，例如 OAuth、短期 API Token 或校方签发的
   客户端证书。
2. 明确的会话刷新方式和有效期。
3. 对接口版本变化、限流和故障恢复的服务承诺。
4. 数据使用、保存和日志脱敏要求。
5. 若涉及自动预约，还要有官方支持的验证码/人工确认流程。

在没有上述条件时，本项目只保留只读框架，不重放本地 Cookie，不绕过
登录、动态签名、验证码或访问控制。
