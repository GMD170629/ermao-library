"""Anonymous, bounded reads of the official digest-pinned OCI update artifacts."""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import IO

from app.bootstrap.outbound_http import outbound_opener
from app.core.exception_diagnostics import capture_exception

from ..application.models import UpdateError
from .download_stream import download_chunks, download_failure

REGISTRY = "https://ghcr.io/v2/gmd170629/ermao-library-updates"
TOKEN_URL = "https://ghcr.io/token?service=ghcr.io&scope=repository%3Agmd170629%2Fermao-library-updates%3Apull"
OCI_TYPE = "application/vnd.oci.image.manifest.v1+json"
ARTIFACT_TYPE = "application/vnd.ermao.update.v2"


class RegistryRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        target = urllib.parse.urlsplit(newurl)
        if (
            not req.full_url.startswith(REGISTRY + "/blobs/sha256:")
            or target.scheme != "https"
            or target.username
            or target.password
            or target.port not in (None, 443)
            or target.hostname != "pkg-containers.githubusercontent.com"
        ):
            raise UpdateError("UNTRUSTED_SOURCE")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


def blob_url(digest: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise UpdateError("INVALID_MANIFEST")
    return f"{REGISTRY}/blobs/sha256:{digest}"


def registry_chunks(url: str, limit: int, seconds: int) -> Iterator[bytes]:
    if not re.fullmatch(
        re.escape(REGISTRY) + r"/(blobs|manifests)/sha256:[a-f0-9]{64}", url
    ):
        raise UpdateError("UNTRUSTED_SOURCE")
    opener = outbound_opener(RegistryRedirects())
    deadline = time.monotonic() + seconds
    try:
        # Fixed anonymous pull scope; never follow an untrusted auth challenge URL.
        with opener.open(TOKEN_URL, timeout=min(10, seconds)) as response:
            token_bytes = b"".join(download_chunks(response, 16384, deadline))
        token = json.loads(token_bytes)["token"]
        if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
            raise UpdateError("INVALID_MANIFEST")
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": OCI_TYPE,
                "Accept-Encoding": "identity",
                "User-Agent": "Shuku-Updater/1",
            },
        )
        with opener.open(request, timeout=min(10, seconds)) as response:
            yield from download_chunks(response, limit, deadline)
    except (OSError, http.client.HTTPException) as error:
        raise download_failure(error) from error
    except (ValueError, KeyError, TypeError) as error:
        capture_exception(error, persist=False)
        raise UpdateError("INVALID_MANIFEST") from error
