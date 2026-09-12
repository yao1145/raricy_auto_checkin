# 部署到 Rocky Linux 9（Docker）

把本系统打包成镜像，在 Rocky 9 服务器上无人值守运行，面板通过 SSH 隧道访问。

---

## 关于本文档的验证状态

**已在开发机（Windows + Docker Desktop）实际验证过的：**

- `docker build --platform linux/amd64` 构建成功，镜像 231MB
- `docker save` → 删除本地镜像 → `docker load` 往返成功，tar 54MB，载入后 tag 与 `docker-compose.yml` 引用一致
- 镜像内容干净：无 `accounts.json` / `accounts.enc` / `runtime/` 数据
- 容器以 uid 1000 非 root 运行；`tzdata` 正常解析 `Asia/Shanghai`
- 挂载后容器能解出账号、真实打卡成功、日志落到宿主机挂载目录
- **嵌套挂载成立**：密钥文件从独立目录挂进已被挂载的 `/app/runtime` 内，与 data 目录的内容共存
- `:Z` 标签在 Docker Desktop 上是 no-op（加不加都能跑）
- 容器重启恰好注册一次定时任务，无重复调度器

**未经实测、需你在服务器上确认的：**

- 第 1 节的全部 `dnf` / `systemctl` 命令（开发机是 Windows，无法执行）
- 第 3 节的 SELinux 行为（`chcon` / `restorecon` / `semanage` 在开发机不可用）
- `download.docker.com` 与 `mirrors.aliyun.com` 在你服务器网络下的可达性

遇到与文档不符的情况，请把实际报错发我，我来更新这份手册。

---

## 0. 前置：先在本机跑通

**不要在没本地跑通的情况下直接上服务器。** 尤其是 `config.json`：仓库里那份已经迁移到 `/api/*` 路径，如果你传一份旧版的上去，打卡会全部 404，而现象看起来像「登录失败」，很难排查。

```bash
# 在开发机，确认这三件事都正常
python run.py --port 5099 --no-browser      # 面板能打开
python -m backend.accounts_tool status      # 密文可解密，账号数正确
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

# 安装（含 compose v2 插件，第 4 节要用 `docker compose` 子命令）
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

**服务器全程不需要访问 Docker Hub** —— 镜像由开发机 `docker save` 传过来 `docker load`，所以第 3 节那种「国内拉不动基础镜像」的问题在这里不会出现。

---

## 2. 准备目录与数据

```bash
sudo mkdir -p /opt/raricy/data/runtime /opt/raricy/key
```

从开发机传三个文件上去（**密钥和数据分两个目录**，这是设计的关键）：

```bash
# 在开发机执行
scp backend/config.json          user@server:/opt/raricy/data/config.json
scp backend/accounts.enc         user@server:/opt/raricy/data/accounts.enc
scp runtime/.accounts.key        user@server:/opt/raricy/key/accounts.key
scp raricy-checkin-1.0.0.tar     user@server:/opt/raricy/
scp docker-compose.yml           user@server:/opt/raricy/
```

`runtime/` 目录可以传也可以不传：想要保留历史打卡日志和博客库就传（`scp -r runtime/ user@server:/opt/raricy/data/`），想要干净开局就跳过。

回到服务器设置属主与权限 —— **容器以 uid 1000 运行，属主不对会导致面板保存配置失败**：

```bash
sudo chown -R 1000:1000 /opt/raricy/data
sudo chown 1000:1000 /opt/raricy/key/accounts.key
sudo chmod 400 /opt/raricy/key/accounts.key
sudo chmod -R u+rwX /opt/raricy/data
```

---

## 3. SELinux

Rocky 9 默认 **enforcing**。bind mount 不带 SELinux 标签时会被拒绝，容器起不来或挂载点为空。

`docker-compose.yml` 里的四个挂载**已经带了 `:Z` 标签**（`/opt/raricy/data/config.json:/app/backend/config.json:Z` 这种形式），正常情况下你什么都不用做。

> ⚠️ **本节未经实测。** 开发机没有真实 SELinux，以下是按文档撰写的处置方式。若你遇到问题，请把 `sudo ausearch -m avc -ts recent` 的输出发我。

被 SELinux 拒绝时的典型特征：

- 容器启动失败，`docker logs` 里是 `Permission denied` 写 `config.json` 或 `accounts.enc`
- 容器起来了但 `docker exec ... ls /app/runtime` 是空的
- `sudo ausearch -m avc -ts recent` 能看到 `denied ... comm="docker"` 记录

处置：

```bash
# 首选：确认 compose 里每个挂载都带 :Z（本仓库已带）
grep -n ':Z' /opt/raricy/docker-compose.yml

# 备选：给目录打上容器可写的 SELinux 标签
sudo chcon -Rt container_file_t /opt/raricy/data
sudo chcon -Rt container_file_t /opt/raricy/key

# 若系统不支持 chcon 的类型参数，改设布尔值（放宽容器访问本地文件）
sudo setsebool -P container_manage_cgroup true
```

**不建议**为此把 SELinux 改成 permissive 或 disabled —— 那会削弱整台机器的防护，而 `:Z` 标签本来就能解决问题。

---

## 4. 加载镜像并启动

```bash
cd /opt/raricy
sudo docker load -i raricy-checkin-1.0.0.tar     # 输出 Loaded image: raricy-checkin:1.0.0

sudo docker compose up -d
sudo docker compose ps                            # 应为 running / healthy
```

等健康检查通过（约 15 秒）：

```bash
curl -s http://127.0.0.1:5000/api/health
# 期望: {"ok":true,"service":"checkin-system"}
```

**如果不通，先看日志再看别的**：

```bash
sudo docker logs --tail 50 raricy-checkin
```

开机自启由两部分保证：`systemctl enable docker`（第 1 节，daemon 自启）+ compose 里的 `restart: unless-stopped`（容器自启）。两者都要有。

---

## 5. 访问面板

容器只发布到宿主机回环（`127.0.0.1:5000`），**面板本身没有任何鉴权** —— 谁能打开页面，谁就能看到你的账号列表、触发打卡、改配置、删账号。所以不要改成对外监听。

在开发机（或任何能 SSH 到服务器的机器）开隧道：

```bash
ssh -L 5000:127.0.0.1:5000 user@server
```

保持这个 SSH 会话开着，然后在本地浏览器打开 `http://127.0.0.1:5000`。

---

## 6. 更新流程

```bash
# 1. 开发机：重新构建并指定新版本号
docker build --platform linux/amd64 -t raricy-checkin:1.0.1 .
docker save raricy-checkin:1.0.1 -o raricy-checkin-1.0.1.tar
scp raricy-checkin-1.0.1.tar user@server:/opt/raricy/

# 2. 服务器：改 compose 里的 image tag，再加载重启
cd /opt/raricy
sudo sed -i 's|raricy-checkin:1.0.0|raricy-checkin:1.0.1|' docker-compose.yml
sudo docker load -i raricy-checkin-1.0.1.tar
sudo docker compose up -d
```

> **易错点**：`docker compose up -d` 是否重建容器取决于 `image` 字段指向的 tag 有没有变。如果你 `docker build` 后仍用**同一个 tag** 覆盖，`compose up` 可能什么都不做、继续跑旧容器。每次更新都升版本号，或显式 `docker compose up -d --force-recreate`。

旧镜像记得清理，否则磁盘会累积：

```bash
sudo docker image prune -f
```

---

## 7. 备份与恢复

**要备份的东西分两类，且必须分开存放：**

| 内容 | 路径 | 说明 |
|---|---|---|
| 数据 | `/opt/raricy/data/` | `config.json`（配置）、`accounts.enc`（账号密文）、`runtime/`（打卡日志 + 博客库） |
| 密钥 | `/opt/raricy/key/accounts.key` | **丢了这些账号就恢复不了，只能重新录入** |

```bash
# 数据
sudo tar czf raricy-data-$(date +%F).tar.gz -C /opt/raricy/data .
# 密钥（存到另一个地方，不要和数据放在同一个备份里）
sudo tar czf raricy-key-$(date +%F).tar.gz -C /opt/raricy/key .
```

> 密钥和密文放在一起备份，等于没有加密 —— 加密防的正是「这一个文件单独泄露」。所以这两份备份要放到不同的位置。

恢复：

```bash
sudo docker compose down
sudo tar xzf raricy-data-<日期>.tar.gz -C /opt/raricy/data
sudo tar xzf raricy-key-<日期>.tar.gz -C /opt/raricy/key
sudo chown -R 1000:1000 /opt/raricy/data
sudo chown 1000:1000 /opt/raricy/key/accounts.key
sudo docker compose up -d
```

---

## 8. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 本地浏览器打不开面板 | SSH 隧道没开或断了 | 重新 `ssh -L 5000:127.0.0.1:5000 user@server`，确认会话没退出 |
| 面板返回 `accounts_decrypt_failed` | `/opt/raricy/key/accounts.key` 与 `/opt/raricy/data/accounts.enc` **不是配套的一对** | 检查密钥是不是从同一台开发机传的。**修好之前不要在面板上保存配置** —— 现在的设计保证它不会覆盖你的数据，但配置也不会保存成功 |
| 打卡全部失败、提示 404 | 传上去的 `config.json` 是 Next.js 迁移前的旧版本 | 用开发机当前的 `backend/config.json` 覆盖，重启容器 |
| 面板保存配置报错 / 写不进去 | 宿主机目录属主不是 1000 | `sudo chown -R 1000:1000 /opt/raricy/data` |
| 容器起来就退出 | 启动异常 | `sudo docker logs --tail 50 raricy-checkin` 看 Python 异常 |
| 容器在跑但挂载目录是空的 | SELinux 拒绝 | 见第 3 节 |
| 调度器没在预期时间打卡 | 时区不对 | `docker exec raricy-checkin date` 应显示北京时间；确认 compose 里 `TZ: Asia/Shanghai` 还在 |
| `docker compose up -d` 后还是旧行为 | tag 没变，容器没重建 | 升版本号，或 `docker compose up -d --force-recreate` |
