"""Shared input validation; does not depend on application or feature services."""

from errors import DomainError


def text(value, maximum, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise DomainError('内容长度不正确')
    return value.strip()
