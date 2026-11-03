# 部署与分发指南

从零把 Nova Agent 部署到一台 Linux 服务器，并让使用者下载桌面客户端安装包。

> 本文只覆盖云端模式（Docker Compose）。本地 Windows 桌面运行时见 [LOCAL_MODE.md](LOCAL_MODE.md)；`docker-compose.yml` 与云端部署流程不因本地模式改变。

> 最低配置 2 核 2G（单用户 / 小团队演示）；推荐 4C8G 支撑多人。需要已安装 Docker 与 Docker Compose 插件。

## 零、阿里云 ECS（国内）注意事项

> 项目是 Linux 容器栈，请把实例操作系统换成 **Ubuntu 22.04 / 24.04 64 位**（控制台 → 实例 → 更换操作系统）。
> Windows Server 跑不了这套 compose（挂载的是 `/var/run/docker.sock`，且 2G 内存装 Docker Desktop 不可行）。换系统会重置系统盘，新实例无影响。

- **安全组**：控制台 → 安全组 → 入方向添加规则，放行 TCP `8000`（或 80/443）。阿里云默认全禁，不放行外网访问不了。
- **一键脚本**：项目上传到服务器（如 `/opt/nova-agent`）后执行 `sudo bash deploy/setup-aliyun.sh /opt/nova-agent`，脚本会装 Docker（阿里云源）、配镜像加速、建 2G swap（2G 内存构建前端必需）、起服务。
- **带宽 1Mbps 太小**：日常页面没问题（前端 gzip 后约 220KB）；但**首次 `--build` 拉基础镜像和用户下载 96MB 安装包会很慢**。按使用流量计费的实例可临时把带宽峰值调到 20–100Mbps（只多付流量费，单价不变），装完再调回。
- **Docker Hub 拉不动**：脚本已配公共加速镜像；更稳的做法是在阿里云「容器镜像服务」申请个人专属加速地址，替换 `/etc/docker/daemon.json` 第一项。

## 一、部署服务端（约 5 分钟）

```bash
# 1. 拿到代码
git clone <你的仓库地址> nova-agent && cd nova-agent
# （或本地打包上传：git archive HEAD | ssh server "tar -x -C ~/nova-agent"）

# 2. 准备配置
cp .env.docker.example .env
vim .env   # 必改 4 项：DASHSCOPE_API_KEY（或 DEEPSEEK_API_KEY）、SECRET_KEY、ADMIN_PASSWORD、DEMO_PASSWORD

# 3. 启动（首次会构建沙箱/验证镜像，需要 10~20 分钟；之后只 pull 不 build）
docker compose up -d --build

# 4. 验证
curl http://127.0.0.1:8000/api/v1/status/health
```

浏览器打开 `http://<服务器IP>:8000`，用 `ADMIN_USERNAME / ADMIN_PASSWORD` 登录。

**必改项说明**（`APP_ENV=prod` 下弱配置会直接拒绝启动）：

| 变量 | 要求 |
|---|---|
| `SECRET_KEY` | `openssl rand -hex 32` 生成；同时用于加密用户 API Key |
| `ADMIN_PASSWORD` / `DEMO_PASSWORD` | 强密码；公开部署建议 `DEMO_ENABLED` 相关账号不用 demo |
| `LLM_ALLOW_SERVER_FALLBACK` | 公开多用户部署设 `false`，强制每个用户填自己的 Key |
| `REGISTRATION_MODE` | `open` 自助注册 / `invite` 邀请码 / `closed` 仅管理员建号 |

### 邮箱验证码（可选）

线上实例的 `/api/v1/auth/config` 返回 `email_verification: true` 就说明已经启用了
邮箱验证码；这需要 `SMTP_*` 五项都填好，否则注册页会卡在「请输入验证码」。
四组变量缺一不可（`email_enabled` 要求 `SMTP_HOST`、`SMTP_USER`、`SMTP_PASSWORD`、
`SMTP_FROM` 同时存在）：

| 变量 | 说明 |
|---|---|
| `SMTP_HOST` / `SMTP_PORT` | QQ 邮箱 `smtp.qq.com:465`；阿里云邮件推送 `smtpdm.aliyun.com:465` |
| `SMTP_USER` / `SMTP_PASSWORD` | QQ/163 的密码栏填**授权码**，不是登录密码 |
| `SMTP_FROM` | 发件人显示名，如 `"Nova Agent <xxx@qq.com>"` |
| `SMTP_SSL` | 465 端口用 `true`；587 端口设 `false`（走 STARTTLS） |
| `EMAIL_VERIFY_REQUIRED` | 邮件启用后注册是否强制验证码；设 `false` 可先放开注册 |

留空 `SMTP_HOST` 即为未启用邮件，注册页不会要求验证码，找回密码走恢复码。
注意 `.env` 修改后要 `docker compose up -d app` 重建容器才生效。

## 二、绑定域名 + HTTPS

### 1. 买域名（阿里云万网）

在阿里云控制台「域名注册」搜索喜欢的名字，与项目相关的候选：`nova-agent.cn`、`novacoder.cn`、
`use-nova.cn`、`nova-ai.dev` 等（.cn 便宜且个人可备案；先查可用性）。购买后完成实名认证。

### 2. ICP 备案（大陆服务器必需）

域名指向大陆 ECS 的 80/443 端口**必须 ICP 备案**，否则会被接入商阻断（直接用 IP:8000 访问不受影响）。
阿里云控制台搜「ICP 备案」免费办理：填个人/企业信息 → 幕布核验 → 管局审核，约 1–2 周。
备案期间可继续用 `http://60.205.0.224:8000` 使用，不受影响。

### 3. 解析 + HTTPS

备案通过后：

```bash
# 控制台「云解析 DNS」：添加 A 记录  @ → 60.205.0.224（www 同理）
cp Caddyfile.example Caddyfile   # 改成你的域名
vim .env                         # 设置 TRUSTED_PROXIES=<Caddy 容器 IP>
docker compose --profile https up -d
```

Caddy 会自动申请并续期 Let's Encrypt 证书，之后用户访问 `https://你的域名`。
`COOKIE_SECURE` 留空即可：后端按请求协议自动给 Cookie 加 `Secure`。

**必须设置 `TRUSTED_PROXIES`**：只有来自白名单的请求，后端才采信
`X-Forwarded-For` / `X-Forwarded-Proto`。直连 `:8000` 时该端口是公网的，
不设这一项任何人都能伪造转发头绕过注册限流和「游客每网络一次」限制。
查 Caddy 容器在 compose 网络里的地址：

```bash
docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
  "$(docker compose ps -q caddy)"
```

Caddy 与 app 同在默认 bridge 网络时通常是 `172.x.0.x`；也可以直接填 `*`
（仅在 app 端口已改为只监听 127.0.0.1 时使用，见 `Caddyfile.example` 注释）。

备案完成前想先内网试用域名，可以用 hosts 绑定测试。

## 三、桌面客户端分发

桌面端是一个 Electron 壳（`desktop/`），数据仍在服务器，安装包约 80–100MB。

### 方式 A：本机打包（Windows 推荐）

```bash
cd desktop
npm install          # 首次会下载 Electron 二进制
npm run dist:win     # 产出 out/Nova-Agent-Setup-2.0.0.exe
# macOS: npm run dist:mac → out/Nova-Agent-2.0.0.dmg
# Linux: npm run dist:linux → out/Nova-Agent-2.0.0.AppImage
```

### 方式 B：CI 打包

仓库自带 `.github/workflows/desktop.yml`：推一个 `desktop-v*` 标签（如 `desktop-v2.0.0`），
Actions 会为 Windows / macOS / Linux 打包并上传到 Release，下载后进入方式 C。

### 方式 C：发布到服务器的下载页

把安装包放进服务器的 `data/downloads/` 目录（docker-compose 已把它挂进容器）：

```bash
scp desktop/out/Nova-Agent-Setup-2.0.0.exe server:~/nova-agent/data/downloads/
```

无需重启。用户从登录页点「下载桌面客户端」或直接访问 `http://<服务器>:8000/downloads` 下载；
安装后首次启动填服务器地址（如 `http://<服务器IP>:8000`），登录即用。

## 四、日常运维

```bash
docker compose logs -f app        # 看日志
docker compose ps                 # 服务状态
# 升级版本
git pull && docker compose up -d --build
# 备份（PostgreSQL + Qdrant snapshot/体积包 + repos 卷，保留 14 天）
sudo BACKUP_DIR=/opt/nova-backups ./deploy/backup.sh
# 恢复（会 drop 数据库并覆盖 repos/qdrant 卷，需输入 RESTORE 确认）
sudo BACKUP_DIR=/opt/nova-backups ./deploy/restore.sh 2026-10-30_030000
```

数据都在卷里（`pgdata` / `qdrant_data` / `repos_data`）和宿主机 `data/downloads`，重建容器不丢数据。

**让备份自动跑起来**（否则只能靠人记得，出事时手上是几天前的包）：

```bash
sudo cp deploy/nova-backup.service deploy/nova-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nova-backup.timer
systemctl list-timers nova-backup.timer     # 确认下次运行时间
journalctl -u nova-backup.service -n 30     # 查看最近一次结果
```

默认每天 03:20 执行、保留 14 天；部署目录不是 `/opt/nova-agent` 时改
`nova-backup.service` 里的 `WorkingDirectory`。备份脚本现在会在 dump 为空或
gzip 损坏时**直接失败**，不会留下一个看似正常的空包。

### 升级后的索引迁移

本轮升级增加了密钥文件过滤与文件级增量索引。旧索引里可能仍有 `credentials.json` / `secrets.yaml` 的 chunk：

```bash
# 先预览，再实际清理（幂等）
docker exec -w /app nova-agent-app-1 python -m scripts.purge_secret_chunks --dry-run
docker exec -w /app nova-agent-app-1 python -m scripts.purge_secret_chunks
# 或在项目页点一次「重建索引」（现在是增量的；需要全量时调 reindex?force=true）
```

### 服务器安全 E2E / 沙箱 smoke

```bash
docker exec -w /app nova-agent-app-1 python -m scripts.security_e2e
docker exec -w /app nova-agent-app-1 python -m scripts.sandbox_smoke
```

`security_e2e` 覆盖：显式/间接密钥读取、只读 git、取消后无容器残留；`sandbox_smoke` 覆盖：git、非 root、只读根、禁网、Python 执行。

## 五、安全清单（公开到互联网前逐项确认）

- [ ] `APP_ENV=prod`（compose 默认已设）
- [ ] `SECRET_KEY` 为 32+ 位随机值
- [ ] 两个账号密码已改强密码
- [ ] 有域名走 HTTPS（Caddy profile），或在前面加限流反向代理
- [ ] `COOKIE_SECURE` 留空（自动按协议判断）或显式 `true`
- [ ] `TRUSTED_PROXIES` 填反代地址；直连公网时保持留空
- [ ] `LLM_ALLOW_SERVER_FALLBACK=false`（不想共用服务端 Key 时）
- [ ] `MAX_USERS` 控制在预期规模内；游客额度按需收紧
- [ ] `SANDBOX_ALLOW_NETWORK=false` 保持关闭
