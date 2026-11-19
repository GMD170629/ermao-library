"""One outbound HTTP entry point, with routing evaluated on each redirect hop."""

import ssl
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack
from email.message import Message
from io import BufferedReader, RawIOBase
from typing import cast
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import BaseHandler, OpenerDirector, Request
from urllib.response import addinfourl

import httpx

from app.core.exception_diagnostics import capture_exception


class ProxyTransportError(OSError):
    """HTTP or SOCKS proxy transport failed before receiving an origin response."""


class _Stream(RawIOBase):
    def __init__(self, response: httpx.Response, resources: ExitStack) -> None:
        self._chunks: Iterator[bytes] = response.iter_raw()
        self._remaining = memoryview(b"")
        self._resources = resources

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        try:
            if not self._remaining:
                self._remaining = memoryview(next(self._chunks, b""))
            count = min(len(buffer), len(self._remaining))
            buffer[:count] = self._remaining[:count]
            self._remaining = self._remaining[count:]
            return count
        except httpx.TransportError as error:
            capture_exception(error, persist=False)
            raise URLError(
                ProxyTransportError("Proxy response stream failed")
            ) from error

    def close(self) -> None:
        try:
            self._resources.close()
        finally:
            super().close()


class _ProxyResponse(addinfourl):
    msg: str


def _request_body(request: Request) -> bytes | Iterable[bytes] | None:
    body = request.data
    if body is None or isinstance(body, bytes):
        return body
    if isinstance(body, (bytearray, memoryview)):
        return bytes(body)
    if hasattr(body, "read"):
        return iter(lambda: body.read(64 * 1024), b"")
    return cast(Iterable[bytes], body)


class ProxyHTTPHandler(BaseHandler):
    # The deployment's default ProxyHandler runs next for unmatched requests.
    # urllib's error and redirect processors run for both transports.
    handler_order = 90

    def __init__(
        self, proxy: httpx.Proxy, matches: Callable[[str], tuple[str, ...]]
    ) -> None:
        self._proxy = proxy
        self._matches = matches

    def http_open(self, request: Request) -> addinfourl | None:
        host = urlsplit(request.full_url).hostname
        if not host or not self._matches(host):
            return None
        # A redirect from the deployment proxy can carry its old authentication
        # header. Only HTTPX's configured proxy may add proxy credentials here.
        headers = {
            name: value
            for name, value in request.header_items()
            if name.lower() != "proxy-authorization"
        }
        headers.setdefault("Accept-encoding", "identity")
        resources = ExitStack()
        try:
            client = resources.enter_context(
                httpx.Client(
                    proxy=self._proxy,
                    trust_env=False,
                    verify=ssl.create_default_context(),
                )
            )
            response = resources.enter_context(
                client.stream(
                    request.get_method(),
                    request.full_url,
                    headers=headers,
                    content=_request_body(request),
                    timeout=request.timeout,
                    follow_redirects=False,
                )
            )
            response_headers = Message()
            for name, value in response.headers.multi_items():
                response_headers[name] = value
            wrapped = _ProxyResponse(
                BufferedReader(_Stream(response, resources)),
                response_headers,
                str(response.url),
                response.status_code,
            )
            wrapped.msg = response.reason_phrase
            return wrapped
        except httpx.TransportError as error:
            capture_exception(error, persist=False)
            resources.close()
            raise URLError(ProxyTransportError("Proxy request failed")) from error
        except BaseException as error:
            capture_exception(error, persist=False)
            resources.close()
            raise

    https_open = http_open


def build_outbound_opener(
    *handlers: BaseHandler,
    proxy_handler: ProxyHTTPHandler | None = None,
) -> OpenerDirector:
    active = handlers if proxy_handler is None else (proxy_handler, *handlers)
    return urllib.request.build_opener(*active)
