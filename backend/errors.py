"""Shared domain errors, independent of storage and HTTP implementations."""


class DomainError(Exception):
    """A safe, user-facing validation failure; never include secrets."""
