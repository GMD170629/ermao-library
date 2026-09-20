"""Bounded HTTPS reads from the single official release source."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from typing import IO, Protocol

from pydantic import ValidationError

from ..application.models import (
    REPOSITORY,
    GHCRReleaseReference,
    Package,
    ReleaseReference,
    UpdateError,
    parse_target,
    version_parts,
)
from .ghcr_source import blob_url, registry_chunks

FEED_URL = f"https://raw.githubusercontent.com/{REPOSITORY}/release-feed/index.json"
ASSET_ROOT = f"https://github.com/{REPOSITORY}/releases/download/"


class ByteSource(Protocol):
    def chunks(self, url: str, limit: int, seconds: int) -> Iterator[bytes]: ...


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        parsed = urllib.parse.urlsplit(newurl)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.hostname
            not in {
                "release-assets.githubusercontent.com",
                "objects.githubusercontent.com",
            }
            or not req.full_url.startswith(
                (
                    ASSET_ROOT,
                    "https://release-assets.githubusercontent.com/",
                    "https://objects.githubusercontent.com/",
                )
            )
        ):
            raise UpdateError("UNTRUSTED_SOURCE")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class OfficialHTTP:
    def __init__(self, opener: urllib.request.OpenerDirector | None = None) -> None:
        self.opener = opener or urllib.request.build_opener(OfficialRedirects())

    def chunks(self, url: str, limit: int, seconds: int) -> Iterator[bytes]:
        if url.startswith("https://ghcr.io/v2/gmd170629/ermao-library-updates/"):
            yield from registry_chunks(url, limit, seconds)
            return
        if url != FEED_URL and not url.startswith(ASSET_ROOT):
            raise UpdateError("UNTRUSTED_SOURCE")
        deadline = time.monotonic() + seconds
        request = urllib.request.Request(
            url,
            headers={"Accept-Encoding": "identity", "User-Agent": "Shuku-Updater/1"},
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                total = 0
                while True:
                    if time.monotonic() >= deadline:
                        raise UpdateError("DOWNLOAD_TIMEOUT")
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise UpdateError("SIZE_LIMIT")
                    yield chunk
        except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
            raise UpdateError("DOWNLOAD_FAILED") from error


class OfficialReleases:
    def __init__(self, transport: ByteSource, protocol: int = 1) -> None:
        self.transport = transport
        self.protocol = protocol

    def releases(self) -> list[tuple[str, list[Package | ReleaseReference]]]:
        try:
            feed = json.loads(
                b"".join(self.transport.chunks(FEED_URL, 1024 * 1024, 30))
            )
            if feed["schemaVersion"] != 1 or feed["repository"] != REPOSITORY:
                raise ValueError("feed identity")
            releases = feed["releases"]
            if not isinstance(releases, list) or not 0 < len(releases) <= 1000:
                raise ValueError("release count")
            result = []
            previous = None
            for release in releases:
                datetime.fromisoformat(release["publishedAt"])
                version = release["version"]
                parts = version_parts(version)
                if previous is not None and previous <= parts:
                    raise ValueError("release ordering")
                previous = parts
                if (
                    release["tag"] != f"v{version}"
                    or release["notesPath"] != f"v{version}.md"
                    or release["releaseUrl"]
                    != f"https://github.com/{REPOSITORY}/releases/tag/v{version}"
                ):
                    raise ValueError("release identity")
                packages = [
                    parse_target(p)
                    for p in release.get(
                        "appPackages" if self.protocol == 1 else "dependencyReleases",
                        [],
                    )
                ]
                if self.protocol != 1 and "ghcrDependencyReleases" in release:
                    packages = [
                        parse_target(p) for p in release["ghcrDependencyReleases"]
                    ]
                if any(p.version != version for p in packages) or len(
                    {p.environment.platform for p in packages}
                ) != len(packages):
                    raise ValueError("package identity")
                result.append((version, packages))
            return result
        except (ValueError, TypeError, KeyError, ValidationError) as error:
            raise UpdateError("INVALID_MANIFEST") from error


def package_url(package: Package | ReleaseReference) -> str:
    if isinstance(package, GHCRReleaseReference):
        return blob_url(package.sha256)
    return f"{ASSET_ROOT}v{package.version}/{package.filename}"


def artifact_url(version: str, filename: str) -> str:
    version_parts(version)
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,240}", filename):
        raise UpdateError("UNTRUSTED_SOURCE")
    return f"{ASSET_ROOT}v{version}/{filename}"
