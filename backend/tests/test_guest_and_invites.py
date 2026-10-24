"""Guest once-per-device/IP gating helpers and invite code generation."""
from types import SimpleNamespace

from app.api.v1.auth import _client_ip
from app.core.security.accounts import generate_invite_code


def _request(headers: dict[str, str] | None = None, client_host: str | None = "1.2.3.4"):
    return SimpleNamespace(
        headers={k.lower(): v for k, v in (headers or {}).items()},
        client=SimpleNamespace(host=client_host) if client_host else None,
    )


def test_client_ip_prefers_forwarded_for():
    req = _request({"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
    assert _client_ip(req) == "203.0.113.7"


def test_client_ip_falls_back_to_real_ip_then_peer():
    assert _client_ip(_request({"X-Real-IP": "198.51.100.9"})) == "198.51.100.9"
    assert _client_ip(_request()) == "1.2.3.4"
    assert _client_ip(_request(client_host=None)) == "unknown"


def test_client_ip_truncates_long_values():
    req = _request({"X-Forwarded-For": "a" * 200})
    assert len(_client_ip(req)) == 64


def test_invite_code_format_is_unambiguous():
    for _ in range(20):
        code = generate_invite_code()
        assert code.startswith("NOVA-")
        body = code[5:]
        assert len(body) == 14  # 3 组 4 字符 + 2 个连字符
        assert not any(ch in body for ch in "ILO01")  # 无易混淆字符


def test_invite_codes_are_random():
    assert generate_invite_code() != generate_invite_code()
