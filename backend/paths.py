# backend/paths.py
"""
全项目「可变路径」的唯一来源。

默认值就是仓库本来的本地布局（backend/config.json、runtime/…），所以本地开发、
tests/、accounts_tool 全都不受影响；容器里靠环境变量切到挂载点上，见
docker-compose.yml 与 deploy/DEPLOY.md。

【为什么这些路径必须可注入】docker 把**单个文件**bind mount 进来时，那个文件
在内核里是个挂载点，而 rename(2) 拒绝把别的文件改名覆盖到挂载点上（EBUSY）。
accounts.enc 走的正是 .tmp + os.replace 原子写 —— 于是容器里每一次保存都 500。
所以容器只挂目录，这些文件在容器内的位置就必须能改。
tests/test_deploy_mounts.py 把「不挂单文件」这条约束钉住。
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

# ── 可变数据：会被改写，需要持久化到容器之外 ──────────────
DATA_DIR = Path(os.environ.get("RARICY_DATA_DIR") or BASE_DIR)
CONFIG_PATH = DATA_DIR / "config.json"
ACCOUNTS_ENC_PATH = DATA_DIR / "accounts.enc"
ACCOUNTS_PLAIN_PATH = DATA_DIR / "accounts.json"

# ── 运行期产物：日志、博客库 ──────────────────────────────
RUNTIME_DIR = Path(os.environ.get("RARICY_RUNTIME_DIR") or PROJECT_DIR / "runtime")
LOG_PATH = RUNTIME_DIR / "logs" / "checkin_log.json"
BLOG_DB_PATH = RUNTIME_DIR / "blog.db"

# 密钥默认跟着运行期目录走；RARICY_KEY_PATH 用它挪到只读挂载点，
# 这样备份 data/ 不会连带把密钥一起带走。
KEY_PATH = Path(os.environ.get("RARICY_KEY_PATH") or RUNTIME_DIR / ".accounts.key")

# ── 源码：不随部署环境变化 ────────────────────────────────
FRONTEND_DIR = PROJECT_DIR / "frontend"
