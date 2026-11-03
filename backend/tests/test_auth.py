"""Auth primitives: password hashing, JWT round-trip, rate limiting."""
import time

import jwt
import pytest
from fastapi import HTTPException

from app.config import settings
from app.core.security.auth import create_token, hash_password, verify_password
from app.core.security.limits import _rate_check, messages_last_hour


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert h != "s3cret"
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)


def test_password_hash_is_salted():
    assert hash_password("same") != hash_password("same")


def test_verify_password_handles_garbage_hash():
    assert not verify_password("x", "not-a-bcrypt-hash")


def test_jwt_roundtrip_carries_identity():
    token = create_token({"id": 7, "username": "admin", "role": "admin"})
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    assert payload["sub"] == "7"
    assert payload["username"] == "admin"
    assert payload["role"] == "admin"
    assert payload["exp"] > time.time()


def test_jwt_tamper_rejected():
    token = create_token({"id": 1, "username": "demo", "role": "demo"})
    tampered = token[:-3] + ("a" if token[-3] != "a" else "b") + token[-2:]
    with pytest.raises(jwt.PyJWTError):
        jwt.decode(tampered, settings.secret_key, algorithms=["HS256"])


def test_jwt_signed_with_other_key_rejected():
    bad = jwt.encode({"sub": "1", "exp": time.time() + 60}, "other-key", algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        jwt.decode(bad, settings.secret_key, algorithms=["HS256"])


def test_rate_limit_blocks_over_limit():
    user = {"id": 999001, "role": "demo", "username": "rl-test"}
    for _ in range(3):
        _rate_check(user, "chain", 3)
    with pytest.raises(HTTPException) as exc:
        _rate_check(user, "chain", 3)
    assert exc.value.status_code == 429


def test_messages_last_hour_counts_used_slots():
    user = {"id": 999002, "role": "demo", "username": "rl-test2"}
    assert messages_last_hour(user["id"]) == 0
    _rate_check(user, "chat", 5)
    _rate_check(user, "chat", 5)
    assert messages_last_hour(user["id"]) == 2

# ---------- 反代信任与 cookie 策略 ----------

def _request(headers: dict[str, str] | None = None, peer: str | None = "203.0.113.7",
             scheme: str = "http"):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "scheme": scheme,
        "path": "/api/v1/auth/login",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (peer, 12345) if peer else None,
        "server": ("127.0.0.1", 8000),
        "root_path": "",
    }
    return Request(scope)


def test_forwarded_for_is_ignored_unless_the_peer_is_a_trusted_proxy(monkeypatch):
    from app.api.v1.auth import _client_ip

    monkeypatch.setattr(settings, "trusted_proxies", "")
    spoofed = _request({"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"})
    # 没有配置反代时，伪造的转发头必须被丢弃，否则限流可以被无限绕过。
    assert _client_ip(spoofed) == "203.0.113.7"

    monkeypatch.setattr(settings, "trusted_proxies", "127.0.0.1,10.0.0.0/8")
    trusted = _request({"X-Forwarded-For": "1.2.3.4, 9.9.9.9"}, peer="127.0.0.1")
    assert _client_ip(trusted) == "1.2.3.4"


def test_trusted_proxy_list_parses_comma_separated_entries(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxies", " 127.0.0.1 , ,10.1.2.3 ")
    assert settings.trusted_proxy_list == ["127.0.0.1", "10.1.2.3"]


def test_cookie_secure_follows_the_request_scheme_by_default(monkeypatch):
    from app.api.v1.auth import _cookie_secure

    monkeypatch.setattr(settings, "cookie_secure", None)
    assert _cookie_secure(_request(scheme="https")) is True
    assert _cookie_secure(_request(scheme="http")) is False


def test_cookie_secure_explicit_setting_wins(monkeypatch):
    from app.api.v1.auth import _cookie_secure

    # 反代在 TLS 终止、内部走 http 时，运维可以强制打开 Secure。
    monkeypatch.setattr(settings, "cookie_secure", True)
    assert _cookie_secure(_request(scheme="http")) is True


def test_wildcard_trusts_every_peer(monkeypatch):
    from app.api.v1.auth import _client_ip

    monkeypatch.setattr(settings, "trusted_proxies", "*")
    # 只有 app 端口只监听回环时才允许这么配（Caddy 与本机同栈）。
    assert _client_ip(_request({"X-Forwarded-For": "1.2.3.4"})) == "1.2.3.4"
