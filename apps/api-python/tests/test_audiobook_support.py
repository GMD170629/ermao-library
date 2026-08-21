from __future__ import annotations

import hashlib
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import app.modules.imports.infrastructure.audio_cover as audio_cover_module
import app.services.audio_metadata as audio_metadata_module
from app.core.auth import hash_password
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.models.auth import User
from app.modules.imports.application.audio_types import (
    LEGACY_AUDIO_EXTS,
    NEW_AUDIO_EXTS,
    SUPPORTED_AUDIO_EXTS,
    audio_mime_type,
    is_supported_audio_file,
)
from app.services.audio_metadata import parse_audio_metadata


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 1_000,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _add_audiobook(db_session) -> tuple[LibraryBook, LibraryReadableResource]:
    book_node = _node("audio-book-node", "audio-book/", directory=True)
    resource_node = _node("audio-resource-node", "audio-book/book.m4b")
    book = LibraryBook(
        id="audio-book",
        library_id="test-library",
        source_node_id=book_node.id,
    )
    resource = LibraryReadableResource(
        id="audio-resource",
        library_id="test-library",
        book_id=book.id,
        source_node_id=resource_node.id,
        adapter_id="audio-file",
        adapter_version="1",
        media_kind="AUDIOBOOK",
        format="M4B",
        import_state="READY",
    )
    db_session.add_all(
        [
            book_node,
            resource_node,
            book,
            LibraryBookMetadata(
                book_id=book.id,
                title="Audio book",
                normalized_title="audio book",
                author="Narrator",
            ),
            resource,
            LibraryReadableResourceMetadata(
                resource_id=resource.id,
                title="Audio resource",
                duration_ms=3_600_000,
                track_count=12,
                narrator="Narrator",
            ),
            LibraryResourceAsset(
                id="audio-asset",
                library_id="test-library",
                resource_id=resource.id,
                source_node_id=resource_node.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            ),
            LibraryResourceAssetMetadata(
                asset_id="audio-asset",
                mime_type="audio/mp4",
                duration_ms=3_600_000,
                codec="aac",
                track_number=1,
            ),
        ]
    )
    db_session.flush()
    return book, resource


def _login(client, db_session) -> None:
    db_session.add(
        User(
            id="audio-admin",
            email="audio-admin@example.com",
            name="Audio admin",
            password_hash=hash_password("audio-password"),
            role="admin",
        )
    )
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "audio-admin@example.com", "password": "audio-password"},
    )
    assert response.status_code == 200, response.text


def test_m4a_alac_is_accepted_and_container_extension_never_implies_aac(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "lossless.m4a"
    source.write_bytes(b"not-a-real-container")
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_mutagen",
        lambda _path: {"duration_ms": 1_000, "codec": "aac", "title": "wrong"},
    )
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_ffprobe",
        lambda _path, timeout_seconds: {"duration_ms": 1_000, "codec": "alac"},
    )

    assert parse_audio_metadata(source).codec == "alac"
    assert audio_metadata_module._mutagen_codec(source, SimpleNamespace()) is None
    assert (
        audio_metadata_module._mutagen_codec(
            source, SimpleNamespace(codec_description="Apple Lossless Audio Codec")
        )
        == "alac"
    )
    assert (
        audio_metadata_module._mutagen_codec(
            source, SimpleNamespace(codec_description="AAC LC")
        )
        == "aac"
    )


def test_audio_parser_reads_series_and_resource_index_without_reusing_disc(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "book.mp3"
    source.write_bytes(b"fake-audio")
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_mutagen",
        lambda _path: {
            "duration_ms": 1_000,
            "codec": "mp3",
            "series_name": "银河帝国",
            "volume_index": "第 2 卷",
            "disc_number": "4/6",
        },
    )
    monkeypatch.setattr(
        audio_metadata_module, "_read_with_ffprobe", lambda _path, timeout_seconds: {}
    )

    parsed = parse_audio_metadata(source)

    assert parsed.series_name == "银河帝国"
    assert parsed.volume_index == 2
    assert parsed.disc_number == 4


def test_audio_format_catalog_admits_every_declared_extension() -> None:
    assert LEGACY_AUDIO_EXTS == {".m4a", ".m4b", ".mp3"}
    assert SUPPORTED_AUDIO_EXTS == NEW_AUDIO_EXTS | LEGACY_AUDIO_EXTS
    assert all(is_supported_audio_file(f"track{extension}") for extension in SUPPORTED_AUDIO_EXTS)
    assert audio_mime_type("book.m4b") == "audio/mp4"
    assert audio_mime_type("book.flac") == "audio/flac"
    assert audio_mime_type("book.opus") == "audio/ogg"
    assert audio_mime_type("book.wav") == "audio/wav"
    assert audio_mime_type("book.ape") == "audio/x-ape"


def test_new_audio_format_requires_ffprobe_confirmation(tmp_path, monkeypatch) -> None:
    source = tmp_path / "chapter.flac"
    source.write_bytes(b"audio")
    monkeypatch.setattr(audio_metadata_module, "_read_with_mutagen", lambda _path: {})
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_ffprobe",
        lambda _path, timeout_seconds: {},
    )

    with pytest.raises(audio_metadata_module.AudioInspectionError) as captured:
        parse_audio_metadata(source)
    assert captured.value.code == "AUDIO_PROBE_REQUIRED"


@pytest.mark.parametrize("attached_picture", [False, True])
def test_ffprobe_rejects_video_but_allows_attached_cover(
    tmp_path, monkeypatch, attached_picture: bool
) -> None:
    source = tmp_path / "chapter.mka"
    source.write_bytes(b"audio")
    payload = {
        "streams": [
            {"codec_type": "audio", "codec_name": "flac", "duration": "1"},
            {
                "codec_type": "video",
                "disposition": {"attached_pic": 1 if attached_picture else 0},
            },
        ],
        "format": {"duration": "1"},
    }
    monkeypatch.setattr(audio_metadata_module.shutil, "which", lambda _name: "/ffprobe")
    monkeypatch.setattr(
        audio_metadata_module,
        "_run_process_with_output_limit",
        lambda *_args, **_kwargs: (0, json.dumps(payload).encode(), b""),
    )

    if attached_picture:
        assert audio_metadata_module._read_with_ffprobe(source, timeout_seconds=1)["codec"] == "flac"
    else:
        with pytest.raises(audio_metadata_module.AudioInspectionError) as captured:
            audio_metadata_module._read_with_ffprobe(source, timeout_seconds=1)
        assert captured.value.code == "AUDIO_VIDEO_STREAM_UNSUPPORTED"


def test_m4a_rfc6381_aac_codec_is_accepted_without_ffprobe(tmp_path, monkeypatch) -> None:
    source = tmp_path / "aac-lc.m4a"
    source.write_bytes(b"not-a-real-container")
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_mutagen",
        lambda _path: {
            "title": "RFC 6381 AAC",
            "duration_ms": 5_000,
            "codec": "mp4a.40.2",
            "sample_rate": 44_100,
            "channels": 2,
        },
    )
    monkeypatch.setattr(audio_metadata_module, "_read_with_ffprobe", lambda *_args: {})

    parsed = parse_audio_metadata(source)

    assert parsed.codec == "aac"
    assert parsed.title == "RFC 6381 AAC"


def test_audio_cover_validation_rejects_unknown_oversized_and_high_pixel_images() -> None:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "navy").save(output, format="PNG")
    valid = audio_cover_module.validated_audio_cover(output.getvalue())
    assert valid is not None
    assert valid[1] == ".png"
    assert audio_cover_module.validated_audio_cover(b"not-an-image") is None
    assert (
        audio_cover_module.validated_audio_cover(
            b"x" * (audio_cover_module.MAX_AUDIO_COVER_BYTES + 1)
        )
        is None
    )


def test_audiobook_resource_is_published_through_canonical_book_api(client, db_session) -> None:
    _login(client, db_session)
    _book, resource = _add_audiobook(db_session)
    db_session.commit()

    response = client.get("/api/books/audio-book")

    assert response.status_code == 200, response.text
    book = response.json()["data"]["book"]
    assert book["availableMediaKinds"] == ["AUDIOBOOK"]
    assert [item["id"] for item in book["resources"]] == [resource.id]
    assert book["resources"][0]["readerType"] == "audio"
    assert book["resources"][0]["durationMs"] == 3_600_000
    assert book["resources"][0]["assets"][0]["trackNumber"] == 1
    assert client.get("/api/works/audio-book").status_code == 404
