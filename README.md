# tg-client-telethon

Telegram 多账号客户端管理服务（Python + Telethon），提供 REST API 接口。

## 目录结构

```
tg-client-telethon/
├── account/
│   ├── waitLogin/       # 待登录账号文件（.json + .session）
│   ├── loginSuccess/    # 登录成功账号（每个账号一个文件夹）
│   └── data/            # 账号缓存数据
├── bin/
│   ├── startup.sh       # 启动
│   ├── shutdown.sh      # 停止
│   └── restart.sh       # 重启
├── script/
│   └── login_wait.sh    # 登录待登录账号的脚本
├── logs/
│   └── app.log          # 应用日志
├── main.py              # 主程序（FastAPI）
├── config.py            # 配置
├── client_manager.py    # Telethon 客户端管理
├── database.py          # 数据库操作
├── notify.py            # Telegram Bot 通知
└── requirements.txt     # Python 依赖
```

## 使用方式

### 安装依赖
```bash
pip install -r requirements.txt
```

### 启动/停止
```bash
bash bin/startup.sh    # 启动（后台运行）
bash bin/shutdown.sh   # 停止
bash bin/restart.sh    # 重启
```

### 登录账号
1. 将 `.json` 和 `.session` 文件放入 `account/waitLogin/` 目录
2. 执行: `bash script/login_wait.sh`
3. 或调用 API: `POST http://localhost:8807/api/login/wait`

### API 接口
- `GET /api/status` — 服务状态
- `POST /api/login/wait` — 登录所有待登录账号
- `POST /api/login/{phone}` — 登录指定账号
- `POST /api/logout/{phone}` — 登出指定账号
- `GET /api/accounts` — 所有账号列表
- `GET /api/accounts/active` — 当前在线账号
- `GET /api/accounts/wait` — 待登录账号列表
- `POST /api/notify/test` — 测试通知

### 数据库
使用 MySQL `tg-client-server` 数据库，表: `tg_telethon_account`

### 通知
登录结果通过 Telegram Bot 发送到指定群。
