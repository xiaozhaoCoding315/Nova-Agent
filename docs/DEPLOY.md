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

域名指向大陆 ECS 的 80/443 端口**必须 ICP 备案**，否则会被接入商阻断。
注意拦截是按 **Host 头**做的，不止 80/443——`http://域名:8000` 同样返回 403
（页面标题 `Non-compliance ICP Filing`），只有直接用 `http://IP:8000` 不受影响。
阿里云控制台搜「ICP 备案」免费办理：填个人/企业信息 → 幕布核验 → 管局审核，约 1–2 周。

> 免费二级域名（如 `xxx.de5.net`）**无法备案**：备案是对根域名办的，办理人必须是
> 该域名的实名持有人；境外注册商（Spaceship / Namecheap / GoDaddy）注册的域名
> 也要先转入国内持牌注册商才能核验通过。

备案期间可继续用 `http://<IP>:8000` 使用，不受影响。

### 3. 解析 + HTTPS

备案通过后：

```bash
# 控制台「云解析 DNS」：两条 A 记录都指向本机
#   @     → 60.205.0.224   （个人博客）
#   nova  → 60.205.0.224   （Nova Agent）

vim .env    # APP_BIND=127.0.0.1；填 TRUSTED_PROXIES（见下，填网段）；如需显示备案号填 ICP_BEIAN
docker compose build app          # ICP_BEIAN 是构建期变量，必须重建镜像
docker compose --profile https up -d
```

`APP_BIND` 是关键的一步：默认 `0.0.0.0` 保留 `http://<IP>:8000` 直连（备案前只能
这样访问，桌面客户端填的地址也是它）；切到 Caddy 后必须改成 `127.0.0.1`。否则
`:8000` 就是一条绕过 HTTPS 的明文旁路——密码和会话 cookie 会在传输中裸奔，
Caddy 签的证书也就形同虚设。

仓库里的 `Caddyfile` 已经按「根域名给博客、`nova.` 子域名给 Nova」写好，
一个 Caddy 同时托管两个站点并各自申请证书。域名换成别的就改 `Caddyfile`
里那两行。

**同一台机器上跑博客时注意**：博客自己的 compose 把 `80:3000` 直接绑在公网，
和 Caddy 抢 80 端口，Caddy 会起不来、证书也签发不了。上线前先让博客让出 80：
把 `Z-Blog/docker-compose.yml` 的 `ports: - "80:3000"` 注释掉（它只在 `blog_default`
网络里，Caddy 通过 `blog-app-1:3000` 访问它），再 `docker compose up -d app`。

Caddy 会自动申请并续期 Let's Encrypt 证书，之后访问 `https://zxycoder.cn` 与
`https://nova.zxycoder.cn`。

**`COOKIE_SECURE` 和 `TRUSTED_PROXIES` 是一组的，别只做一半**：Caddy 终止 TLS 后
内部走 http，uvicorn 默认只采信来自 `127.0.0.1` 的 `X-Forwarded-Proto`（Caddy 容器
不在其中），所以后端的 `request.url.scheme` 是 `http`。此时「按协议自动加 Secure」
能生效，靠的正是 `TRUSTED_PROXIES` 里含 Caddy 的来源——两项都配好，会话 cookie
才会带 `Secure`；只配 Caddy 不配 `TRUSTED_PROXIES`，cookie 就会在明文 HTTP 下
传输。想少一层推断，直接显式写 `COOKIE_SECURE=true` 更稳。

**必须设置 `TRUSTED_PROXIES`**：只有来自白名单的请求，后端才采信
`X-Forwarded-For` / `X-Forwarded-Proto`。不设这一项任何人都能伪造转发头绕过
注册限流和「游客每网络一次」限制。

设了 `APP_BIND=127.0.0.1` 之后，Caddy 通过 docker 内部网络访问 `app:8000`，到达
app 的 peer 是 **Caddy 容器的 IP**——容器重建后会变（`172.18.0.2` → `172.18.0.3`），
**填单个 IP 迟早失效**。`TRUSTED_PROXIES` 支持 CIDR，直接填 compose 给项目分配的
网段，一次填对就永久有效：

```bash
docker network inspect nova-agent_default \
  --format '{{(index .IPAM.Config 0).Subnet}}'   # 例如 172.18.0.0/16
```

```bash
# .env
TRUSTED_PROXIES=172.18.0.0/16
```

填错的症状：所有请求都被算成同一个 IP，登录限流与「游客每网络一次」退化成
全站共享额度。注意 `*` 虽然最省事，但它信任任何来源，只在 app 端口确实只监听
回环时才该用——本项目已经满足这个前提，但填网段更窄、更安全。

登录失败限流默认 `MAX_LOGIN_ATTEMPTS_PER_HOUR=20`，按「来源 IP」和
「IP + 账号」两个维度各算一次：撞库脚本在单个 IP 上会被拖慢，同一个
账号被同一台机器反复试错也会被挡，但别人换 IP 无法把你的账号锁死。
`TRUSTED_PROXIES` 没配对时，所有请求都会被算成反代那一个 IP，
这个限流会变成全站共享额度——所以它和反代配置是一组的。

备案完成前想先内网试用域名，可以用 hosts 绑定测试。

### 4. 备案号展示（备案通过后必做）

大陆网站备案通过后必须在页面底部展示备案号并链接到 `beian.miit.gov.cn`，否则
可能被抽查要求整改。Nova 在登录页页脚和左栏底部各渲染一处，内容来自构建期变量：

```bash
# .env
ICP_BEIAN=粤ICP备12345678号-1
docker compose build app && docker compose up -d --no-build app
```

留空则两处都不渲染（本地运行、桌面端、海外部署都不用填）。**这是构建期变量**：
Vite 在打包时静态替换，改 `.env` 后不重建镜像不会生效。博客那边的备案号要改
`Z-Blog` 自己的页脚组件，并重建它的镜像。

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
- [ ] `COOKIE_SECURE` 显式 `true`，或留空但确认 `TRUSTED_PROXIES` 已含 Caddy 来源（两项缺一，cookie 就会走明文）
- [ ] 走 Caddy 时 `.env` 已设 `APP_BIND=127.0.0.1`（否则 `:8000` 是绕过 HTTPS 的旁路）
- [ ] `TRUSTED_PROXIES` 填本项目 docker 网段（如 `172.18.0.0/16`），不要填容器单个 IP；直连公网时留空
- [ ] 博客让出 80 端口（否则 Caddy 抢不到 80，证书签不下来）
- [ ] 备案通过后 `ICP_BEIAN` 已填并重建镜像
- [ ] `LLM_ALLOW_SERVER_FALLBACK=false`（不想共用服务端 Key 时）
- [ ] `MAX_USERS` 控制在预期规模内；游客额度按需收紧
- [ ] `SANDBOX_ALLOW_NETWORK=false` 保持关闭
