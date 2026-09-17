"""Password hashing policy. Kept separate from HTTP routing and business logic."""

import hashlib
import hmac
import secrets

from errors import DomainError

PASSWORD_COST = 600000


def hash_password(password, salt=None):
    if not isinstance(password, str) or not 10 <= len(password) <= 128:
        raise DomainError('密码需为 10–128 个字符')
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256', password.encode(), bytes.fromhex(salt), PASSWORD_COST
    ).hex()
    return salt + ':' + digest


def verify_password(password, stored):
    try:
        return hmac.compare_digest(hash_password(password, stored.split(':')[0]), stored)
    except (ValueError, DomainError, AttributeError):
        return False
