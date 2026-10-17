"""Password hashing (Argon2), tokens, secret encryption and TOTP."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_config

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # constant-ish time: still run a hash to avoid user enumeration by timing
        _hasher.hash(password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pin_lookup(tenant_slug: str, pin: str) -> str:
    """Deterministic keyed hash so a PIN can be looked up; the PIN itself is also Argon2-hashed."""
    key = get_config().secret_key.encode()
    return hmac.new(key, f"{tenant_slug}:{pin}".encode(), hashlib.sha256).hexdigest()


def _fernet() -> Fernet:
    key = get_config().encryption_key
    if not key:
        # derive a stable key from the secret in development; production must set KP_ENCRYPTION_KEY
        digest = hashlib.sha256(get_config().secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(cipher: str | None) -> str | None:
    if not cipher:
        return None
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except InvalidToken:
        return None


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name="Kübelpflanzen-Planer")


def verify_totp(secret: str | None, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)
