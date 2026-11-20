"""Keep HTTP transfer failures distinct from update artifact verification."""

import http.client
import ssl
import time
from collections.abc import Iterator
from typing import Protocol
from urllib.error import URLError

import httpx

from ..application.models import UpdateError


class DownloadResponse(Protocol):
    def read1(self, size: int, /) -> bytes: ...


def download_chunks(
    response: DownloadResponse, limit: int, deadline: float
) -> Iterator[bytes]:
    total = 0
    while True:
        if time.monotonic() >= deadline:
            raise UpdateError("DOWNLOAD_TIMEOUT")
        chunk = response.read1(min(64 * 1024, limit - total + 1))
        if not chunk:
            # urllib's bounded read can return EOF with HTTP Content-Length bytes outstanding.
            if isinstance(response, http.client.HTTPResponse) and response.length:
                raise http.client.IncompleteRead(b"", response.length)
            return
        total += len(chunk)
        if total > limit:
            raise UpdateError("SIZE_LIMIT")
        yield chunk


def download_failure(error: OSError | http.client.HTTPException) -> UpdateError:
    reason = error.reason if isinstance(error, URLError) else error
    cause = error.__cause__
    if isinstance(reason, TimeoutError) or isinstance(cause, httpx.TimeoutException):
        return UpdateError("DOWNLOAD_TIMEOUT")
    if isinstance(
        reason,
        (
            http.client.IncompleteRead,
            ConnectionResetError,
            ConnectionAbortedError,
            ssl.SSLEOFError,
        ),
    ) or isinstance(cause, (httpx.ReadError, httpx.RemoteProtocolError)):
        return UpdateError("DOWNLOAD_INTERRUPTED")
    return UpdateError("DOWNLOAD_FAILED")
