"""Password hashing, opaque tokens and at-rest encryption helpers."""

import base64
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_hasher = PasswordHasher()
API_KEY_PREFIX = "sa_live_"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Deterministic one-way hash for high-entropy tokens (sessions, API keys)."""
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def sign(value: str) -> str:
    key = get_settings().secret_key.encode()
    mac = hmac.new(key, value.encode(), hashlib.sha256).hexdigest()
    return f"{value}.{mac}"


def unsign(signed: str) -> str | None:
    value, _, mac = signed.rpartition(".")
    if not value or not mac:
        return None
    expected = hmac.new(get_settings().secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
    return value if hmac.compare_digest(mac, expected) else None


def _fernet() -> Fernet:
    settings = get_settings()
    if settings.encryption_key:
        return Fernet(settings.encryption_key.encode())
    derived = hashlib.sha256(("signal-atlas:enc:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str | None:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, display_prefix, key_hash). The full key is shown to the user exactly once."""
    public = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full = f"{API_KEY_PREFIX}{public}_{secret}"
    return full, f"{API_KEY_PREFIX}{public}", hash_token(full)
