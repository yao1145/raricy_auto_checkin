# raricy.com 自动打卡系统

一个基于 **Python + requests** 的纯 HTTP API 自动化操作台，面向 raricy.com 提供每日自动打卡、批量转账与博客辅助能力。全程调用网站自身的 HTTP 接口，**零 Selenium / ChromeDriver 依赖**，支持多账号、定时执行、固定签到奖励、批量手工 / 定时转账、博客目录扫描 / 内容抓取 / 批量点赞，并附带一套科幻风格的五面板 Web 控制台。

---

> **已经跑起来了？** 日常操作（查看今天打卡情况、手动补打卡、改定时、备份、排错）看 **[`USAGE.md` 日常使用指南](USAGE.md)**。本文讲的是安装、首次配置与各项功能说明。

## 一、项目介绍

### 1.1 这是什么

raricy.com 自动打卡系统通过 `requests` 直接调用网站 HTTP API 完成登录与打卡，规避了浏览器与驱动版本管理带来的维护负担。系统由 **Flask + APScheduler** 驱动，前端是纯静态多页面控制台，数据与日志落在本地 JSON / SQLite 中。

### 1.2 功能特性

- **自动打卡** —— 直接调用网站 HTTP API 完成登录与签到，无浏览器依赖
- **多账号支持** —— 多个账号可分别启用/禁用，支持按需勾选或一键批量打卡
- **定时执行** —— APScheduler 支持多个每日定时点，适配不同签到时段
- **固定奖励** —— 签到成功直接到账 3 条小鱼干，记录响应中的实际奖励与余额
- **批量转账** —— 每个启用或选定账号向指定用户名转账指定金额，自动排除收款账号自身，支持手工与独立每日定时
- **实时进度** —— 打卡 / 博客任务异步执行，前端 500ms 轮询展示步骤与进度条
- **博客工具** —— 目录扫描、内容抓取、批量点赞，SQLite 持久化，支持筛选与排序
- **Web 控制台** —— 五面板（控制中心 / 自动打卡 / 博客工具 / 系统配置）+ 科幻动态背景
- **账号密文存储** —— 账号凭据以 Fernet 密文落盘，密钥独立存放，误传/误提交不会泄露密码
- **Docker 部署** —— 可打包为镜像在 Rocky Linux 9 等服务器上无人值守运行
- **高度可配置** —— 站点、选择器、打卡 / 转账定时、API 路径均可通过配置面板在线修改

### 1.3 技术架构

```
APScheduler 定时任务 或 Web 控制台手动触发
        │
        ▼
CheckinEngine.execute()
        │  requests.Session
        ├─ POST /api/auth/login        → 登录（JSON，下发 JWT 会话 cookie）
        ├─ POST /api/checkin           → 打卡
        └─ 签到响应 reward_fish / today_fish / dried_fish → 奖励与余额（无抽卡）
        │
        ▼
写入 runtime/logs/checkin_log.json
```

- **Flask** 提供 Web 控制台与 HTTP API
- **APScheduler** 管理每日定时打卡
- **requests** 完成全部页面交互，无 Selenium 依赖
- **cryptography**（Fernet）加密账号凭据
- **sqlite3** 持久化文章与点赞记录（站点已改为 JSON 接口，不再需要 HTML 解析库）

### 1.4 项目结构

```
raricy_auto_checkin/
├── run.py                      # 项目入口（启动 Flask + 调度器）
├── launcher.py                 # 桌面快捷方式启动器（检测服务 → 启动/打开面板）
├── start_checkin.bat           # 快捷方式入口脚本（纯 ASCII，调用 launcher.py）
├── Dockerfile                  # 容器镜像定义
├── docker-compose.yml          # 服务器侧编排（回环端口 + 挂载 + SELinux :Z）
├── .dockerignore               # 构建上下文排除（含凭据文件）
├── README.md                   # 本文件
├── CLAUDE.md                   # Claude Code 指引
├── favicon.ico                 # 站点图标（同时作为快捷方式图标）
├── deploy/
│   └── DEPLOY.md               # Rocky Linux 9 部署手册
├── tests/                      # 单元测试（标准库 unittest，仅覆盖账号加密层）
├── backend/
│   ├── __init__.py             # 包标记
│   ├── app.py                  # Flask API 服务 + 进度追踪 + 前端路由
│   ├── checkin.py              # requests 打卡引擎（核心逻辑）+ 配置读取
│   ├── client.py               # 共享纯 requests 登录客户端（打卡/博客复用）
│   ├── crypto.py               # 账号文件加解密 + 密钥管理（Fernet）
│   ├── accounts_tool.py        # 账号迁移 CLI（明文 → 密文）
│   ├── blog.py                 # 博客引擎：目录扫描 / 内容抓取 / 批量点赞
│   ├── store.py                # SQLite 存储层（文章 + 点赞记录）
│   ├── progress.py             # 通用任务进度存储（内存）
│   ├── scheduler.py            # APScheduler 定时调度器
│   ├── config.json             # 站点/选择器/打卡与转账定时/API 配置（不含账号）
│   ├── accounts.enc            # 账号密文（已 gitignore，不提交）
│   └── requirements.txt        # Python 依赖
├── frontend/
│   ├── index.html              # 控制中心（状态总览 + 功能导航）
│   ├── checkin.html            # 自动打卡面板
│   ├── blog.html               # 博客工具面板
│   ├── config.html             # 系统配置面板
│   ├── styles.css              # 全局样式（设计令牌 + 组件 + 星云背景）
│   ├── app.js                  # 共享工具（API 客户端 / toast / 导航高亮）
│   ├── bg.js                   # 粒子星野 + 流星动态背景
│   └── favicon.ico             # 站点图标
└── runtime/                    # 运行时生成（自动创建，已 gitignore）
    ├── logs/                   # 打卡日志 JSON
    └── blog.db                 # 博客文章与点赞 SQLite 数据库
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

### 2.3 启动系统

**方式一：桌面一键打卡（推荐）**

双击桌面「一键打卡」快捷方式，脚本自动判断：

- 服务**未运行** → 启动服务并自动打开浏览器控制台
- 服务**已在运行** → 直接打开控制台，不重复启动

快捷方式由 `start_checkin.bat`（纯 ASCII，内部用 `%~dp0` 自动定位自身目录，不依赖固定路径）+ 桌面 `一键打卡.lnk` 组成。创建方法（PowerShell，`<项目根目录>` 替换为实际路径）：

```powershell
$ws = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = $ws.CreateShortcut("$desktop\一键打卡.lnk")
$lnk.TargetPath = '<项目根目录>\start_checkin.bat'
$lnk.WorkingDirectory = '<项目根目录>'
$lnk.IconLocation = '<项目根目录>\favicon.ico'
$lnk.Save()
```

**方式二：命令行启动**

```bash
python run.py
```

默认启动在 `http://127.0.0.1:5000`，自动打开浏览器访问控制台。

| 参数               | 说明                       |
| ------------------ | -------------------------- |
| `--port 8080`    | 指定服务端口（默认 5000）  |
| `--host 0.0.0.0` | 绑定地址（默认 127.0.0.1） |
| `--debug`        | Flask 调试模式（热重载）   |
| `--no-browser`   | 不自动打开浏览器           |

### 2.4 控制台导航

浏览器打开后进入「控制中心」，顶部导航可切换到四个面板：

| 面板     | 路径         | 用途                                             |
| -------- | ------------ | ------------------------------------------------ |
| 控制中心 | `/`        | 今日状态总览 + 各功能入口                        |
| 自动打卡 | `/checkin` | 状态查看、账号选择、手动/批量打卡、日志与定时    |
| 博客工具 | `/blog`    | 博客目录扫描、内容抓取、批量点赞                 |
| 系统配置 | `/config`  | 账号、站点、选择器、打卡 / 转账定时、API 路径集中管理 |

---

## 三、打卡管理

### 3.1 控制面板

「自动打卡」面板（`/checkin`）包含：

- **今日状态** —— 各账号今日是否已打卡、下次定时时间、调度器开关
- **账号选择** —— 账号 chip 可点选/取消，支持全选、取消全选；已禁用账号置灰并标注「已禁用」
- **打卡所选** —— 为选中的账号逐一打卡，实时展示步骤动画
- **批量全部** —— 一键为所有启用账号打卡
- **打卡记录** —— 历史日志表格（默认 5 条，可展开至 50 条）

> 选择已禁用账号打卡时，右上角会弹出「账号 XX 已被禁用」提示，并自动跳过该账号。

### 3.2 打卡流程

```
POST /api/auth/login {username, password}
  → 获取会话 cookie，并用 GET /api/checkin 复核会话真的生效
  → POST /api/checkin
  → 检测响应：已打卡 / 打卡成功
  → 签到响应直接包含固定奖励（3 条鱼干）和当前余额
  → 记录日志 → 返回结果
```

### 3.3 定时打卡

定时时间点通过「系统配置」面板的「定时设置」卡片维护（或直接编辑 `config.json` 的 `schedule` 段）。APScheduler 在后台按配置的每日时间点自动触发打卡。

### 3.4 打卡 API

| 方法     | 路径                                | 说明                               |
| -------- | ----------------------------------- | ---------------------------------- |
| `GET`  | `/api/health`                     | 健康检查                           |
| `GET`  | `/api/status`                     | 今日各账号打卡状态 + 下次定时时间  |
| `POST` | `/api/checkin`                    | 手动触发打卡（异步，返回 task_id） |
| `GET`  | `/api/checkin/progress/<task_id>` | 轮询打卡进度                       |
| `GET`  | `/api/logs?limit=50`              | 打卡历史记录                       |

**手动打卡示例：**

```bash
# 指定账号打卡
curl -X POST http://127.0.0.1:5000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{"accounts": ["user1", "user2"]}'

# 全部启用账号打卡
curl -X POST http://127.0.0.1:5000/api/checkin \
  -H "Content-Type: application/json" \
  -d '{"accounts": ["all"]}'
```

### 3.5 常见问题

**登录失败** —— 在「系统配置」面板检查该账号的用户名和密码（账号以密文存在 `backend/accounts.enc`，无法直接打开查看）。

**登录提示「尝试过于频繁」** —— 站点对登录做了限频，且**只统计失败的尝试**（同一用户名 15 分钟内 100 次、同一 IP 300 次）。密码错误重试太多次会触发，等待 15 分钟即可，成功登录本身不计入。这一提示与「密码错误」是分开的，看到它就说明凭据没错、只是被限流。

**端口被占用** —— `python run.py --port 8080` 换端口。

**网络异常** —— 确认服务器可访问 raricy.com；默认超时 15 秒，超时返回「网络异常」提示。

---

## 四、博客管理

### 4.1 简介

博客工具基于**纯 requests**（无浏览器依赖），对 raricy.com 博客区进行自动化操作，数据持久化在 `runtime/blog.db`（SQLite）：

- **目录扫描** —— 逐页爬取博客列表，收录文章（标题/作者/分类/描述/点赞数）
- **内容抓取** —— 抓取指定文章正文，供离线查看
- **批量点赞** —— 对选中文章批量点赞，支持重试与已赞跳过

所有操作异步执行并实时展示进度。

### 4.2 使用步骤

1. **扫描目录** —— 点击「扫描目录」，系统使用首个启用账号登录并逐页爬取。
2. **筛选 / 排序** —— 按作者、分类、点赞数、内容状态筛选，点击表头排序。
3. **抓取内容** —— 勾选文章后点击「抓取内容」（已抓取的可点「查看」阅读）。
4. **批量点赞** —— 选择点赞账号，勾选文章后点击「点赞所选」。
5. **清空数据库** —— 点击「清空数据库」删除全部文章与点赞记录。

### 4.3 每日点赞额度

raricy.com 单账号每日最多点赞 **100** 次，系统会：

- 在账号标签上实时显示该账号今日「已用 / 总量」，悬停提示剩余额度
- 某账号额度归零时自动禁用点赞按钮
- 点赞完成后在结果区展示本次消耗与今日剩余额度

> **点赞需要核心用户（core 及以上）权限。** 站点对点赞接口做了角色校验，普通用户账号调用会返回 `403 需要核心用户权限`，该篇点赞会记为失败。另外站点侧还有 100 次/小时、500 次/天的限频，超出会返回 `429`。

### 4.4 博客 API

| 方法     | 路径                             | 说明                                          |
| -------- | -------------------------------- | --------------------------------------------- |
| `GET`  | `/blog`                        | 博客工具页面                                  |
| `GET`  | `/api/blog/articles/all`       | 一次性加载全部文章（支持筛选/排序）           |
| `GET`  | `/api/blog/articles`           | 分页文章列表                                  |
| `GET`  | `/api/blog/meta`               | 作者 / 分类下拉选项                           |
| `GET`  | `/api/blog/article/<id>`       | 单篇文章详情（含正文）                        |
| `GET`  | `/api/blog/like-stats`         | 各账号今日点赞额度统计                        |
| `POST` | `/api/blog/scan`               | 扫描博客目录（异步，返回 task_id）            |
| `POST` | `/api/blog/fetch`              | 抓取文章内容（异步，body: article_ids）       |
| `POST` | `/api/blog/like`               | 批量点赞（异步，body: article_ids + account） |
| `POST` | `/api/blog/clear`              | 清空文章与点赞记录                            |
| `GET`  | `/api/blog/progress/<task_id>` | 轮询博客任务进度                              |

---

## 五、配置管理

所有配置均通过「系统配置」面板（`/config`）在线完成，无需手动编辑 JSON 文件。面板从上到下依次排列以下卡片，修改任意字段后点击页面底部的「保存配置」即生效。

### 5.1 账号管理（置顶）

- **账号列表** —— 展示全部账号，右侧「启用 / 禁用」徽章点击即可切换该账号是否参与打卡，点击「移除」删除账号。
- **添加账号** —— 底部输入用户名与密码，点击「添加账号」加入列表。
- 密码统一以 `****` 脱敏显示；新增账号保存真实密码，已存在的账号保持 `****` 即保留原密码不变。
- 账号凭据以 Fernet 密文保存在 `backend/accounts.enc`，密钥在 `runtime/.accounts.key`（首次保存时自动生成）。**密钥丢失则账号无法恢复**，请单独备份。从旧版本升级时执行 `python -m backend.accounts_tool encrypt` 完成明文到密文的迁移。

### 5.2 站点设置

- **登录页 URL** —— raricy.com 登录页地址（默认 `https://raricy.com/login`）。该地址只用于请求的 `Referer`，真正的登录接口由下方「登录 API 路径」指定。
- **打卡页 URL** —— 打卡页地址（默认 `https://raricy.com/checkin`）。

### 5.3 CSS 选择器（历史兼容）

页面交互已改用 HTTP API，此卡片为旧版兼容保留，字段不再被引擎读取，无特殊需求时保持默认值即可。

### 5.4 定时设置

- **启用定时打卡** —— 勾选后 APScheduler 按下方时间点每日自动打卡，取消勾选立即停用。
- **当前定时时间** —— 已添加的时间点标签，点击标签右侧 `×` 移除。
- **添加新时间** —— 选择时间后点击「添加」加入定时列表。

### 5.5 签到奖励与批量转账

签到已改为一步式，`POST /api/checkin` 成功即到账固定 **3 条小鱼干**；旧的抽卡设置不再生效，旧日志仍可查看。

在「批量转账」页输入**精确收款用户名**和**每个转出账号的金额**（大于 0，最多 4 位小数），选择全部启用账号或指定账号，然后点击「立即批量转账」。确认框显示收款人、转出账号、每账号金额与预计合计。收款账号自身、同一身份的重复账号会跳过；邮箱登录也按站点返回的真实用户名识别。单个账号失败不影响后续账号。

勾选「启用每日定时转账」，填写北京时间（如 `00:05, 12:00`），点击「保存转账设置」。定时默认关闭，与打卡定时独立；金额、收款人、转出账号和留言均使用保存的设置。所有账号模式会包含以后新增的启用账号。系统需保持运行；若触发时另一个转账批次仍在执行，该次不会启动，原因写入服务器日志。

手工批次携带 UUID；逐账号请求带上游支持的幂等键，网络异常最多使用同键再发一次。同一批次重复请求不会再次扣款，同一批次更改参数会拒绝执行。定时幂等键由北京时间日期、时间槽和真实账号身份生成。页面刷新后同一标签页仍可查看进行中的批次，失败或未确认时使用「用原批次重试」，请勿把重新创建批次当作重试。

记录保存在 `runtime/transfer.db`（随 `RARICY_RUNTIME_DIR` 移动），含上游单号、余额、状态和批次号；请求发送前先记录意图。`待核对` / `未确认` 表示需要核对站点流水，不能按失败直接另发一笔。转账接口无需 core 权限，但账号必须有效且未被禁言。

接口：`POST /api/transfer`（`recipient`, `amount`, `accounts`, 可选 `note`, 必填 UUID `batch_id`），返回 HTTP 202 与 `task_id`；`GET /api/transfer/progress/<task_id>` 查询结果，`GET /api/transfer/status` 查询设置和下次执行，`GET /api/transfer/logs` 查询最近流水。

上游接口依据：[转账路由](https://github.com/raricycms/raricy.com/blob/main/src/app/api/fish/market/transfer/route.ts)、[固定签到奖励](https://github.com/raricycms/raricy.com/blob/main/src/lib/checkin-service.ts)。

### 5.6 API 设置

- **登录 / 打卡 / 转账 / 余额 API 路径** —— 默认 `/api/auth/login`、`/api/checkin`、`/api/fish/market/transfer`、`/api/fish/balance`；余额接口也用于复核登录会话（普通账号不再被 core 门槛误判为登录失败）。
- **博客列表 / 内容 / 点赞 API 路径** —— 博客工具的目录列表、正文、点赞接口（默认 `/api/blogs`、`/api/spider/blogs`、`/api/blogs`；点赞的实际请求是 `<点赞路径>/<文章 id>/like`）。

### 5.7 保存配置

点击页面底部「保存配置」后：

- 账号加密写入 `backend/accounts.enc`（界面显示脱敏，但保留真实密码）
- 其余配置写入 `backend/config.json`
- 后端自动重启调度器，使新的定时设置立即生效

---

## 六、服务器部署（Docker）

本系统可跑在容器里，在 Rocky Linux 9 等服务器上长期无人值守运行。**源码放在服务器上，镜像由服务器本地构建** —— 改代码只需 `git push` + `git pull`，不用再从开发机传镜像包。完整步骤见 [`deploy/DEPLOY.md`](deploy/DEPLOY.md)，这里只概述流程：

```
开发机                                        服务器
git push ────────────────────────────────>  git clone / git pull（仓库公开）
                                              docker compose up -d --build
                                                → 宿主 127.0.0.1:5000
  ssh -L 5000:127.0.0.1:5000 ──────────────>  本地浏览器打开面板
```

四点关键设计取舍：

- **面板不暴露到公网。** 容器端口只发布到宿主机回环，经 SSH 隧道访问 —— 面板本身没有鉴权，能打开它的人就能读你的账号列表、触发打卡、改配置、删账号。
- **必须单进程。** 系统是「Flask + 进程内 APScheduler」；若用多 worker 的 WSGI 服务器，每个 worker 会各起一份调度器，同一账号会被重复打卡。容器直接跑 `python run.py`，这是刻意的。
- **只挂目录，不挂单个文件。** 单文件 bind mount 在内核里是挂载点，`rename(2)` 覆盖挂载点会返回 `EBUSY`；而 `accounts.enc` 是 `.tmp` + `os.replace` 的原子写 —— 挂单文件会让面板的**每一次保存都 500**，本地直接跑却完全正常。可变路径通过 `RARICY_DATA_DIR` / `RARICY_RUNTIME_DIR` / `RARICY_KEY_PATH` 注入（见 `backend/paths.py`），`tests/test_deploy_mounts.py` 钉住这条约束。
- **服务器只在首次构建时需要外网**（拉基础镜像 + pip 装依赖），之后 `git pull` 重建都能命中缓存。国内网络下用 registry 镜像源 + pip 源，配置方式见 `deploy/DEPLOY.md` 第 1.1 节。

账号凭据在服务器上同样是密文，且**密钥单独挂载**（不与数据目录放在一起），这样备份数据目录不会连带把密钥一起带走。

---

## 许可（License）

MIT License

Copyright (c) 2026 yaozitao

特此免费授予任何获得本软件及相关文档文件副本的人不受限制地处理本软件的权利，包括但不限于使用、复制、修改、合并、发布、分发、再许可和/或出售本软件副本，以及允许获得本软件的人这样做，但须符合以下条件：

上述版权声明和本许可声明应包含在本软件的所有副本或主要部分中。

本软件按「原样」提供，不附带任何明示或暗示的保证，包括但不限于对适销性、特定用途适用性和非侵权的保证。

---

## 贡献者（Contributor）

- [yao1145](https://github.com/yao1145) —— 项目作者与主要维护者
