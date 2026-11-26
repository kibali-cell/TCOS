"""Encryption of small secrets stored in the database (two-factor secrets).

AES-256-GCM with a random nonce per value. The key comes from ``TCOS_ENCRYPTION_KEY``; only in
development and tests, when it is empty, one is derived from ``SECRET_KEY``. Stored form:
``v1:<base64(nonce + ciphertext)>``. The version prefix leaves room to rotate keys.
"""

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

PREFIX = "v1:"


class DecryptionError(Exception):
    """The stored value is damaged, or the key is not the one it was written with."""


def _key() -> bytes:
    configured = settings.TCOS_ENCRYPTION_KEY
    if configured:
        try:
            key = base64.urlsafe_b64decode(configured + "=" * (-len(configured) % 4))
        except ValueError as exc:
            raise ImproperlyConfigured("TCOS_ENCRYPTION_KEY is not valid base64.") from exc
        if len(key) != 32:
            raise ImproperlyConfigured("TCOS_ENCRYPTION_KEY must decode to exactly 32 bytes.")
        return key
    if not settings.DEBUG:
        raise ImproperlyConfigured("TCOS_ENCRYPTION_KEY is required outside development.")
    return hashlib.sha256(b"tcos-dev-encryption|" + settings.SECRET_KEY.encode()).digest()


def encrypt(plaintext: str, context: str) -> str:
    """``context`` (for example ``2fa:<user id>``) is bound to the value, so a stored secret
    copied to another row will not decrypt."""
    nonce = os.urandom(12)
    sealed = AESGCM(_key()).encrypt(nonce, plaintext.encode(), context.encode())
    return PREFIX + base64.urlsafe_b64encode(nonce + sealed).decode()


def decrypt(stored: str, context: str) -> str:
    if not stored.startswith(PREFIX):
        raise DecryptionError("Unknown format.")
    try:
        raw = base64.urlsafe_b64decode(stored[len(PREFIX) :])
        return AESGCM(_key()).decrypt(raw[:12], raw[12:], context.encode()).decode()
    except (InvalidTag, ValueError) as exc:
        raise DecryptionError("Could not decrypt.") from exc
