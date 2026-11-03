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


# ---------- 登录限流 ----------

def test_login_failures_are_throttled_per_ip(monkeypatch):
    from app.api.v1 import auth as auth_mod

    monkeypatch.setattr(settings, "max_login_attempts_per_hour", 3)
    monkeypatch.setattr(settings, "trusted_proxies", "")
    auth_mod._login_ip_buckets.clear()
    auth_mod._login_user_buckets.clear()

    req = _request(peer="198.51.100.9")
    # 前 3 次失败都放行（401 由调用方决定），第 4 次直接 429。
    for _ in range(3):
        auth_mod._check_login_rate(req, "victim")
        auth_mod._record_login_failure(req, "victim")
    with pytest.raises(HTTPException) as exc:
        auth_mod._check_login_rate(req, "victim")
    assert exc.value.status_code == 429


def test_successful_logins_do_not_consume_the_budget(monkeypatch):
    from app.api.v1 import auth as auth_mod

    monkeypatch.setattr(settings, "max_login_attempts_per_hour", 2)
    auth_mod._login_ip_buckets.clear()
    auth_mod._login_user_buckets.clear()

    req = _request(peer="198.51.100.10")
    # 只检查不记账：正常用户反复登录永远不会被自己的额度挡住。
    for _ in range(10):
        auth_mod._check_login_rate(req, "alice")
    assert len(auth_mod._login_ip_buckets["198.51.100.10"]) == 0


def test_login_throttle_does_not_let_a_third_party_lock_an_account(monkeypatch):
    """攻击者换 IP 猛试别人的账号，不能把该账号的正常登录锁死。

    账号桶是 (IP, 账号) 组合：换了 IP 就重新计数，受害者从自己的 IP
    登录不会被别人的失败拖累。
    """
    from app.api.v1 import auth as auth_mod

    monkeypatch.setattr(settings, "max_login_attempts_per_hour", 3)
    auth_mod._login_ip_buckets.clear()
    auth_mod._login_user_buckets.clear()

    attacker = _request(peer="198.51.100.20")
    for _ in range(5):
        auth_mod._record_login_failure(attacker, "victim")

    victim = _request(peer="203.0.113.9")
    auth_mod._check_login_rate(victim, "victim")  # 不应抛 429


def test_login_throttle_can_be_disabled(monkeypatch):
    from app.api.v1 import auth as auth_mod

    monkeypatch.setattr(settings, "max_login_attempts_per_hour", 0)
    auth_mod._login_ip_buckets.clear()
    req = _request(peer="198.51.100.11")
    for _ in range(50):
        auth_mod._record_login_failure(req, "bob")
        auth_mod._check_login_rate(req, "bob")
