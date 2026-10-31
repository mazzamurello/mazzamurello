"""Passwords, session tokens and identifiers (AUTH-001, AUTH-004).

Argon2id hashing is CPU-bound, so it runs in a worker thread and never blocks
the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_HASHER = PasswordHasher()
# Verified when the username is unknown, so that the answer takes as long as
# for a known user with a wrong password.
_UNKNOWN_USER_HASH = _HASHER.hash(secrets.token_urlsafe(32))

TOKEN_BYTES = 32


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_HASHER.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Whether `password` matches; an unknown user (no hash) never matches, in the same time."""

    def verify() -> bool:
        try:
            return _HASHER.verify(password_hash or _UNKNOWN_USER_HASH, password) and password_hash is not None
        except (VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(verify)


def new_token() -> str:
    """An opaque session token of 256 random bits (ADR-0025)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> bytes:
    """What the database stores for a token: its SHA-256."""
    return hashlib.sha256(token.encode()).digest()


def uuid7() -> uuid.UUID:
    """A version 7 UUID: 48 bits of Unix time in milliseconds, then random bits."""
    value = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    value = (value & ~(0xF << 76)) | (0x7 << 76)
    value = (value & ~(0x3 << 62)) | (0x2 << 62)
    return uuid.UUID(int=value)
