"""OCI source identity, bounded streaming and persisted target coverage."""

import hashlib
import io
import json
import urllib.request
from email.message import Message

import pytest

from app.modules.updates.application.models import (
    GHCRReleaseReference,
    PreparationState,
    UpdateError,
)
from app.modules.updates.infrastructure import ghcr_source as ghcr
from app.modules.updates.infrastructure.official_source import OfficialReleases


def fixture():
    reference = {
        "version": "1.1.0",
        "format": 2,
        "environment": {
            "format": 1,
            "platform": "linux-x86_64",
            "compatibility": "a" * 64,
        },
        "filename": "shuku-1.1.0-linux-x86_64-v2.json",
        "size": 2,
        "sha256": hashlib.sha256(b"{}").hexdigest(),
    }
    manifest = {
        "schemaVersion": 2,
        "mediaType": ghcr.OCI_TYPE,
        "artifactType": ghcr.ARTIFACT_TYPE,
        "annotations": {
            "org.opencontainers.image.version": "1.1.0",
            "io.ermao.platform": "linux-x86_64",
        },
        "layers": [
            {
                "size": 2,
                "digest": "sha256:" + reference["sha256"],
                "annotations": {
                    "org.opencontainers.image.title": reference["filename"]
                },
            }
        ],
    }
    raw = json.dumps(manifest).encode()
    return GHCRReleaseReference(
        **reference, oci_digest="sha256:" + hashlib.sha256(raw).hexdigest()
    ), raw


class Source:
    def __init__(self, raw):
        self.raw = raw

    def chunks(self, url, limit, seconds):
        yield self.raw


def test_digest_identity_and_persisted_target():
    ref, raw = fixture()
    files = ghcr.validate_registry_manifest(Source(raw), ref)
    assert files[ref.filename].size == 2
    state = PreparationState(phase="ready", target=ref)
    restored = PreparationState.model_validate_json(state.model_dump_json())
    assert isinstance(restored.target, GHCRReleaseReference)
    assert restored.target.oci_digest == ref.oci_digest
    with pytest.raises(UpdateError, match="DIGEST_MISMATCH"):
        ghcr.validate_registry_manifest(Source(raw + b" "), ref)
    with pytest.raises(UpdateError, match="INVALID_MANIFEST"):
        ghcr.match_descriptor(files, ref.filename, 3, ref.sha256)


def test_feed_legacy_clients_do_not_parse_ghcr_references():
    ref, _ = fixture()
    feed = {
        "schemaVersion": 1,
        "repository": "GMD170629/ermao-library",
        "releases": [
            {
                "version": "1.1.0",
                "tag": "v1.1.0",
                "notesPath": "v1.1.0.md",
                "publishedAt": "2026-09-16T00:00:00Z",
                "releaseUrl": "https://github.com/GMD170629/ermao-library/releases/tag/v1.1.0",
                "ghcrDependencyReleases": [ref.model_dump()],
            }
        ],
    }
    source = Source(json.dumps(feed).encode())
    assert OfficialReleases(source, 1).releases() == [("1.1.0", [])]
    assert OfficialReleases(source, 2).releases()[0][1] == [ref]


def test_redirect_strips_auth_and_rejects_other_hosts():
    request = urllib.request.Request(
        ghcr.blob_url("a" * 64), headers={"Authorization": "Bearer secret"}
    )
    redirects = ghcr.RegistryRedirects()
    result = redirects.redirect_request(
        request,
        io.BytesIO(),
        307,
        "redirect",
        Message(),
        "https://pkg-containers.githubusercontent.com/blob?signature=x",
    )
    assert result.get_header("Authorization") is None
    for url in [
        "https://evil.example/blob",
        "http://pkg-containers.githubusercontent.com/blob",
        "https://ghcr.io.evil.example/blob",
        "https://user@pkg-containers.githubusercontent.com/blob",
    ]:
        with pytest.raises(UpdateError, match="UNTRUSTED_SOURCE"):
            redirects.redirect_request(
                request, io.BytesIO(), 307, "redirect", Message(), url
            )


class Response(io.BytesIO):
    def read1(self, size):
        assert size <= 65536
        return super().read(size)


def test_stream_consumed_before_completion_and_limits(monkeypatch):
    data = b"x" * 200000
    calls = []
    body = Response(data)

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return (
                Response(b'{"token":"anonymous"}') if isinstance(request, str) else body
            )

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    chunks = ghcr.registry_chunks(ghcr.blob_url("a" * 64), len(data), 30)
    assert len(next(chunks)) == 65536
    assert body.tell() == 65536
    chunks.close()
    assert body.closed
    assert calls[0] == ghcr.TOKEN_URL
    body = Response(data)
    with pytest.raises(UpdateError, match="SIZE_LIMIT"):
        list(ghcr.registry_chunks(ghcr.blob_url("a" * 64), 10, 30))
    with pytest.raises(UpdateError, match="UNTRUSTED_SOURCE"):
        list(ghcr.registry_chunks(ghcr.REGISTRY + "/manifests/latest", 10, 30))
