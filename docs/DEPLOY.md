# 部署与分发指南

从零把 Nova Agent 部署到一台 Linux 服务器，并让使用者下载桌面客户端安装包。

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
vim .env                         # COOKIE_SECURE=true
docker compose --profile https up -d
```

Caddy 会自动申请并续期 Let's Encrypt 证书，之后用户访问 `https://你的域名`。
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

> 也可以不装任何东西：用 Chrome/Edge 打开站点，地址栏点「安装」即得 PWA 桌面应用。

## 四、日常运维

```bash
docker compose logs -f app        # 看日志
docker compose ps                 # 服务状态
# 升级版本
git pull && docker compose up -d --build
# 备份（停机一致性备份更稳妥）
docker compose exec postgres pg_dump -U postgres nova_agent > backup_$(date +%F).sql
docker run --rm -v nova-agent_pgdata:/data -v $PWD:/backup alpine tar czf /backup/pgdata.tgz /data
docker run --rm -v nova-agent_qdrant_data:/data -v $PWD:/backup alpine tar czf /backup/qdrant.tgz /data
```

数据都在卷里（`pgdata` / `qdrant_data` / `repos_data`）和宿主机 `data/downloads`，重建容器不丢数据。

## 五、安全清单（公开到互联网前逐项确认）

- [ ] `APP_ENV=prod`（compose 默认已设）
- [ ] `SECRET_KEY` 为 32+ 位随机值
- [ ] 两个账号密码已改强密码
- [ ] `COOKIE_SECURE=true`（启用 HTTPS 后）
- [ ] `LLM_ALLOW_SERVER_FALLBACK=false`（不想共用服务端 Key 时）
- [ ] 有域名走 HTTPS（Caddy profile），或在前面加限流反向代理
- [ ] `MAX_USERS` 控制在预期规模内；游客额度按需收紧
- [ ] `SANDBOX_ALLOW_NETWORK=false` 保持关闭
