"""Password hashing and verification utilities using bcrypt."""
from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt. Returns the hash string."""
    salt = bcrypt.gensalt(rounds=10)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Return True if *password* matches *password_hash*."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
