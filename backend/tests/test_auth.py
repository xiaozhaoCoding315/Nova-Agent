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