# TG Client 项目完整技术文档

> 本文档整理自开发过程中的全部历史对话和代码实现，供新 Session 参考。

---

## 一、项目概览

### 1.1 项目组成

| 项目 | 技术栈 | 功能 |
|------|--------|------|
| **tg-client-bg** | Java 17 + Spring Boot + MyBatis + MySQL | 后台管理系统（前端+API+数据库管理） |
| **tg-client-telethon** | Python 3.10 + Telethon + FastAPI + aiomysql | Telegram 客户端服务（账号管理、消息收发、自动回复） |
| **前端** | Vue.js (RuoYi框架) | 后台管理界面 |

### 1.2 服务器部署

| 套 | 外网IP | 内网IP | 用途 |
|----|--------|--------|------|
| 第一套 | 43.163.95.234 | 172.22.0.43 | 主服务（含自动回复API） |
| 第二套 | 43.134.24.173 | 172.22.16.11 | 副服务 |

### 1.3 端口分配

| 端口 | 服务 |
|------|------|
| 80 | Nginx（前端 + API反代 + 静态文件） |
| 8807 | tg-client-telethon (FastAPI) |
| 8809 | tg-client-bg (Java后端) |
| 8000 | 自动回复AI API（仅第一套） |
| 3306 | MySQL 5.7（Docker） |
| 6379 | Redis |

### 1.4 目录结构

```
/home/ubuntu/telegram-project/
├── tg-client-bg/               # Java后台
│   ├── bin/                    # 启动/停止脚本
│   │   ├── startup.sh
│   │   └── shutdown.sh
│   ├── ruoyi-admin/           # SpringBoot主模块
│   └── ruoyi-system/          # 业务模块
├── tg-client-telethon/         # Python Telethon服务
│   ├── main.py                # FastAPI入口
│   ├── client_manager.py      # 账号登录/登出管理
│   ├── auto_reply.py          # 自动回复核心逻辑
│   ├── contact_adder.py       # 添加好友模块
│   ├── data_collector.py      # 数据同步（联系人+聊天记录）
│   ├── database.py            # 数据库操作层
│   ├── config.py              # 配置文件
│   ├── notify.py              # TG Bot通知
│   ├── ws_handler.py          # WebSocket处理
│   ├── auth.py                # JWT认证
│   ├── phone_country.py       # 手机号归属国判断
│   ├── account/               # 账号文件（.session + .json）
│   ├── sessions/              # Telethon session文件
│   ├── logs/                  # 日志目录
│   └── bin/
│       └── restart.sh         # 完全重启脚本
├── ruoyi-ui/                   # 前端项目（Vue.js）
└── uploadPath/                 # 文件上传目录
```

---

## 二、数据库设计

### 2.1 数据库信息

- **数据库类型**: MySQL 5.7 (Docker)
- **数据库名**: `tg-client-server`
- **用户**: root
- **密码**: XkOVjlR6FvmONtLi75BS
- **字符集**: utf8mb4

### 2.2 核心业务表

#### tg_telethon_account（Telethon账号表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| phone | VARCHAR(32) UNIQUE | 手机号 |
| api_id | INT | Telegram API ID |
| api_hash | VARCHAR(64) | Telegram API Hash |
| tg_user_id | BIGINT | Telegram用户ID |
| nickname | VARCHAR(128) | 昵称(firstName + lastName) |
| username | VARCHAR(64) | 用户名 |
| country | VARCHAR(100) | 手机号归属国 |
| device_model | VARCHAR(200) | 设备型号 |
| system_version | VARCHAR(100) | 系统版本 |
| app_version | VARCHAR(100) | APP版本 |
| lang_code | VARCHAR(20) | 语言代码 |
| system_lang_code | VARCHAR(20) | 系统语言代码 |
| batch_no | VARCHAR(64) | 导入批次号 |
| status | VARCHAR(20) | 状态: online/offline/banned/restricted/failed |
| last_login_time | DATETIME | 最后登录时间 |
| is_deleted | TINYINT(1) | 是否已删除 |
| proxy_ip_id | INT | 代理IP的ID |
| proxy_group_no | VARCHAR(64) | 代理IP组号 |
| proxy_url | VARCHAR(500) | 完整代理URL |
| proxy_protocol | VARCHAR(10) | 代理协议(socks5/http) |
| proxy_host | VARCHAR(200) | 代理地址 |
| proxy_port | INT | 代理端口 |
| proxy_username | VARCHAR(200) | 代理认证用户名 |
| proxy_password | VARCHAR(200) | 代理认证密码 |
| auto_reply | TINYINT(1) DEFAULT 1 | 是否开启自动回复 |
| is_restricted | TINYINT(1) DEFAULT 0 | 是否被限制 |
| total_msg_count | INT DEFAULT 0 | 消息总数 |
| sent_msg_count | INT DEFAULT 0 | 发送总数 |
| recv_msg_count | INT DEFAULT 0 | 接收总数 |
| create_time | DATETIME | 创建时间 |
| update_time | DATETIME | 更新时间 |

#### tg_contact（好友/联系人表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| tg_account_id | INT | 所属账号ID |
| user_id | BIGINT | 好友的Telegram用户ID |
| first_name | VARCHAR(255) | 名 |
| last_name | VARCHAR(255) | 姓 |
| nickname | VARCHAR(255) | 昵称 |
| username | VARCHAR(255) | 用户名 |
| phone_number | VARCHAR(50) | 手机号 |
| is_mutual | TINYINT(1) | 是否互为好友 |
| is_bot | TINYINT(1) | 是否机器人 |
| is_premium | TINYINT(1) | 是否Premium用户 |
| last_online_time | DATETIME | 最后在线时间 |
| last_send_time | DATETIME | 最后发送时间（账号→好友） |
| last_receive_time | DATETIME | 最后接收时间（好友→账号） |
| auto_reply | TINYINT(1) DEFAULT 1 | 是否开启自动回复 |
| source | VARCHAR(20) | 来源: import(后台导入) / natural(自然) |
| total_msg_count | INT DEFAULT 0 | 消息总数 |
| account_sent_count | INT DEFAULT 0 | 账号发送数 |
| friend_sent_count | INT DEFAULT 0 | 好友发送数 |
| create_time | DATETIME | 创建时间 |
| update_time | DATETIME | 更新时间 |

**索引**: UNIQUE(tg_account_id, user_id)

#### tg_chat_message（聊天记录表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO_INCREMENT | 主键 |
| tg_account_id | INT | 所属账号ID |
| chat_id | BIGINT | 对话用户的Telegram ID |
| message_id | BIGINT | Telegram消息ID |
| sender_user_id | BIGINT | 发送者用户ID |
| is_outgoing | TINYINT(1) | 是否为账号发出的消息 |
| send_time | DATETIME | 发送时间 |
| content_type | VARCHAR(50) | 内容类型: text/photo/video/voice/document等 |
| text_content | TEXT | 文字内容或媒体描述 |
| media_file_id | BIGINT | 媒体文件ID |
| media_file_size | BIGINT | 媒体文件大小 |
| media_mime_type | VARCHAR(100) | MIME类型 |
| create_time | DATETIME | 创建时间 |

**索引**: UNIQUE(tg_account_id, chat_id, message_id)

#### tg_auto_reply_log（自动回复日志表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | BIGINT AUTO_INCREMENT | 主键 |
| account_phone | VARCHAR(50) | 账号手机号 |
| account_nickname | VARCHAR(100) | 账号TG ID |
| friend_user_id | BIGINT | 好友TG用户ID |
| friend_nickname | VARCHAR(100) | 好友TG ID |
| friend_phone | VARCHAR(50) | 好友手机号 |
| trigger_type | VARCHAR(20) | 触发类型: incoming/polling |
| state | INT | 请求state值(0-8) |
| request_params | TEXT | 请求参数(JSON) |
| chat_context | TEXT | 聊天上下文 |
| reply_content | TEXT | 获取到的自动回复内容 |
| send_result | VARCHAR(20) | 发送结果: success/failed/no_reply/api_error |
| error_reason | TEXT | 错误原因 |
| create_time | DATETIME | 记录时间 |

#### tg_greeting（广告问候语表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| title | VARCHAR(200) | 标题 |
| content | TEXT | 问候语内容 |
| image_path | VARCHAR(500) | 图片路径（可选） |
| is_enabled | TINYINT(1) DEFAULT 1 | 是否启用 |
| sort_order | INT DEFAULT 0 | 排序 |
| remark | VARCHAR(500) | 备注 |

**用途**: 好友给账号发的第一条消息时，回复广告问候语（state=0 且好友消息数<=1）

#### tg_opening（主动开场白表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| content | TEXT | 开场白内容（纯文本） |
| is_enabled | TINYINT(1) DEFAULT 1 | 是否启用 |
| sort_order | INT DEFAULT 0 | 排序 |
| remark | VARCHAR(500) | 备注 |

**用途**: state=1 时随机获取一条启用的开场白发送

#### tg_proxy_ip（代理IP表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| group_no | VARCHAR(64) | 组号 |
| protocol | VARCHAR(20) | 协议: socks5/socks4/http |
| host | VARCHAR(256) | 代理地址 |
| port | INT | 代理端口 |
| username | VARCHAR(256) | 认证用户名 |
| password | VARCHAR(256) | 认证密码 |
| proxy_url | VARCHAR(512) | 完整代理URL |
| max_bindable | INT DEFAULT 1 | 最大可绑定账号数 |
| current_bind_count | INT DEFAULT 0 | 当前绑定数 |
| status | VARCHAR(20) DEFAULT 'active' | 状态 |

#### tg_send_fail_log（发送失败日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| phone | VARCHAR(32) | 账号手机号 |
| tg_account_id | INT | 账号ID |
| user_id | BIGINT | 好友user_id |
| content_type | VARCHAR(32) | 内容类型 |
| content | TEXT | 发送内容 |
| error_reason | VARCHAR(512) | 错误原因 |
| send_time | DATETIME | 发送时间 |

#### tg_login_log（登录日志）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| phone | VARCHAR(32) | 手机号 |
| result | VARCHAR(20) | 结果: success/failed/banned/logout |
| reason | VARCHAR(512) | 原因 |
| tg_user_id | BIGINT | TG用户ID |
| proxy_info | VARCHAR(500) | 代理信息 |
| login_time | DATETIME | 登录时间 |

#### tg_import_batch（账号导入批次表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| batch_no | VARCHAR(64) UNIQUE | 批次号 |
| title | VARCHAR(200) | 批次标题 |
| total_count | INT | 总数 |
| success_count | INT | 成功数 |
| failed_count | INT | 失败数 |
| waiting_count | INT | 等待数 |

#### tg_import_account（导入账号明细表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| batch_no | VARCHAR(64) | 批次号 |
| phone | VARCHAR(32) | 手机号 |
| status | VARCHAR(20) | 状态: waiting/online/failed/banned |
| tg_user_id | BIGINT | TG用户ID |

#### tg_contact_import_batch（联系人导入批次表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| batch_no | VARCHAR(64) UNIQUE | 批次号 |
| import_type | VARCHAR(20) | 导入类型: phone/username |
| total_count | INT | 总数 |
| used_count | INT | 已用数 |

#### tg_contact_import_record（联系人导入记录表）

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INT AUTO_INCREMENT | 主键 |
| batch_no | VARCHAR(64) | 批次号 |
| phone | VARCHAR(32) | 联系人手机号 |
| username | VARCHAR(200) | 联系人用户名 |

#### tg_contact_assign_log（好友分配日志 - 用于加好友队列）

用于记录"分配给哪个账号添加哪个好友"的任务队列，contact_adder 模块轮询此表处理待添加的好友。

#### tg_account_config（账号配置表 - 兼容旧Java后台）

历史遗留表，包含api_id, api_hash, device_model等配置信息。

---

## 三、tg-client-telethon 核心逻辑

### 3.1 应用启动流程 (main.py)

```
1. 初始化数据库连接池 (database.init_db())
2. 写启动登出日志（标记之前在线的账号为"服务重启"）
3. 逐个登录之前在线的账号 (client_manager.login_all_db_accounts())
   - 跳过 is_restricted=1 的账号
   - 每个账号间隔1秒（串行）
   - 400+账号约需7分钟
4. 登录完成后发送TG通知
5. 启动后台任务:
   - _periodic_sync(): 每小时同步联系人+聊天记录
   - auto_reply.poll_auto_reply(): 每5分钟轮询主动发消息
   - contact_adder.poll_contact_adder(): 每60秒轮询待加好友
6. Uvicorn启动，监听8807端口
```

### 3.2 账号登录流程 (client_manager.py)

```
login_account_by_phone(phone):
1. 检查是否已在线
2. 检查 .session 文件是否存在
3. 读取 .json 文件（可选）
   - 有 .json: 从中获取 api_id, api_hash, device_kwargs
   - 无 .json: 
     a) 先从数据库加载已保存的设备指纹
     b) 数据库无记录则随机生成指纹并保存到数据库
     c) 使用默认 api_id=2040, api_hash="b18441a1ff607e10a989891a5462e627"
4. 从数据库获取代理信息，构建 proxy_kwargs
5. 创建 TelegramClient 实例，连接
6. 验证 session 是否已授权
7. 获取用户信息 (client.get_me())
8. 注册消息事件处理器（实时消息→保存DB→触发自动回复）
9. 更新数据库状态、写登录日志、发TG通知
10. 后台触发数据同步
```

### 3.3 自动回复核心逻辑 (auto_reply.py)

#### 触发方式

1. **incoming（实时触发，state=0）**: 收到好友消息时立即回复
2. **polling（定时轮询，state=0~8）**: 每5分钟扫描符合条件的好友，主动发消息

#### State 状态机

```
State判断逻辑:

前置条件:
- 好友开启了自动回复 (auto_reply=1)
- 账号开启了自动回复 (auto_reply=1)
- 满足以下之一:
  - 最后发送时间为空
  - 最后接收时间为空
  - (最后发送时间距今<72小时 且 最后发送时间>最后接收时间)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
好友没给自己发过消息 (last_receive_time IS NULL):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - 最后发送时间为空 → state=1
  - 发送次数为0 → state=1
  - 发送1次 且 距今>=1小时 → state=2
  - 发送2次 且 距今>=3小时 → state=3
  - 发送3次 且 距今>=24小时 → state=4
  - 其他 → state=-1 (跳过)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
好友给自己发过消息 (last_receive_time IS NOT NULL):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - 最后发送时间为空 → state=0
  - 最后发送时间 < 最后接收时间 → state=0
  - 否则检查最后N条连续发出消息:
    - 连续5条都是自己发的 → state=-1 (停止骚扰)
    - 连续4条 且 48<=距今<=72小时 → state=8
    - 连续3条 且 24<=距今<=48小时 → state=7
    - 连续2条 且 12<=距今<=24小时 → state=6
    - 连续1条 且 3<=距今<=12小时 → state=5
    - 其他 → state=-1 (跳过)
```

#### 各 State 发送策略

| State | 含义 | 发送内容 |
|-------|------|----------|
| 0 | 好友发过消息，需要回复 | 好友消息数<=1: 发**广告问候语**(tg_greeting)；>1: 调**自动回复API** |
| 1 | 第一次主动打招呼 | 从**主动开场白**(tg_opening)随机获取一条 |
| 2~8 | 递进追踪 | 调**自动回复API**获取内容 |
| -1 | 跳过 | 不发送 |

#### 自动回复API调用

- **地址**: 
  - 第一套: `http://127.0.0.1:8000/generate-reply`
  - 第二套: `http://172.22.0.43/generate-reply`（通过nginx代理到第一套8000端口）
- **请求参数**:
  ```json
  {
    "state": 0,           // 状态值
    "agent_gender": 1,    // 固定: 女
    "customer_gender": 2, // 固定: 未知
    "my_nickname": "账号TG用户ID",
    "customer_name": "好友TG用户ID",
    "chat_context": "TG用户ID[时间]:内容\nTG用户ID[时间]:内容"
  }
  ```
- **chat_context格式**: 
  ```
  {发送者TGID}[{YYYY-MM-DD HH:mm:ss}]:{消息内容}
  ```
  最近60条消息，按时间正序排列。

- **错误处理**: 3次重试，指数退避(2s, 4s)。区分错误类型:
  - ConnectTimeout: 连接超时
  - ReadTimeout: 读取超时
  - ConnectError: 连接失败
  - PoolTimeout: 连接池满

#### 广告问候语发送

- 从 `tg_greeting` 表获取第一条有效的（is_enabled=1，按sort_order排序）
- 如果有图片(image_path字段)：文字+图片作为**一条消息**发送（send_file + caption）
- 数据库聊天记录**分开写2条**：一条text类型，一条photo类型
- 更新 last_send_time

#### 消息发送中的特殊处理

- **[AIMG:url] 标签**: API返回的回复内容中如果包含 `[AIMG:图片URL]`，会下载图片并发送
- **FloodWaitError**: 捕获后等待指定秒数再重试
- **PRIVACY_PREMIUM_REQUIRED**: 发送失败且是此错误，自动关闭该好友的自动回复
- **Too many requests**: 发送失败3次以上，标记账号为restricted，登出+释放资源+TG通知

### 3.4 添加好友模块 (contact_adder.py)

- 每60秒轮询 `tg_contact_assign_log` 表中待处理的任务
- 支持两种添加方式:
  - 手机号: 使用 `ImportContactsRequest`
  - 用户名: 使用 `client.get_entity(username)`
- 添加成功后: 写入 `tg_contact` 表，状态为 `import`
- 网络错误自动重试（最多30次）
- 非网络错误直接标记失败

### 3.5 数据同步模块 (data_collector.py)

- **触发时机**: 账号登录后立即 + 每小时定时
- **同步内容**:
  1. 获取所有联系人 → upsert到 `tg_contact`
  2. 获取最近对话的聊天记录 → upsert到 `tg_chat_message`
  3. 更新 last_online_time, last_send_time, last_receive_time

### 3.6 实时消息处理

```
收到消息 → _base_new_message_handler:
1. 标记消息已读 (send_read_acknowledge)
2. 保存消息到数据库 (await data_collector.save_realtime_message)
   - 先保存到DB，确保消息入库
3. 触发自动回复 (asyncio.create_task(auto_reply.handle_incoming_message))
   - 在消息入库之后再触发
```

### 3.7 账号限制处理

```
条件: 发送失败日志中 "Too many requests" 出现 >= 3次
处理:
1. 设置 is_restricted=1, status='restricted'
2. 从 active_clients 中移除
3. 断开连接 (client.disconnect())
4. 发送TG通知
5. 重启时跳过 is_restricted=1 的账号
```

### 3.8 设备指纹管理

登录时如果没有 .json 文件:
1. 先从数据库 `tg_telethon_account` 表加载 device_model 等字段
2. 如果数据库也没有：随机生成一个指纹（15种设备型号池）
3. 保存到数据库，后续登录复用

设备池包括: Samsung Galaxy S21-S23, Xiaomi 13-14, HUAWEI P60, OPPO, vivo, OnePlus, Google Pixel, iPhone等。

### 3.9 TG Bot通知 (notify.py)

- **Bot Token**: 8534398194:AAF6CKDeS_yGeo167C4znOq9cR3porDGJa0
- **Chat ID**: -5181774632
- 通过 Telegram Bot API 发送HTML格式消息
- 用于: 登录成功/失败、账号被限制、服务启动等通知

---

## 四、tg-client-bg 后台系统

### 4.1 技术栈

- Java 17
- Spring Boot 2.x (RuoYi框架)
- MyBatis-Plus
- MySQL 5.7
- Redis
- Maven多模块

### 4.2 后台功能模块

| 模块 | 功能 |
|------|------|
| 账号管理 | 账号列表、搜索(手机号/批次号)、状态显示、消息统计(总/发送/接收) |
| 好友列表 | 好友列表、搜索(TG用户ID)、聊天记录弹窗(500条)、操作(发送问候语) |
| 聊天记录 | 消息列表、搜索(聊天ID)、图片直接显示 |
| 广告问候语 | CRUD、图片上传、启用/禁用、排序 |
| 主动开场白 | CRUD、纯文本内容、启用/禁用 |
| IP代理管理 | 代理列表、用户名显示、状态管理 |
| 账号导入 | 批量导入账号(.session文件) |
| 联系人导入 | 批量导入联系人(手机号/用户名) |

### 4.3 后台与Telethon交互

Java后台通过 HTTP 调用 Telethon 服务(8807端口):
- 登录/登出账号
- 发送问候语
- 批量导入联系人
- 测试代理
- 下载媒体文件

### 4.4 登录信息

- 地址: http://{服务器IP}
- 账号: admin
- 密码: admin123

---

## 五、Telethon API 接口

### 5.1 FastAPI 端点 (端口8807)

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/login/{phone} | 登录单个账号 |
| POST | /api/login/batch/{batch_no} | 批量登录 |
| POST | /api/login/wait | 登录所有等待中的账号 |
| POST | /api/login/noproxy/{phone} | 无代理登录(测试用) |
| POST | /api/logout/{phone} | 登出单个账号 |
| POST | /api/logout/batch/{batch_no} | 批量登出 |
| POST | /api/logout/all | 登出所有账号 |
| GET | /api/status | 服务状态 |
| GET | /api/accounts | 账号列表 |
| GET | /api/accounts/active | 在线账号列表 |
| POST | /api/sync | 手动触发数据同步 |
| POST | /api/add-contact | 添加联系人 |
| POST | /api/contacts/batch_import | 批量导入联系人 |
| POST | /api/send-greeting | 发送问候语 |
| POST | /api/proxy/test | 测试代理连接 |
| GET | /api/client/tg/file | 下载TG媒体文件 |
| WS | /ws/client | WebSocket连接 |
| POST | /api/token | 获取JWT Token |

---

## 六、业务流程详解

### 6.1 账号导入流程

```
1. 后台上传 .zip 文件（包含 .session + .json 文件）
2. 解压到 account/ 目录
3. 写入 tg_import_batch 和 tg_import_account 表
4. 调用 /api/login/batch/{batch_no} 批量登录
5. 逐个账号尝试连接Telegram
6. 登录成功: 更新状态、同步数据、注册消息handler
7. 登录失败: 记录原因（代理失败/session过期/被封等）
```

### 6.2 添加好友流程

```
1. 后台上传联系人文件（手机号或用户名列表）
2. 分配给在线账号（写入 tg_contact_assign_log）
3. contact_adder 每60秒轮询，取出待处理任务
4. 使用 ImportContactsRequest 或 get_entity 添加好友
5. 添加成功: 写入 tg_contact 表(source='import')
6. 添加失败: 网络错误重试(最多30次)，其他错误直接失败
```

### 6.3 消息收发流程

```
接收消息:
1. Telethon事件触发 → _base_new_message_handler
2. 标记已读
3. 保存到 tg_chat_message 表（await，确保入库）
4. 更新 recv_msg_count
5. 触发自动回复（create_task，异步不阻塞）

发送消息（自动回复/问候语）:
1. 调用 client.send_message 或 client.send_file
2. 保存到 tg_chat_message 表
3. 更新 sent_msg_count
4. 更新 last_send_time
5. 失败则写 tg_send_fail_log，检查是否需要限制账号
```

### 6.4 问候语发送流程

```
好友列表页面"发送问候语"按钮:
1. 前端弹窗选择问候语
2. 调用 /api/send-greeting
3. 如有图片: send_file(file, caption=文字) — 一条消息发送
4. 仅文字: send_message(文字)
5. 数据库分开写:
   - 文字 → 一条 content_type='text' 记录
   - 图片 → 一条 content_type='photo' 记录
6. 更新 last_send_time 和消息计数
```

---

## 七、部署与运维

### 7.1 环境要求

- Ubuntu 22.04
- Docker (MySQL 5.7, Redis)
- Python 3.10 + pip
- JDK 17
- Nginx
- 时区: Asia/Shanghai (UTC+8)

### 7.2 Python 依赖

```
telethon
fastapi
uvicorn
httpx
aiomysql
aiohttp
aiohttp-socks
python-socks[asyncio]
pyjwt
cryptography
```

### 7.3 重启脚本

**Telethon 服务** (`bin/restart.sh`):
```bash
#!/bin/bash
# 1. 杀掉所有旧进程
kill -9 $(pgrep -f "python3 main.py") 2>/dev/null
sleep 2
# 确认全部杀死
kill -9 $(pgrep -f "python3 main.py") 2>/dev/null
sleep 1

# 2. 清理 session-journal 锁文件
find sessions/ -name "*.session-journal" -delete 2>/dev/null
find account/ -name "*.session-journal" -delete 2>/dev/null

# 3. 启动
cd /home/ubuntu/telegram-project/tg-client-telethon
nohup python3 main.py >> logs/app.log 2>&1 &
echo "Started PID: $!"
```

**Java后端**:
```bash
# 启动
bash /home/ubuntu/telegram-project/tg-client-bg/bin/startup.sh
# 停止
bash /home/ubuntu/telegram-project/tg-client-bg/bin/shutdown.sh
```

### 7.4 Nginx 配置要点

```nginx
server {
    listen 80;

    # 前端静态文件
    location / {
        root /home/ubuntu/telegram-project/ruoyi-ui/dist;
        try_files $uri $uri/ /index.html;
    }

    # Java后台API
    location /prod-api/ {
        proxy_pass http://localhost:8809/;
    }

    # 图片/上传文件
    location /profile/ {
        alias /home/ubuntu/telegram-project/uploadPath/;
    }

    # 自动回复API代理（第一套特有，供第二套调用）
    location /generate-reply {
        proxy_pass http://localhost:8000/generate-reply;
    }
}
```

### 7.5 第二套与第一套的差异

| 配置项 | 第一套 | 第二套 |
|--------|--------|--------|
| REPLY_API_URL | http://127.0.0.1:8000/generate-reply | http://172.22.0.43/generate-reply |
| MySQL | Docker容器名 mysql57 | Docker容器名 mysql-container |
| 自动回复API | 本地运行 | 通过nginx代理访问第一套 |

**第二套连接第一套API说明**: 
- 云安全组未开放8000端口
- 解决方案: 第一套nginx配置 `/generate-reply` 代理到 `localhost:8000`
- 第二套通过内网IP `172.22.0.43:80` (nginx端口) 访问

---

## 八、配置文件 (config.py)

```python
# 服务端口
HOST = "0.0.0.0"
PORT = 8807

# 数据库
DB_HOST = "127.0.0.1"
DB_PORT = 3306
DB_USER = "root"
DB_PASSWORD = "XkOVjlR6FvmONtLi75BS"
DB_NAME = "tg-client-server"

# TG Bot通知
BOT_TOKEN = "8534398194:AAF6CKDeS_yGeo167C4znOq9cR3porDGJa0"
BOT_CHAT_ID = "-5181774632"

# JWT
JWT_SECRET = "tg-telethon-secret-key-2024"
JWT_EXPIRE_HOURS = 24

# 自动回复API
REPLY_API_URL = "http://127.0.0.1:8000/generate-reply"  # 第二套改为 http://172.22.0.43/generate-reply
AUTO_REPLY_INTERVAL = 300  # 秒 (5分钟)

# 文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNT_DIR = os.path.join(BASE_DIR, "account")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
```

---

## 九、关键业务规则

### 9.1 自动回复条件

只对满足以下全部条件的好友自动回复：
1. 好友 `auto_reply=1`（开启自动回复）
2. 好友 `source='import'`（后台导入的好友）
3. 好友 `is_bot=0`（非机器人）
4. 好友 `user_id` 不在 `OFFICIAL_IDS`（排除777000等官方ID）
5. 账号 `auto_reply=1`
6. 账号 `status='online'`
7. 账号 `is_restricted=0`

### 9.2 消息计数规则

- **不计入**系统账号(chat_id=777000)的消息
- 每次发送成功: `sent_msg_count+1`, `total_msg_count+1`, `account_sent_count+1`
- 每次接收消息: `recv_msg_count+1`, `total_msg_count+1`, `friend_sent_count+1`

### 9.3 图片消息处理

- Telegram中"图片+文字"是一条 **photo类型消息带caption**
- 发送: `client.send_file(entity, file, caption="文字")`
- 存储: 分成2条记录（一条text，一条photo）
- 显示: 聊天记录页面直接显示图片缩略图

---

## 十、已知问题与优化方向

### 10.1 当前问题

1. **启动速度慢**: 400+账号串行登录约7分钟。可优化为并发登录(每个账号独立代理，并发20-30)
2. **API返回空内容多**: `tg_auto_reply_log` 中约200万条"API返回回复内容为空"，AI模型问题
3. **TG Bot通知限流**: 批量操作时Bot API返回429，需加队列

### 10.2 优化建议

1. 并发登录：用 `asyncio.Semaphore(20)` 控制，预计400账号15-20秒完成
2. session文件存数据库：便于多服务器部署和账号迁移
3. 消息队列：Bot通知改为异步队列，避免429
