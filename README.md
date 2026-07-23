# 🔔 raricy.com 自动打卡系统

基于 **Python + requests** 的纯 HTTP API 自动化打卡系统，支持多账号、定时执行、运势卡片抽取和 Web 控制面板管理。

## 功能特性

- ✅ **自动打卡** — requests 直接调用网站 HTTP API 完成登录和签到
- 👥 **多账号支持** — 支持多个账号，可选择指定账号打卡或一键批量打卡
- 🔮 **运势卡片抽取** — 打卡后自动抽取运势卡片，记录运势结果值
- ⏰ **定时执行** — APScheduler 支持多个每日定时任务，适配不同签到时段
- 🖥 **Web 控制面板** — 单页 HTML 管理界面，状态查看 / 手动打卡 / 配置编辑 / 日志查看
- ⚙ **高度可配置** — URL、API 路径、账号、定时规则全部通过 `config.json` 或 Web UI 管理
- 📡 **实时进度** — 打卡过程实时显示"正在登录→登录成功→正在打卡→打卡成功"步骤动画

## 项目结构

```
raricy_auto_login/
├── run.py                      # 项目入口，一键启动
├── .gitignore                  # Git 忽略规则
├── README.md                   # 本文件
├── CLAUDE.md                   # Claude Code 指引
├── backend/
│   ├── __init__.py             # 包标记
│   ├── checkin.py              # requests 打卡引擎（核心逻辑）
│   ├── scheduler.py            # APScheduler 定时调度器
│   ├── app.py                  # Flask API 服务 + 进度追踪
│   ├── config.json             # 所有可配置项
│   └── requirements.txt        # Python 依赖
├── frontend/
│   └── index.html              # Web 控制面板
└── runtime/                    # 运行时生成（自动创建）
    └── logs/                   # 打卡日志 JSON
```

## 环境要求

| 依赖     | 说明                    |
| -------- | ----------------------- |
| Python   | 3.8 及以上              |
| 操作系统 | Windows / macOS / Linux |

无需 Chrome 浏览器或 ChromeDriver。

## 快速开始

### 1. 安装 Python 依赖

```bash
cd raricy_auto_login
pip install -r backend/requirements.txt
```

### 2. 配置账号信息

编辑 `backend/config.json`，在 `accounts` 数组中填写你的 raricy.com 账号：

```json
{
  "accounts": [
    {
      "username": "你的用户名",
      "password": "你的密码",
      "enabled": true
    }
  ]
}
```

> 也可以通过启动后的 Web 控制面板修改配置，密码会自动脱敏。

### 3. 启动系统

```bash
python run.py
```

默认启动在 `http://127.0.0.1:5000`，自动打开浏览器访问控制面板。

**命令行参数：**

| 参数               | 说明                       |
| ------------------ | -------------------------- |
| `--port 8080`    | 指定服务端口（默认 5000）  |
| `--host 0.0.0.0` | 绑定地址（默认 127.0.0.1） |
| `--debug`        | Flask 调试模式（热重载）   |
| `--no-browser`   | 不自动打开浏览器           |

### 4. 使用控制面板

浏览器打开后，可以看到控制面板：

- **状态面板** — 查看各账号今日打卡状态、下次定时时间
- **账号选择** — 勾选要打卡的账号，支持全选/取消全选
- **🖐 打卡所选** — 为选中的账号逐一打卡（实时显示进度动画）
- **⚡ 批量全部** — 一键为所有启用账号打卡
- **⏰ 定时设置** — 添加/删除每日打卡时间点（如 09:00, 18:00）
- **⚙ 配置** — 编辑 URL、API 路径、账号、运势卡片等所有配置
- **日志列表** — 查看历史打卡记录（默认5条，可展开至50条）

## 配置说明

完整配置文件 `backend/config.json`：

```json
{
  "site": {
    "login_url": "https://raricy.com/auth/login",
    "checkin_url": "https://raricy.com/checkin"
  },
  "accounts": [
    {
      "username": "test",
      "password": "12345678",
      "enabled": true
    }
  ],
  "schedule": {
    "times": ["09:00", "18:00"],
    "timezone": "Asia/Shanghai",
    "enabled": true
  },
  "fortune": {
    "enabled": true,
    "card_index": "random"
  },
  "api": {
    "login_path": "/auth/login",
    "checkin_path": "/checkin/api/do-checkin",
    "fortune_path": "/checkin/api/claim-fortune"
  }
}
```

| 配置段       | 说明                                                    |
| ------------ | ------------------------------------------------------- |
| `site`     | 登录页和打卡页 URL                                      |
| `accounts` | 账号数组，每项含`username`、`password`、`enabled` |
| `schedule` | 定时打卡时间列表、时区、启用开关                        |
| `fortune`  | 运势卡片：是否启用、选牌策略（`random` 或数字索引）   |
| `api`      | 各 API 路径（登录/打卡/运势），默认值通常无需修改       |

> **API 路径说明**：所有打卡操作通过网站自身的 HTTP API 完成，路径可配置。如果 raricy.com 接口地址发生变化，修改 `api` 段即可。

## API 接口

| 方法     | 路径                                | 说明                               |
| -------- | ----------------------------------- | ---------------------------------- |
| `GET`  | `/`                               | 返回 Web 控制面板                  |
| `GET`  | `/api/health`                     | 健康检查                           |
| `GET`  | `/api/status`                     | 今日各账号打卡状态 + 下次定时时间  |
| `POST` | `/api/checkin`                    | 手动触发打卡（异步，返回 task_id） |
| `GET`  | `/api/checkin/progress/<task_id>` | 轮询打卡进度                       |
| `GET`  | `/api/logs?limit=50`              | 打卡历史记录                       |
| `GET`  | `/api/accounts`                   | 获取所有账号列表（密码脱敏）       |
| `POST` | `/api/accounts`                   | 更新账号列表                       |
| `GET`  | `/api/config`                     | 获取当前配置（密码脱敏）           |
| `POST` | `/api/config`                     | 更新配置（支持路径更新或整体替换） |

### 手动打卡

```bash
# 指定账号打卡
curl -X POST http://127.0.0.1:5000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{"accounts": ["user1", "user2"]}'

# 全部启用账号打卡
curl -X POST http://127.0.0.1:5000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{"accounts": ["all"]}'

# 轮询进度
curl http://127.0.0.1:5000/api/checkin/progress/<task_id>
```

### 配置更新

**路径更新（修改单个字段）：**

```bash
curl -X POST http://127.0.0.1:5000/api/config \
  -H "Content-Type: application/json" \
  -d '{"path": ["site", "login_url"], "value": "https://new-url.com/login"}'
```

**整体替换（提交完整配置对象）：**

```bash
curl -X POST http://127.0.0.1:5000/api/config \
  -H "Content-Type: application/json" \
  -d '{"site": {...}, "accounts": [...], ...}'
```

> 密码字段传入 `"****"` 将保持原密码不变。

## 打卡流程

系统完整的自动化流程（纯 HTTP API）：

```
POST /auth/login (username + password)
  → Session cookie 获取成功
  → POST /checkin/api/do-checkin
  → 检测响应：已打卡 / 打卡成功
  → (可选) POST /checkin/api/claim-fortune (chosen_index)
  → 记录日志 → 返回结果
```

## 常见问题

### 登录失败

```
登录失败：账号 xxx 的用户名或密码错误
```

**解决**：检查 `config.json` 中 `accounts` 的用户名和密码是否正确。

### API 路径变更

如果 raricy.com 接口地址发生变化，在控制面板「配置 → API 设置」中更新对应路径，或直接编辑 `config.json` 的 `api` 段。

### 端口被占用

```bash
python run.py --port 8080    # 换一个端口
```

### 网络异常

检查服务器是否能正常访问 raricy.com。项目默认超时 15 秒，超时会返回"网络异常"提示。

## 许可

MIT License
