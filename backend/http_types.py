"""Small HTTP contracts, independent of server bootstrap and business services."""

from dataclasses import dataclass
from typing import Any, Callable, Mapping
from errors import DomainError

COOKIE = '__Host-jamie_session'
UNHANDLED = object()


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class RequestData(dict):
    def __missing__(self, key):
        # Missing user-supplied fields are validation failures; internal KeyErrors
        # are programming errors and must not be disguised as bad user input.
        raise DomainError('缺少必要的请求参数')


@dataclass(frozen=True)
class RequestContext:
    app: Any
    path: str
    raw_path: str
    ip: str
    data: RequestData
    account: Any
    token: str
    write: bool
    headers: Mapping
    reply: Callable
