"""Command signing helpers for M1 contract tests.

Production devices will use asymmetric keys (P-256/Ed25519) and the relay will
only route ciphertext.  HMAC is intentionally used here to make the envelope
contract testable without pretending it is the final device-key scheme.
"""
from __future__ import annotations

import hashlib
import hmac
import json

from app.core.remote.contracts import CommandEnvelope


def canonical_command_payload(envelope: CommandEnvelope) -> bytes:
    payload = envelope.to_dict()
    payload.pop("signature", None)
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return raw.encode("utf-8")


def sign_hmac(secret: bytes, envelope: CommandEnvelope) -> str:
    return hmac.new(
        secret,
        canonical_command_payload(envelope),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac(secret: bytes, envelope: CommandEnvelope) -> bool:
    if not envelope.signature:
        return False
    expected = sign_hmac(secret, envelope)
    return hmac.compare_digest(expected, envelope.signature)
