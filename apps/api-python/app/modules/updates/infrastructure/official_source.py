"""Bounded HTTPS reads from the single official release source."""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from typing import IO, Protocol

from pydantic import ValidationError

from app.bootstrap.outbound_http import outbound_opener
from app.core.exception_diagnostics import capture_exception

from ..application.models import (
    REPOSITORY,
    GHCRReleaseReference,
    Package,
    ReleaseFeed,
    ReleaseNotes,
    ReleaseReference,
    ReleaseSummary,
    UpdateError,
    parse_target,
    version_parts,
)
from .download_stream import download_chunks, download_failure
from .ghcr_source import blob_url, registry_chunks

FEED_ROOT = f"https://raw.githubusercontent.com/{REPOSITORY}/release-feed/"
FEED_URL = f"{FEED_ROOT}index.json"
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
        self.opener = opener

    def chunks(self, url: str, limit: int, seconds: int) -> Iterator[bytes]:
        if url.startswith("https://ghcr.io/v2/gmd170629/ermao-library-updates/"):
            yield from registry_chunks(url, limit, seconds)
            return
        if (
            url != FEED_URL
            and not url.startswith(ASSET_ROOT)
            and not re.fullmatch(re.escape(FEED_ROOT) + r"v\d+\.\d+\.\d+\.md", url)
        ):
            raise UpdateError("UNTRUSTED_SOURCE")
        deadline = time.monotonic() + seconds
        request = urllib.request.Request(
            url,
            headers={"Accept-Encoding": "identity", "User-Agent": "Shuku-Updater/1"},
        )
        try:
            opener = self.opener or outbound_opener(OfficialRedirects())
            with opener.open(request, timeout=10) as response:
                yield from download_chunks(response, limit, deadline)
        except (OSError, http.client.HTTPException) as error:
            raise download_failure(error) from error


class OfficialReleases:
    def __init__(self, transport: ByteSource, protocol: int = 1) -> None:
        self.transport = transport
        self.protocol = protocol

    def _entries(self) -> Iterator[tuple[ReleaseSummary, dict]]:
        feed = json.loads(b"".join(self.transport.chunks(FEED_URL, 1024 * 1024, 30)))
        if feed["schemaVersion"] != 1 or feed["repository"] != REPOSITORY:
            raise ValueError("feed identity")
        releases = feed["releases"]
        if not isinstance(releases, list) or not 0 < len(releases) <= 1000:
            raise ValueError("release count")
        previous = None
        for release in releases:
            summary = ReleaseSummary(
                **{key: release[key] for key in ReleaseSummary.model_fields}
            )
            datetime.fromisoformat(summary.publishedAt)
            parts = version_parts(summary.version)
            if previous is not None and previous <= parts:
                raise ValueError("release ordering")
            previous = parts
            if (
                summary.tag != f"v{summary.version}"
                or summary.notesPath != f"v{summary.version}.md"
                or summary.releaseUrl
                != f"https://github.com/{REPOSITORY}/releases/tag/v{summary.version}"
            ):
                raise ValueError("release identity")
            yield summary, release

    def feed(self) -> ReleaseFeed:
        try:
            return ReleaseFeed(releases=[summary for summary, _ in self._entries()])
        except (ValueError, TypeError, KeyError, ValidationError) as error:
            capture_exception(error, persist=False)
            raise UpdateError("INVALID_MANIFEST") from error

    def notes(self, version: str) -> ReleaseNotes:
        version_parts(version)
        try:
            data = b"".join(
                self.transport.chunks(f"{FEED_ROOT}v{version}.md", 1024 * 1024, 30)
            )
            return ReleaseNotes(markdown=data.decode("utf-8"))
        except UnicodeDecodeError as error:
            capture_exception(error, persist=False)
            raise UpdateError("INVALID_MANIFEST") from error

    def releases(self) -> list[tuple[str, list[Package | ReleaseReference]]]:
        try:
            result = []
            for summary, release in self._entries():
                version = summary.version
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
            capture_exception(error, persist=False)
            raise UpdateError("INVALID_MANIFEST") from error


def package_url(package: Package | ReleaseReference) -> str:
    if isinstance(package, GHCRReleaseReference):
        return blob_url(package.sha256)
    return f"{ASSET_ROOT}v{package.version}/{package.filename}"


def artifact_url(version: str, filename: str) -> str:
    version_parts(version)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,240}", filename):
        raise UpdateError("UNTRUSTED_SOURCE")
    return f"{ASSET_ROOT}v{version}/{filename}"
