"""Device identity helpers for the remote workbench.

The phone generates a P-256 ECDSA key pair with WebCrypto and keeps the private
key on the device.  Only the public JWK reaches the server.  Every remote
command is signed over its canonical envelope (signature field excluded), so a
relay that can read the command still cannot forge or change it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.core.remote.contracts import CommandEnvelope

P256_COORDINATE_BYTES = 32


class IdentityError(Exception):
    """A key, token or signature is malformed or does not match."""


def _b64url_decode(value: str) -> bytes:
    raw = (value or "").strip()
    if not raw:
        raise IdentityError("缺少 base64url 数据")
    padding = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw + padding)
    except (ValueError, TypeError) as exc:
        raise IdentityError("base64url 数据格式不正确") from exc


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def new_token(bytes_len: int = 32) -> str:
    return secrets.token_urlsafe(bytes_len)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def token_matches(token: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), expected_hash or "")


def normalize_public_key(value: Any) -> dict[str, str]:
    """Validate an EC P-256 public JWK and return the canonical fields."""
    if not isinstance(value, dict):
        raise IdentityError("设备公钥必须是 JWK 对象")
    if str(value.get("kty") or "") != "EC":
        raise IdentityError("设备公钥必须是 EC 密钥")
    if str(value.get("crv") or "") != "P-256":
        raise IdentityError("设备公钥必须使用 P-256 曲线")
    x = str(value.get("x") or "").strip()
    y = str(value.get("y") or "").strip()
    if not x or not y:
        raise IdentityError("设备公钥缺少 x/y 坐标")
    if len(_b64url_decode(x)) != P256_COORDINATE_BYTES or len(_b64url_decode(y)) != P256_COORDINATE_BYTES:
        raise IdentityError("设备公钥坐标长度不正确")
    return {"kty": "EC", "crv": "P-256", "x": x, "y": y}


def canonical_public_key(public_key: dict[str, str]) -> bytes:
    return json.dumps(
        public_key, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def compute_sas(pairing_secret: bytes, public_key: dict[str, str]) -> str:
    """Short verification string derived from the pair secret and device key.

    Both the desktop and the phone can show it; the server never sends the
    secret itself.  Six digits are enough for a human to compare out of band.
    """
    digest = hmac.new(pairing_secret, canonical_public_key(public_key), hashlib.sha256).digest()
    number = int.from_bytes(digest[:8], "big") % 1_000_000
    return f"{number // 1000:03d} {number % 1000:03d}"


def canonical_command_payload(envelope: CommandEnvelope) -> bytes:
    payload = envelope.to_dict()
    payload.pop("signature", None)
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _public_key(public_jwk: dict[str, str]) -> ec.EllipticCurvePublicKey:
    try:
        x = int.from_bytes(_b64url_decode(public_jwk["x"]), "big")
        y = int.from_bytes(_b64url_decode(public_jwk["y"]), "big")
        return ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big"),
        )
    except (KeyError, ValueError) as exc:
        raise IdentityError("设备公钥无法解析") from exc


def _raw_to_der(signature: bytes) -> bytes:
    if len(signature) != 64:
        raise IdentityError("签名长度不正确")
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    return utils.encode_dss_signature(r, s)


def verify_command_signature(
    public_jwk: dict[str, str], envelope: CommandEnvelope,
) -> bool:
    """Verify a WebCrypto-style (raw r||s) or DER ECDSA signature."""
    if not envelope.signature:
        return False
    try:
        signature = _b64url_decode(envelope.signature)
        key = _public_key(public_jwk)
        payload = canonical_command_payload(envelope)
        candidates = [signature]
        try:
            candidates.append(_raw_to_der(signature))
        except IdentityError:
            pass
        for candidate in candidates:
            try:
                key.verify(candidate, payload, ec.ECDSA(hashes.SHA256()))
                return True
            except InvalidSignature:
                continue
        return False
    except (IdentityError, ValueError, TypeError):
        return False


def public_jwk_from_private(private_key: ec.EllipticCurvePrivateKey) -> dict[str, str]:
    numbers = private_key.public_key().public_numbers()
    return {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url_encode(numbers.x.to_bytes(32, "big")),
        "y": _b64url_encode(numbers.y.to_bytes(32, "big")),
    }


__all__ = [
    "IdentityError",
    "canonical_command_payload",
    "compute_sas",
    "hash_token",
    "new_token",
    "normalize_public_key",
    "public_jwk_from_private",
    "token_matches",
    "verify_command_signature",
]
