"""Anonymous, bounded reads of the official digest-pinned OCI update artifacts."""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from typing import IO, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..application.dependency_release import ReleaseManifest
from ..application.models import GHCRReleaseReference, ReleaseReference, UpdateError

if TYPE_CHECKING:
    from .official_source import ByteSource

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
    opener = urllib.request.build_opener(RegistryRedirects())
    deadline = time.monotonic() + seconds
    try:
        # Fixed anonymous pull scope; never follow an untrusted auth challenge URL.
        with opener.open(TOKEN_URL, timeout=min(10, seconds)) as response:
            token_bytes = response.read(16385)
        if len(token_bytes) > 16384:
            raise UpdateError("SIZE_LIMIT")
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
            total = 0
            while True:
                if time.monotonic() >= deadline:
                    raise UpdateError("DOWNLOAD_TIMEOUT")
                chunk = response.read1(64 * 1024)
                if not chunk:
                    return
                total += len(chunk)
                if total > limit:
                    raise UpdateError("SIZE_LIMIT")
                yield chunk
    except (OSError, urllib.error.URLError, http.client.HTTPException) as error:
        raise UpdateError("DOWNLOAD_FAILED") from error
    except (ValueError, KeyError, TypeError) as error:
        raise UpdateError("INVALID_MANIFEST") from error


class Descriptor(BaseModel):
    model_config = ConfigDict(extra="ignore")
    digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    size: int = Field(gt=0, le=512 * 1024 * 1024)
    annotations: dict[str, str]


class OCIManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schemaVersion: int
    mediaType: str
    artifactType: str
    annotations: dict[str, str]
    layers: list[Descriptor] = Field(max_length=10002)


def validate_registry_manifest(
    source: ByteSource, reference: GHCRReleaseReference
) -> dict[str, Descriptor]:
    raw = b"".join(
        source.chunks(
            f"{REGISTRY}/manifests/{reference.oci_digest}", 4 * 1024 * 1024, 30
        )
    )
    if "sha256:" + hashlib.sha256(raw).hexdigest() != reference.oci_digest:
        raise UpdateError("DIGEST_MISMATCH")
    try:
        manifest = OCIManifest.model_validate_json(raw)
        if (
            manifest.schemaVersion != 2
            or manifest.mediaType != OCI_TYPE
            or manifest.artifactType != ARTIFACT_TYPE
            or manifest.annotations.get("org.opencontainers.image.version")
            != reference.version
            or manifest.annotations.get("io.ermao.platform")
            != reference.environment.platform
        ):
            raise ValueError("OCI identity")
        files: dict[str, Descriptor] = {}
        for layer in manifest.layers:
            name = layer.annotations["org.opencontainers.image.title"]
            if name in files or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._+-]{0,240}", name
            ):
                raise ValueError("OCI filename")
            files[name] = layer
        match_descriptor(files, reference.filename, reference.size, reference.sha256)
        return files
    except (ValueError, KeyError, ValidationError) as error:
        raise UpdateError("INVALID_MANIFEST") from error


def match_descriptor(
    files: dict[str, Descriptor], name: str, size: int, digest: str
) -> None:
    item = files.get(name)
    if item is None or item.size != size or item.digest != f"sha256:{digest}":
        raise UpdateError("INVALID_MANIFEST")


def validate_registry_files(
    files: dict[str, Descriptor],
    reference: ReleaseReference,
    manifest: ReleaseManifest,
) -> None:
    expected = {reference.filename}
    code = manifest.code
    match_descriptor(files, code.filename, code.size, code.sha256)
    expected.add(code.filename)
    for package in manifest.dependencies.packages:
        item = package.artifact
        match_descriptor(files, item.filename, item.size, item.sha256)
        expected.add(item.filename)
    if set(files) != expected:
        raise UpdateError("INVALID_MANIFEST")
