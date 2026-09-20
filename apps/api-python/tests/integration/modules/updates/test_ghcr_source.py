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
    ref, _ = fixture()
    state = PreparationState(
        phase="ready", target={**ref.model_dump(), "future_field": {"anything": True}}
    )
    restored = PreparationState.model_validate_json(state.model_dump_json())
    assert isinstance(restored.target, GHCRReleaseReference)
    assert restored.target.oci_digest == ref.oci_digest


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


@pytest.mark.parametrize("registry", [False, True])
@pytest.mark.parametrize("changed_digest", [False, True])
def test_offline_preflight_preserves_confirmed_target(
    tmp_path, monkeypatch, registry, changed_digest
):
    from pathlib import Path
    from types import SimpleNamespace

    from app.bootstrap import update_install
    from app.modules.updates.infrastructure import install_plan

    ref, _ = fixture()
    target = ref.model_dump()
    if not registry:
        target.pop("oci_digest")
    state = PreparationState(phase="checking", target=target)
    work = tmp_path / "update-tmp"
    work.mkdir()
    (work / "preparation.json").write_text(state.model_dump_json())
    requested = dict(target)
    if changed_digest:
        requested["sha256"] = "b" * 64
    (work / "install-request.json").write_text(
        json.dumps({"target": requested, "current": "1.0.0", "plan_sha256": "c" * 64})
    )
    monkeypatch.setattr(
        update_install,
        "get_settings",
        lambda: SimpleNamespace(resolved_storage_root=tmp_path, app_version="1.0.0"),
    )
    original_read = Path.read_bytes
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda path: (
            json.dumps({"environment": ref.environment.model_dump()}).encode()
            if str(path) == "/opt/shuku-launcher/environment.json"
            else original_read(path)
        ),
    )
    calls = []
    monkeypatch.setattr(
        install_plan,
        "validate_prepared",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    if changed_digest:
        with pytest.raises(UpdateError, match="PACKAGE_NOT_READY"):
            update_install.validate()
        assert calls == []
    else:
        update_install.validate()
        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args == (tmp_path, state, ref.environment, "c" * 64)
        assert kwargs == {"extract": True}
        assert args[1].target.model_dump() == target


@pytest.mark.parametrize("value", [None, "", "invalid", "g" * 64])
def test_target_requires_a_usable_file_digest(value):
    from pydantic import ValidationError

    from app.modules.updates.application.models import parse_target

    reference, _ = fixture()
    target = reference.model_dump()
    target["sha256"] = value
    with pytest.raises(ValidationError):
        parse_target(target)


def test_unknown_fields_cannot_hide_a_malformed_ghcr_reference():
    from pydantic import ValidationError

    from app.modules.updates.application.models import parse_target

    reference, _ = fixture()
    target = reference.model_dump()
    target["oci_digest"] = "invalid"
    with pytest.raises(ValidationError):
        parse_target(target)
    with pytest.raises(ValidationError):
        PreparationState(target=target)


def test_preflight_failure_records_public_cause_in_installation_log(
    tmp_path, monkeypatch
):
    import runpy
    from pathlib import Path
    from types import SimpleNamespace

    from app.bootstrap import update_install
    from app.core import config

    reference, _ = fixture()
    root = tmp_path / "update-tmp"
    root.mkdir()
    (root / "preparation.json").write_text(
        PreparationState(phase="checking", target=reference).model_dump_json()
    )
    (root / "install-request.json").write_text(
        json.dumps(
            {"target": {**reference.model_dump(), "sha256": "invalid-private-value"}}
        )
    )
    log = root / "installation.log"
    log.write_text("phase=checking\n")
    monkeypatch.setattr(
        config, "get_settings", lambda: SimpleNamespace(resolved_storage_root=tmp_path)
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(update_install.__file__)), run_name="__main__")
    assert result.value.code == 1
    assert "preflight=INVALID_INSTALL_REQUEST" in log.read_text()
    assert "invalid-private-value" not in log.read_text()
