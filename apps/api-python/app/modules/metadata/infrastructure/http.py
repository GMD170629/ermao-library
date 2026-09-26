"""Metadata HTTP calls reject redirects instead of hiding extra requests."""

from email.message import Message
from typing import IO, BinaryIO, cast
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: IO[bytes], code: int, msg: str,
                         headers: Message, newurl: str) -> None:
        raise HTTPError(req.full_url, code, "METADATA_REDIRECT_REJECTED", headers, fp)


def urlopen(request: Request, *, timeout: float = 30) -> BinaryIO:
    # Every actual attempt is gated by the provider caller. No hidden retries
    # or redirects may issue unbudgeted requests or forward credentials.
    return cast(BinaryIO, build_opener(_NoRedirect()).open(request, timeout=timeout))


def provider_error_code(error: BaseException) -> str:
    if isinstance(error, ValueError) and str(error) == "SOURCE_RESTRICTED":
        return "SOURCE_RESTRICTED"
    if isinstance(error, HTTPError):
        return "RATE_LIMITED" if error.code == 429 else "AUTHENTICATION" if error.code in {401, 403} else "HTTP_ERROR"
    if isinstance(error, TimeoutError) or (isinstance(error, URLError) and isinstance(error.reason, TimeoutError)):
        return "TIMEOUT"
    if isinstance(error, URLError):
        return "NETWORK_ERROR"
    if isinstance(error, ValueError):
        return "PARSE_ERROR"
    return "PROVIDER_ERROR"
