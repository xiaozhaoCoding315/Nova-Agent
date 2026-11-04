"""Guards for the Caddy/HTTPS deployment wiring.

These files only take effect on a deployed server, so a broken wiring would
surface as "certificate never issued" or "every client shares one IP bucket"
— both invisible in unit tests. Keep the cheap structural assertions here.

Each assertion below encodes something verified against a real Caddy container
on the deployment host, not a guess: Caddy reaches the app as a container IP on
the compose network (so TRUSTED_PROXIES needs a subnet, not one address), and
it overwrites X-Forwarded-For but passes X-Real-IP through untouched.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
CADDYFILE = ROOT / "Caddyfile"
DOCKERFILE = ROOT / "backend" / "Dockerfile"


def _compose() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def test_app_bind_defaults_to_public_and_is_narrowable() -> None:
    """默认按 IP:8000 直连（备案前只能这样访问），走 Caddy 时能收窄到回环。

    收窄的理由是明文旁路：Caddy 上了 HTTPS 之后，:8000 若还开着，密码和会话
    cookie 就能在传输中明文泄露，证书也等于白签。
    """
    text = _compose()
    assert '"${APP_BIND:-0.0.0.0}:${BACKEND_PORT:-8000}:8000"' in text
    # 绑回环这件事必须由 APP_BIND 控制，不能写死在 ports 里。
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped.startswith("-"):
            continue
        assert "127.0.0.1:" not in stripped, stripped


def test_caddy_reaches_the_blog_network() -> None:
    """一个 Caddy 托管两个站点，所以要同时接进 nova 与 blog 两个网络。"""
    text = _compose()
    assert "blog_default" in text
    assert "external: true" in text
    caddy = text.split("  caddy:", 1)[1].split("\nvolumes:", 1)[0]
    assert "- default" in caddy
    assert "- blog" in caddy


def test_caddyfile_routes_both_sites() -> None:
    text = CADDYFILE.read_text(encoding="utf-8")
    # 每条站点块都要有 reverse_proxy，且指向正确的容器。
    assert "reverse_proxy app:8000" in text
    assert "reverse_proxy blog-app-1:3000" in text
    # 站点行可以是多主机写法（"a.cn, www.a.cn {"），每个域名都要有证书，
    # 所以这里按逗号拆开计数，而不是只认行首那一个。
    hosts = [
        host.strip()
        for line in text.splitlines()
        for host in re.findall(r"^([a-z0-9.\-,\s]+?)\s*\{", line, flags=re.MULTILINE)
        for host in host.split(",")
        if host.strip()
    ]
    assert len(hosts) >= 3, hosts
    assert any("www." in host for host in hosts), hosts


def test_caddy_overrides_the_spoofable_real_ip_header() -> None:
    """Caddy 覆盖 X-Forwarded-For，但 X-Real-IP 是原样透传的。

    实测：客户端带 `X-Real-IP: 8.8.8.8` 经过 Caddy 后原封不动到达后端。后端
    目前先读 X-Forwarded-For 所以利用不了，但这依赖两处代码的先后顺序——
    任何一次调整都会让伪造的来源 IP 生效，绕过登录限流和「游客每网络一次」。
    在边缘覆盖掉它，就不依赖应用层顺序了。
    """
    text = CADDYFILE.read_text(encoding="utf-8")
    assert "header_up X-Real-IP {remote_host}" in text


def test_icp_number_is_injected_at_build_time() -> None:
    """备案号走 Vite 的构建期替换，只在 Dockerfile 里注入才会生效。"""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "ARG VITE_ICP_BEIAN" in dockerfile
    assert "ENV VITE_ICP_BEIAN=$VITE_ICP_BEIAN" in dockerfile
    # compose 必须把 ICP_BEIAN 作为 build arg 传进去，否则上面两行收不到值。
    assert "VITE_ICP_BEIAN: ${ICP_BEIAN:-}" in _compose()
