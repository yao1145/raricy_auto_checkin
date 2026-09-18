# 部署到 Rocky Linux 9（Docker）

把本系统跑在 Rocky 9 服务器上无人值守，面板通过 SSH 隧道访问。

**部署形态：服务器上放一份源码，`git pull` 之后在服务器本地构建镜像。**
开发机不再需要 `docker save` 传 54 MB 的镜像 tar —— 改一行代码只要 `git push` + 服务器 `git pull`。

---

## 关于本文档的验证状态

**已在开发机（Windows + Docker Desktop）实际验证过的：**

- `docker compose build` 构建成功（走清华 pip 源）
- 以「只挂目录」的方式挂载后，容器能解出账号、**面板保存配置返回 200**（旧版单文件挂载下必然 500，见第 8 节）
- 保存后宿主机上的 `accounts.enc` 密文确实被替换、能用密钥解出正确的账号数、无残留 `.tmp`
- 容器以 uid 1000 非 root 运行；`TZ` 正常解析 `Asia/Shanghai`
- `RARICY_DATA_DIR` / `RARICY_RUNTIME_DIR` / `RARICY_KEY_PATH` 三个环境变量在容器内解析到挂载点；日志目录与 `blog.db` 都落在宿主机数据目录里

**未经实测、需你在服务器上确认的：**

- 第 1 节的全部 `dnf` / `systemctl` 命令（开发机是 Windows，无法执行）
- 第 3 节的 SELinux 行为（`chcon` / `restorecon` / `semanage` 在开发机不可用）
- 服务器上 `git clone` 的可达性，以及 `daemon.json` 配的 registry 镜像源
- `download.docker.com` 与 `mirrors.aliyun.com` 在你服务器网络下的可达性

遇到与文档不符的情况，请把实际报错发我，我来更新这份手册。

---

## 0. 前置：先在本机跑通

**不要在没本地跑通的情况下直接上服务器。** 尤其是 `config.json`：仓库里那份已经迁移到 `/api/*` 路径，如果你传一份旧版的上去，打卡会全部 404，而现象看起来像「登录失败」，很难排查。

```bash
# 在开发机，确认这三件事都正常
python run.py --port 5099 --no-browser      # 1. 面板能打开
python -m backend.accounts_tool status      # 2. 密文可解密，账号数正确
python -m unittest discover -s tests -t .   # 3. 测试全绿（含部署约束测试）
```

---

## 1. 服务器安装 Docker CE

Rocky 9 自带的是 **podman**，不是 Docker。`podman-docker` 这个包会提供 `docker` 命令的兼容层，**必须移除**，否则和 docker-ce 冲突。

```bash
# 移除冲突包（没装过会提示 "No match for argument"，可以忽略）
sudo dnf remove -y podman-docker

# 装仓库配置工具
sudo dnf install -y dnf-plugins-core

# 添加 Docker 官方仓库
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo

# 安装（含 compose v2 插件，第 5 节要用 `docker compose` 子命令）
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo systemctl enable --now docker
sudo docker run hello-world          # 验证
sudo usermod -aG docker "$USER"      # 让当前用户免 sudo；需重新登录生效
```

> **若 `download.docker.com` 不可达**（国内网络常见）：改用阿里云的同名仓库。
>
> ```bash
> sudo dnf config-manager --add-repo https://mirrors.aliyun.com/docker-ce/linux/centos/docker-ce.repo
> sudo sed -i 's|download.docker.com|mirrors.aliyun.com/docker-ce|g' /etc/yum.repos.d/docker-ce.repo
> ```
>
> 这一步未经实测，若失败请把报错发我。

### 1.1 让服务器能拉基础镜像

现在镜像是在**服务器上构建**的，所以服务器第一次 build 需要能拉到 `python:3.13-slim`。
配一次 registry 镜像源即可，以后每次 build 都受益：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
EOF
sudo systemctl restart docker
sudo docker pull python:3.13-slim        # 验证：能拉下来再继续
```

> 阿里云、daocloud 等镜像源可用性会变，若上面这个不通，换任一可用的 registry 镜像即可 —— 这个地址只存在服务器上，**不会进仓库**。

---

## 2. 准备目录与源码

```bash
# 2.1 数据与密钥目录（如果之前已经部署过，这两个目录已存在，跳过）
sudo mkdir -p /opt/raricy/data/runtime /opt/raricy/key

# 2.2 源码：仓库是公开的，直接 clone，不需要配密钥或 token
sudo git clone https://github.com/yao1145/raricy_auto_checkin.git /opt/raricy/app

# 2.3 目录属主交给容器 uid
# 容器以 uid 1000 运行，这一步不做会导致容器写不了配置、面板保存报错。
sudo chown -R 1000:1000 /opt/raricy/data
sudo chown -R 1000:1000 /opt/raricy/key
sudo chmod 400 /opt/raricy/key/accounts.key
sudo chmod -R u+rwX /opt/raricy/data

# /opt/raricy/app 保持归 root 或你的登录用户都行 —— 它只是构建上下文，容器不写它
```

### 2.4 灌入初始数据

`config.json` 就在 clone 下来的源码里，直接拷一份过去：

```bash
sudo cp /opt/raricy/app/backend/config.json /opt/raricy/data/config.json
```

`accounts.enc` 和密钥是 gitignore 的，必须从开发机传（**这两个文件不走 git**）：

```bash
# 在开发机
scp backend/accounts.enc      user@server:/tmp/accounts.enc
scp runtime/.accounts.key     user@server:/tmp/accounts.key

# 在服务器
sudo mv /tmp/accounts.enc /opt/raricy/data/accounts.enc
sudo mv /tmp/accounts.key /opt/raricy/key/accounts.key

# 可选：想保留历史打卡日志与博客库就传，想干净开局就跳过
scp -r runtime/logs runtime/blog.db user@server:/tmp/
sudo mv /tmp/logs /opt/raricy/data/runtime/
sudo mv /tmp/blog.db /opt/raricy/data/runtime/

# 传完再统一交属主（第 2.3 步在这里再做一次最保险）
sudo chown -R 1000:1000 /opt/raricy/data
sudo chown 1000:1000 /opt/raricy/key/accounts.key
sudo chmod 400 /opt/raricy/key/accounts.key
```

**密钥和数据分两个目录是设计的关键** —— 这样备份 `data/` 不会连带把密钥一起带走。

---

## 3. SELinux

Rocky 9 默认 **enforcing**。bind mount 不带 SELinux 标签时会被拒绝，容器起不来或挂载点为空。

`docker-compose.yml` 里的两个挂载**已经带了 `:Z` 标签**（`/opt/raricy/data:/app/data:Z` 这种形式），正常情况下你什么都不用做。

> ⚠️ **本节未经实测。** 开发机没有真实 SELinux，以下是按文档撰写的处置方式。若你遇到问题，请把 `sudo ausearch -m avc -ts recent` 的输出发我。

被 SELinux 拒绝时的典型特征：

- 容器启动失败，`docker logs` 里是 `Permission denied` 写 `config.json` 或 `accounts.enc`
- 容器起来了但 `docker exec ... ls /app/data` 是空的
- `sudo ausearch -m avc -ts recent` 能看到 `denied ... comm="docker"` 记录

处置：

```bash
# 首选：确认 compose 里每个挂载都带 :Z（本仓库已带）
grep -n ':Z' /opt/raricy/app/docker-compose.yml

# 备选：给目录打上容器可写的 SELinux 标签
sudo chcon -Rt container_file_t /opt/raricy/data
sudo chcon -Rt container_file_t /opt/raricy/key

# 若系统不支持 chcon 的类型参数，改设布尔值（放宽容器访问本地文件）
sudo setsebool -P container_manage_cgroup true
```

**不建议**为此把 SELinux 改成 permissive 或 disabled —— 那会削弱整台机器的防护，而 `:Z` 标签本来就能解决问题。

---

## 4. 迁移（已经按旧文档部署过的才需要看）

旧部署是「传入镜像 tar + `docker load`」。切到新形态：

```bash
# 1. 停掉旧容器（旧 compose 在 /opt/raricy/）
cd /opt/raricy && sudo docker compose down

# 2. 按第 2 节 clone 源码到 /opt/raricy/app
#    注意：数据目录 /opt/raricy/data 与 /opt/raricy/key 原位保留，一个字节都不用动

# 3. 用新 compose 起来
cd /opt/raricy/app && sudo docker compose up -d --build

# 4. 确认没问题后清理旧产物
cd /opt/raricy && rm -f raricy-checkin-*.tar docker-compose.yml
sudo docker rmi raricy-checkin:1.0.0
```

**宿主机目录结构没有变**，所以数据、密钥、备份脚本、`chown` 全都原地可用。

---

## 5. 启动与访问

```bash
cd /opt/raricy/app
sudo docker compose up -d --build
sudo docker compose ps                            # 应为 running / healthy

curl -s http://127.0.0.1:5000/api/health
# 期望: {"ok":true,"service":"checkin-system"}
```

**如果不通，先看日志再看别的**：

```bash
sudo docker logs --tail 50 raricy-checkin
```

开机自启由两部分保证：`systemctl enable docker`（第 1 节，daemon 自启）+ compose 里的 `restart: unless-stopped`（容器自启）。两者都要有。

容器只发布到宿主机回环（`127.0.0.1:5000`），**面板本身没有任何鉴权** —— 谁能打开页面，谁就能看到你的账号列表、触发打卡、改配置、删账号。所以不要改成对外监听。

在开发机（或任何能 SSH 到服务器的机器）开隧道：

```bash
ssh -L 5000:127.0.0.1:5000 user@server
```

保持这个 SSH 会话开着，然后在本地浏览器打开 `http://127.0.0.1:5000`。

---

## 6. 更新流程

```bash
# 开发机：改完代码推到 GitHub
git push

# 服务器：拉下来重建
cd /opt/raricy/app
sudo git pull
sudo docker compose up -d --build
```

依赖没变时，Docker 会命中缓存层，通常几秒完成。**改代码不需要动数据目录，也不需要重新传任何文件。**

> **易错点**：`docker compose up -d` 是否重建容器取决于镜像有没有变。`--build` 会先构建再比对，所以更新时始终带上它最省心。

旧镜像记得清理，否则磁盘会累积：

```bash
sudo docker image prune -f
```

> 想让服务器完全跟不动 Dockerfile 也不要紧：镜像现在由服务器自己构建，`git pull` 之后 `--build` 即可。

---

## 7. 备份与恢复

**要备份的东西分两类，且必须分开存放：**

| 内容 | 路径 | 说明 |
| --- | --- | --- |
| 数据 | `/opt/raricy/data/` | `config.json`（配置）、`accounts.enc`（账号密文）、`runtime/`（打卡日志 + 博客库） |
| 密钥 | `/opt/raricy/key/accounts.key` | **丢了这些账号就恢复不了，只能重新录入** |

> 源码不用备份 —— 它在 GitHub 上。

```bash
# 数据
sudo tar czf raricy-data-$(date +%F).tar.gz -C /opt/raricy/data .
# 密钥（存到另一个地方，不要和数据放在同一个备份里）
sudo tar czf raricy-key-$(date +%F).tar.gz -C /opt/raricy/key .
```

> 密钥和密文放在一起备份，等于没有加密 —— 加密防的正是「这一个文件单独泄露」。所以这两份备份要放到不同的位置。

恢复：

```bash
cd /opt/raricy/app && sudo docker compose down
sudo tar xzf raricy-data-<日期>.tar.gz -C /opt/raricy/data
sudo tar xzf raricy-key-<日期>.tar.gz -C /opt/raricy/key
sudo chown -R 1000:1000 /opt/raricy/data
sudo chown 1000:1000 /opt/raricy/key/accounts.key
sudo chmod 400 /opt/raricy/key/accounts.key
sudo docker compose up -d
```

---

## 8. 排错

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 本地浏览器打不开面板 | SSH 隧道没开或断了 | 重新 `ssh -L 5000:127.0.0.1:5000 user@server`，确认会话没退出 |
| 面板返回 `accounts_decrypt_failed` | `/opt/raricy/key/accounts.key` 与 `/opt/raricy/data/accounts.enc` **不是配套的一对** | 检查密钥是不是从同一台开发机传的。**修好之前不要在面板上保存配置** |
| 面板保存配置报 500 | 见下面两条 | 先 `sudo docker logs --tail 30 raricy-checkin` 看 Python traceback |
| ↳ traceback 是 `OSError: [Errno 16] Device or resource busy` | **把单个文件 bind mount 进了容器**（旧 compose 的 `accounts.enc:/app/backend/accounts.enc` 就是这样）。挂载点是 mountpoint，`rename(2)` 覆盖它会 `EBUSY`，而 `accounts.enc` 走 `.tmp` + `os.replace` 原子写 | 用当前仓库的 `docker-compose.yml`（只挂 `/opt/raricy/data` 和 `/opt/raricy/key` 两个目录）。不要自己往 compose 里加单文件挂载 |
| ↳ traceback 是 `PermissionError: [Errno 13] Permission denied` | 宿主机目录属主不是 1000 | `sudo chown -R 1000:1000 /opt/raricy/data` |
| 打卡全部失败、提示 404 | 传上去的 `config.json` 是 Next.js 迁移前的旧版本 | 用 `cp /opt/raricy/app/backend/config.json /opt/raricy/data/config.json` 覆盖，重启容器 |
| 容器起来就退出 | 启动异常 | `sudo docker logs --tail 50 raricy-checkin` 看 Python 异常 |
| 容器在跑但挂载目录是空的 | SELinux 拒绝 | 见第 3 节 |
| 调度器没在预期时间打卡 | 时区不对 | `docker exec raricy-checkin date` 应显示北京时间；确认 compose 里 `TZ: Asia/Shanghai` 还在 |
| `docker compose build` 卡在拉 `python:3.13-slim` | 服务器拉不到 Docker Hub | 见第 1.1 节配 registry 镜像源 |
| `docker compose build` 卡在 pip install | 服务器到 PyPI 慢/不通 | `sudo docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/` |
| 面板加载正常、但保存后账号没变 | 旧版 `save_config()` 先写 config.json 再写 accounts.enc，后者失败时前者已落盘，形成半截状态 | 升级到当前版本：写入顺序已调换（accounts 先写，失败则 config.json 不动），且挂载方式已修好 |
| `git pull` 报冲突 | 服务器上直接改过源码 | 别在服务器改代码。`sudo git -C /opt/raricy/app checkout -- .` 丢弃本地改动后重试 |
