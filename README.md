# 🔔 raricy.com 自动打卡系统

---

## 一、项目介绍

### 1.1 这是什么

一个基于 **Python + requests** 的纯 HTTP API 自动化打卡系统，用于 raricy.com 网站的每日签到。它直接调用网站自身的 HTTP 接口完成登录与打卡，**不依赖任何浏览器或 ChromeDriver**，支持多账号、定时执行、运势卡片抽取和 Web 控制面板管理。

### 1.2 功能特性

- ✅ **自动打卡** — 直接调用网站 HTTP API 完成登录和签到
- 👥 **多账号支持** — 支持多个账号，可选择指定账号打卡或一键批量打卡
- 🔮 **运势卡片抽取** — 打卡后自动抽取运势卡片，记录运势结果值
- ⏰ **定时执行** — APScheduler 支持多个每日定时任务，适配不同签到时段
- 🖥 **Web 控制面板** — 单页 HTML 管理界面：状态查看 / 手动打卡 / 配置编辑 / 日志查看
- ⚙ **高度可配置** — URL、API 路径、定时规则通过 `config.json` 管理，账号通过 `accounts.json` 管理
- 📡 **实时进度** — 打卡过程实时显示"正在登录 → 登录成功 → 正在打卡 → 打卡成功"步骤动画
- 🖱 **一键打卡** — 桌面快捷方式一键启动系统（详见使用指南）
- 📚 **博客工具** — 目录扫描 / 内容抓取 / 批量点赞，纯 requests + SQLite 存储

### 1.3 技术架构

```
APScheduler 定时任务 或 Web 控制面板手动触发
        │
        ▼
CheckinEngine.execute()
        │  requests.Session
        ├─ POST /auth/login           → 登录（表单优先，JSON 兜底）
        ├─ POST /checkin/api/do-checkin → 打卡
        └─ POST /checkin/api/claim-fortune → 运势卡片（可选）
        │
        ▼
写入 runtime/logs/checkin_log.json
```

- **Flask** 提供 Web 控制面板与 HTTP API
- **APScheduler** 管理每日定时打卡
- **纯 requests** 完成所有页面交互，无 Selenium 依赖

### 1.4 项目结构

```
raricy_auto_checkin/
├── run.py                      # 项目入口（启动 Flask + 调度器）
├── launcher.py                 # 桌面快捷方式启动器（检测服务 → 启动/打开面板）
├── start_checkin.bat           # 快捷方式入口脚本（纯 ASCII，调用 launcher.py）
├── .gitignore                  # Git 忽略规则
├── README.md                   # 本文件
├── CLAUDE.md                   # Claude Code 指引
├── favicon.ico                 # 站点图标（同时作为快捷方式图标）
├── backend/
│   ├── __init__.py             # 包标记
│   ├── checkin.py              # requests 打卡引擎（核心逻辑）+ 配置读取
│   ├── scheduler.py            # APScheduler 定时调度器
│   ├── app.py                  # Flask API 服务 + 进度追踪
│   ├── config.json             # 站点/定时/运势/API 配置（不含账号）
│   ├── accounts.json           # 账号列表（含密码，已 gitignore，不提交）
│   └── requirements.txt        # Python 依赖
├── frontend/
│   └── index.html              # Web 控制面板
└── runtime/                    # 运行时生成（自动创建）
    └── logs/                   # 打卡日志 JSON
```

---

## 二、使用指南

### 2.1 环境要求

| 依赖     | 说明                    |
| -------- | ----------------------- |
| Python   | 3.10 及以上             |
| 操作系统 | Windows / macOS / Linux |

无需 Chrome 浏览器或 ChromeDriver。

### 2.2 安装依赖

```bash
cd raricy_auto_checkin
pip install -r backend/requirements.txt
```

### 2.3 配置账号

账号保存在 `backend/accounts.json`（**该文件已加入 `.gitignore`，不会提交到 Git**），格式为账号数组：

```json
[
  {
    "username": "你的用户名",
    "password": "你的密码",
    "enabled": true
  },
  {
    "username": "账号2",
    "password": "密码2",
    "enabled": false
  }
]
```

> - `enabled: false` 的账号会被跳过，不参与打卡。
> - 也可以通过 Web 控制面板「账号管理」修改，密码自动脱敏显示。
> - 首次使用：系统读取 `accounts.json`；若文件不存在则回退到 `config.json` 内嵌的 `accounts`（旧版兼容）。

### 2.4 启动系统

**方式一：桌面一键打卡（推荐）**

双击桌面「一键打卡」快捷方式，脚本自动判断：

- 服务**未运行** → 启动服务并自动打开浏览器控制面板
- 服务**已在运行** → 直接打开控制面板，不重复启动

> 快捷方式图标指向项目根目录的 `favicon.ico`。

#### 如何创建「一键打卡」快捷方式

快捷方式由两部分组成，缺一不可：

| 文件 | 位置 | 作用 |
| ---- | ---- | ---- |
| `start_checkin.bat` | 项目根目录 | 入口脚本（纯 ASCII，调用 `launcher.py`） |
| `一键打卡.lnk` | 桌面 | Windows 快捷方式，双击触发上面的 bat |

**创建步骤（PowerShell）：**

1. 确认项目根目录存在 `start_checkin.bat`（本仓库已包含，通常无需新建）。
2. 在 PowerShell 中执行以下命令创建快捷方式（把下面的 `<项目根目录>` 替换为你的实际路径）：

```powershell
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = $ws.CreateShortcut("$desktop\一键打卡.lnk")
$lnk.TargetPath = '<项目根目录>\start_checkin.bat'
$lnk.WorkingDirectory = '<项目根目录>'
$lnk.IconLocation = '<项目根目录>\favicon.ico'
$lnk.Save()
```

3. 若桌面图标未即时刷新，按 `F5` 刷新或重启资源管理器即可。

> - `<项目根目录>` 即本项目所在目录的绝对路径（含 `start_checkin.bat` 的那一层）。
> - `start_checkin.bat` 使用 `%~dp0` 自动定位自身所在目录，因此不依赖固定路径，项目移动到任意位置都能正常工作。

**方式二：命令行启动**

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

> 调试提示：设置环境变量 `LAUNCHER_NO_BROWSER=1` 后再启动，可禁止 `launcher.py` 自动打开浏览器。

### 2.5 使用控制面板

浏览器打开后，可以看到控制面板：

- **状态面板** — 查看各账号今日打卡状态、下次定时时间
- **账号选择** — 勾选要打卡的账号，支持全选/取消全选
- **🖐 打卡所选** — 为选中的账号逐一打卡（实时显示进度动画）
- **⚡ 批量全部** — 一键为所有启用账号打卡
- **⏰ 定时设置** — 添加/删除每日打卡时间点（如 09:00, 18:00）
- **⚙ 配置** — 编辑 URL、API 路径、定时、运势等配置
- **日志列表** — 查看历史打卡记录（默认5条，可展开至50条）

### 2.6 配置说明

站点、定时、运势、API 路径等配置在 `backend/config.json`：

```json
{
  "site": {
    "login_url": "https://raricy.com/auth/login",
    "checkin_url": "https://raricy.com/checkin"
  },
  "schedule": {
    "times": ["13:00"],
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

| 配置段       | 说明                                                      |
| ------------ | --------------------------------------------------------- |
| `site`     | 登录页和打卡页 URL                                        |
| `schedule` | 定时打卡时间列表、时区、启用开关                          |
| `fortune`  | 运势卡片：是否启用、选牌策略（`random` 或数字索引）       |
| `api`      | 各 API 路径（登录/打卡/运势），默认值通常无需修改         |

> **账号不在此文件**：账号在 `accounts.json`，通过 Web 控制面板「账号管理」或直接编辑该文件修改。
>
> **API 路径说明**：所有打卡操作通过网站自身的 HTTP API 完成，路径可配置。如果 raricy.com 接口地址发生变化，修改 `api` 段即可。

### 2.7 HTTP API 接口

| 方法     | 路径                                | 说明                               |
| -------- | ----------------------------------- | ---------------------------------- |
| `GET`  | `/`                               | 返回 Web 控制面板                  |
| `GET`  | `/api/health`                     | 健康检查                           |
| `GET`  | `/api/status`                     | 今日各账号打卡状态 + 下次定时时间  |
| `POST` | `/api/checkin`                    | 手动触发打卡（异步，返回 task_id） |
| `GET`  | `/api/checkin/progress/<task_id>` | 轮询打卡进度                       |
| `GET`  | `/blog`                           | 返回博客工具页面                    |
| `POST` | `/api/blog/scan`                  | 扫描博客目录（异步，返回 task_id） |
| `POST` | `/api/blog/fetch`                 | 抓取文章内容（异步，body: article_ids） |
| `POST` | `/api/blog/like`                  | 批量点赞（异步，body: article_ids + account） |
| `GET`  | `/api/blog/progress/<task_id>`    | 轮询博客任务进度                    |
| `GET`  | `/api/blog/articles`              | 博客文章与点赞记录列表               |
| `GET`  | `/api/logs?limit=50`              | 打卡历史记录                       |
| `GET`  | `/api/accounts`                   | 获取所有账号列表（密码脱敏）       |
| `POST` | `/api/accounts`                   | 更新账号列表（写入 accounts.json） |
| `GET`  | `/api/config`                     | 获取当前配置（密码脱敏）           |
| `POST` | `/api/config`                     | 更新配置（支持路径更新或整体替换） |

**手动打卡：**

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

### 2.8 打卡流程

系统完整的自动化流程（纯 HTTP API）：

```
POST /auth/login (username + password)
  → Session cookie 获取成功
  → POST /checkin/api/do-checkin
  → 检测响应：已打卡 / 打卡成功
  → (可选) POST /checkin/api/claim-fortune (chosen_index)
  → 记录日志 → 返回结果
```

### 2.9 常见问题

**登录失败**

```
登录失败：账号 xxx 的用户名或密码错误
```

**解决**：检查 `backend/accounts.json` 中该账号的用户名和密码是否正确。

**API 路径变更**

如果 raricy.com 接口地址发生变化，在控制面板「配置 → API 设置」中更新对应路径，或直接编辑 `config.json` 的 `api` 段。

**端口被占用**

```bash
python run.py --port 8080    # 换一个端口
```

**网络异常**

检查服务器是否能正常访问 raricy.com。项目默认超时 15 秒，超时会返回"网络异常"提示。

---

## 许可

MIT License
