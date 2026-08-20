from __future__ import annotations

import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.orm import Session

import app.modules.imports.application.import_audio as importer_module
import app.modules.imports.infrastructure.audio_cover as audio_cover_module
import app.services.audio_metadata as audio_metadata_module
from app.bootstrap.imports import (
    import_managed_book,
)
from app.core.auth import hash_password
from app.models.auth import User
from app.models.import_pipeline import ImportTask
from app.models.library import (
    LibraryReadingProgress,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.imports.application.audio_types import (
    LEGACY_AUDIO_EXTS,
    MAX_AUDIO_BUNDLE_TRACKS,
    NEW_AUDIO_EXTS,
    SUPPORTED_AUDIO_EXTS,
    audio_mime_type,
    is_supported_audio_file,
)
from app.modules.imports.application.dto import ImportOptions
from app.modules.imports.application.errors import (
    AudioInspectionError,
    AudioTrackLimitExceededError,
    ImportExecutionError,
)
from app.modules.imports.infrastructure import orchestration_services as orchestration
from app.modules.imports.infrastructure.orchestration_services import (
    SessionImportOrchestrationServices,
)
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from app.services.audio_metadata import (
    AudioChapterMetadata,
    AudioFileMetadata,
    parse_audio_metadata,
)
from tests.conftest import recreate_application_schema


def _options(**kwargs: object) -> ImportOptions:
    kwargs.setdefault("library_id", "test-library")
    return ImportOptions(**kwargs)  # type: ignore[arg-type]


class _FakeAudioDirectoryEntry:
    def __init__(self, root: Path, index: int) -> None:
        self.name = f"{index:05d}.mp3"
        self.path = str(root / self.name)

    def is_dir(self, *, follow_symlinks: bool) -> bool:
        return False

    def is_file(self, *, follow_symlinks: bool) -> bool:
        return True


def _initialize_schema(db_session) -> None:
    db_session.rollback()
    recreate_application_schema(db_session.get_bind())
    db_session.expire_all()


def _login(
    client,
    db_session,
    *,
    email: str = "audio-admin@example.com",
    password: str = "starshipnas",
) -> User:
    user = db_session.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(
            email=email,
            name=email.split("@", 1)[0],
            password_hash=hash_password(password),
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
    response = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return user


def _enable_upload_monitor(client, target: Path, name: str) -> None:
    response = client.post(
        "/api/libraries",
        json={
            "name": name,
            "rootPath": str(target),
            "organizationMode": "FLAT",
            "enabled": True,
        },
    )
    assert response.status_code == 201


def _fake_audio_metadata(
    path: Path, *, album: str = "三体", author: str = "刘慈欣"
) -> AudioFileMetadata:
    number = int(
        "".join(character for character in path.stem if character.isdigit()) or "1"
    )
    duration_ms = 100_000 * number
    return AudioFileMetadata(
        path=path.resolve(),
        title=f"第 {number} 轨",
        album=album,
        author=author,
        narrator="演播者甲",
        duration_ms=duration_ms,
        codec="mp3",
        bitrate=128_000,
        sample_rate=44_100,
        channels=2,
        disc_number=1,
        track_number=number,
        chapters=(
            AudioChapterMetadata(
                title=f"第 {number} 章", start_ms=0, end_ms=duration_ms
            ),
        ),
        raw_tags={"test": True},
    )


def _episode_audio_metadata(path: Path) -> AudioFileMetadata:
    number = int(
        "".join(
            character
            for character in path.stem.split("第")[-1].split("集")[0]
            if character.isdigit()
        )
        or "1"
    )
    return AudioFileMetadata(
        path=path.resolve(),
        title="正文",
        album=f"错误专辑 {number}",
        author=f"错误作者 {number}",
        narrator=f"角色 {number}",
        duration_ms=60_000 + number,
        codec="aac",
        bitrate=64_000,
        sample_rate=44_100,
        channels=2,
        disc_number=None,
        # Real-world episode exports often stamp every standalone file as
        # track 1. The filename episode number must win when tags duplicate.
        track_number=1,
        chapters=(),
        raw_tags={"episode": number},
    )


def _emby_audio_metadata(path: Path) -> AudioFileMetadata:
    track_match = importer_module._audio_episode_number(path)
    track_number = track_match or 1
    disc_match = importer_module._audio_disc_number(path)
    duration_ms = 30_000 + track_number
    return AudioFileMetadata(
        path=path.resolve(),
        title=f"Chapter {track_number}",
        album=None,
        author=None,
        narrator=None,
        duration_ms=duration_ms,
        codec="mp3",
        bitrate=96_000,
        sample_rate=44_100,
        channels=2,
        disc_number=disc_match,
        track_number=track_number,
        chapters=(),
        raw_tags={"embyFixture": True},
    )


def _import_audio_fixture(db_session, test_settings, monkeypatch, tmp_path: Path):
    audio_dir = test_settings.resolved_monitor_root / "[三体][刘慈欣]"
    audio_dir.mkdir(parents=True)
    # Natural filename order conflicts with the embedded track order on
    # purpose; import must honor disc/track metadata.
    (audio_dir / "10.mp3").write_bytes(b"track-ten-0123456789")
    (audio_dir / "02.mp3").write_bytes(b"track-two-abcdefghij")
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _fake_audio_metadata(path),
    )
    work = LibraryWork(
        id="audio-reader-work",
        library_id="test-library",
        origin="WATCH",
        source_key="work:audio-reader",
        title="三体",
        normalized_title="三体",
        author="刘慈欣",
        normalized_author="刘慈欣",
        tags="[]",
        organized=True,
        organize_status="APPLIED",
    )
    version = LibraryVersion(
        id="audio-reader-version",
        work_id=work.id,
        source_key="version:audio-reader",
    )
    volume = LibraryVolume(
        id="audio-reader-volume",
        version_id=version.id,
        origin="WATCH",
        title="三体",
        format="AUDIO",
        resource_key="volume:audio-reader",
        import_status="PENDING",
    )
    task = ImportTask(
        id="audio-reader-task",
        library_id="test-library",
        work_id=work.id,
        volume_id=volume.id,
        origin="WATCH",
        status="PROCESSING",
        original_name=audio_dir.name,
        source_path=str(audio_dir),
    )
    db_session.add(work)
    db_session.flush()
    db_session.add(version)
    db_session.flush()
    db_session.add(volume)
    db_session.flush()
    db_session.add(task)
    db_session.commit()
    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=audio_dir,
            origin="WATCH",
            original_name=audio_dir.name,
            topology_work_id=work.id,
            topology_volume_id=volume.id,
            import_task_id=task.id,
        ),
    )
    return result, audio_dir


def _ensure_test_implicit_version(
    db_session: Session,
    work_id: str,
) -> LibraryVersion:
    version = db_session.scalar(
        select(LibraryVersion).where(
            LibraryVersion.work_id == work_id,
            LibraryVersion.source_key == IMPLICIT_VERSION_SOURCE_KEY,
        )
    )
    if version is not None:
        return version
    version = LibraryVersion(
        id=f"implicit-{work_id}",
        work_id=work_id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _insert_media_volume(
    db_session: Session,
    *,
    volume_id: str,
    work_id: str,
    media_kind: str,
    fmt: str,
) -> None:
    version = _ensure_test_implicit_version(db_session, work_id)
    db_session.add(
        LibraryVolume(
            id=volume_id,
            version_id=version.id,
            origin="MANUAL",
            title=media_kind,
            sort_order=0,
            format=fmt,
            resource_key=f"test:{volume_id}",
            import_status="COMPLETED",
            size_bytes=0,
            cover_status="PENDING",
        )
    )
    db_session.commit()


def test_m4a_alac_is_accepted_and_container_extension_never_implies_aac(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "lossless.m4a"
    source.write_bytes(b"not-a-real-container")
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_mutagen",
        lambda _path: {"duration_ms": 1_000, "codec": "aac", "title": "错误猜测"},
    )
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_ffprobe",
        lambda _path, timeout_seconds: {"duration_ms": 1_000, "codec": "alac"},
    )

    parsed = parse_audio_metadata(source)
    assert parsed.codec == "alac"

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
    assert (
        audio_metadata_module._mutagen_codec(
            source, SimpleNamespace(codec_description="mp4a.40.2")
        )
        == "aac"
    )
    assert (
        audio_metadata_module._mutagen_codec(
            source, SimpleNamespace(codec_description="mp4a.40.5")
        )
        == "aac"
    )
    assert (
        audio_metadata_module._mutagen_codec(
            source, SimpleNamespace(codec_description="mp4a.40.29")
        )
        == "aac"
    )
    assert (
        audio_metadata_module._mutagen_codec(
            source, SimpleNamespace(codec_description="mp4a.40.36")
        )
        == "mp4a.40.36"
    )


def test_audio_parser_reads_explicit_series_and_volume_without_reusing_disc(
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


def test_audio_format_catalog_admits_every_declared_audio_extension() -> None:
    assert LEGACY_AUDIO_EXTS == {".m4a", ".m4b", ".mp3"}
    assert SUPPORTED_AUDIO_EXTS == NEW_AUDIO_EXTS | LEGACY_AUDIO_EXTS
    assert all(
        is_supported_audio_file(f"track{extension}")
        for extension in SUPPORTED_AUDIO_EXTS
    )
    assert audio_mime_type("book.m4b") == "audio/mp4"
    assert audio_mime_type("book.flac") == "audio/flac"
    assert audio_mime_type("book.opus") == "audio/ogg"
    assert audio_mime_type("book.wav") == "audio/wav"
    assert audio_mime_type("book.ape") == "audio/x-ape"


def test_ffprobe_confirmed_codec_is_accepted_for_new_audio_format(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "chapter.wma"
    source.write_bytes(b"audio")
    monkeypatch.setattr(audio_metadata_module, "_read_with_mutagen", lambda _path: {})
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_ffprobe",
        lambda _path, timeout_seconds: {"duration_ms": 1_000, "codec": "wmav2"},
    )

    assert parse_audio_metadata(source).codec == "wmav2"


def test_new_audio_format_requires_ffprobe_confirmation(tmp_path, monkeypatch) -> None:
    source = tmp_path / "chapter.flac"
    source.write_bytes(b"audio")
    monkeypatch.setattr(audio_metadata_module, "_read_with_mutagen", lambda _path: {})
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_ffprobe",
        lambda _path, timeout_seconds: {},
    )

    with pytest.raises(AudioInspectionError) as captured:
        parse_audio_metadata(source)

    assert captured.value.code == "AUDIO_PROBE_REQUIRED"


def test_audio_inspection_error_keeps_stable_import_error_code(
    db_session, test_settings, monkeypatch, tmp_path
) -> None:
    source = tmp_path / "chapter.flac"
    source.write_bytes(b"audio")

    def reject(_path: Path) -> AudioFileMetadata:
        raise AudioInspectionError("AUDIO_METADATA_INVALID", "invalid audio")

    monkeypatch.setattr(orchestration, "parse_audio_metadata", reject)
    services = SessionImportOrchestrationServices(db_session, test_settings)

    with pytest.raises(ImportExecutionError) as captured:
        services.parse_audio_metadata(source)

    assert captured.value.code == "AUDIO_METADATA_INVALID"
    assert captured.value.retryable is False


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
        assert (
            audio_metadata_module._read_with_ffprobe(source, timeout_seconds=1)["codec"]
            == "flac"
        )
    else:
        with pytest.raises(AudioInspectionError) as captured:
            audio_metadata_module._read_with_ffprobe(source, timeout_seconds=1)
        assert captured.value.code == "AUDIO_VIDEO_STREAM_UNSUPPORTED"


def test_m4a_rfc6381_aac_codec_is_accepted_without_ffprobe(
    tmp_path, monkeypatch
) -> None:
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
    monkeypatch.setattr(
        audio_metadata_module, "_read_with_ffprobe", lambda _path, timeout_seconds: {}
    )

    parsed = parse_audio_metadata(source)

    assert parsed.codec == "aac"
    assert parsed.title == "RFC 6381 AAC"


def test_audio_parser_repairs_gbk_bytes_misdeclared_as_latin1(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "鲁迅01_祥林嫂之死－孔庆东.mp3"
    source.write_bytes(b"fake-audio")
    mutagen = pytest.importorskip("mutagen")

    class TextFrame:
        encoding = 0

        def __init__(self, text_value: str):
            self.text = [text_value]

    class Tags(dict):
        def __init__(self, *args, chapters=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.chapters = chapters or []

        def getall(self, key):
            return self.chapters if key == "CHAP" else []

    def mislabeled(value: str) -> str:
        return value.encode("gb18030").decode("latin-1")

    chapter_title = TextFrame(mislabeled("第一章"))
    chapter = SimpleNamespace(
        start_time=0,
        end_time=60_000,
        sub_frames=SimpleNamespace(
            getall=lambda key: [chapter_title] if key == "TIT2" else []
        ),
    )
    tags = Tags(
        {
            "TIT2": TextFrame(mislabeled("01.祥林嫂之死")),
            "TALB": TextFrame(mislabeled("百家讲坛_《鲁迅》")),
            "TPE1": TextFrame(mislabeled("孔庆东")),
        },
        chapters=[chapter],
    )
    monkeypatch.setattr(
        mutagen,
        "File",
        lambda *_args, **_kwargs: SimpleNamespace(
            tags=tags,
            info=SimpleNamespace(
                length=60, bitrate=128_000, sample_rate=44_100, channels=2
            ),
        ),
    )
    monkeypatch.setattr(
        audio_metadata_module, "_read_with_ffprobe", lambda _path, timeout_seconds: {}
    )

    parsed = parse_audio_metadata(source)

    assert parsed.title == "01.祥林嫂之死"
    assert parsed.album == "百家讲坛_《鲁迅》"
    assert parsed.author == "孔庆东"
    assert [chapter.title for chapter in parsed.chapters] == ["第一章"]
    repairs = parsed.raw_tags["mutagen"]["encodingRepairs"]
    assert [
        (item["tag"], item["declaredEncoding"], item["detectedEncoding"])
        for item in repairs
    ] == [
        ("TIT2", "latin-1", "gb18030"),
        ("TALB", "latin-1", "gb18030"),
        ("TPE1", "latin-1", "gb18030"),
        ("CHAP:1:TIT2", "latin-1", "gb18030"),
    ]
    assert repairs[0]["original"] == mislabeled("01.祥林嫂之死")
    assert repairs[0]["repaired"] == "01.祥林嫂之死"


@pytest.mark.parametrize(
    ("value", "expected", "detected_encoding"),
    [
        ("Beyoncé".encode().decode("latin-1"), "Beyoncé", "utf-8"),
        ("繁體中文".encode("big5").decode("latin-1"), "繁體中文", "big5"),
    ],
)
def test_misdeclared_tag_repair_supports_multiple_source_encodings(
    value: str,
    expected: str,
    detected_encoding: str,
) -> None:
    repaired, diagnostic = audio_metadata_module._repair_misdecoded_text(
        value,
        declared_encoding="latin-1",
    )

    assert repaired == expected
    assert diagnostic is not None
    assert diagnostic["detectedEncoding"] == detected_encoding


@pytest.mark.parametrize(
    "value",
    [
        "The Old Man and the Sea",
        "Beyoncé",
        "François Truffaut",
        "Márquez — Cien años de soledad",
        "ÀÉÎÖÜ",
    ],
)
def test_misdeclared_tag_repair_preserves_normal_english_and_western_text(
    value: str,
) -> None:
    assert audio_metadata_module._repair_misdecoded_text(value) == (value, None)


def test_misdeclared_tag_repair_keeps_ambiguous_legacy_text_unchanged() -> None:
    ambiguous = "宮崎駿".encode("shift_jis").decode("latin-1")

    assert audio_metadata_module._repair_misdecoded_text(
        ambiguous,
        declared_encoding="latin-1",
    ) == (ambiguous, None)


def test_audio_parser_falls_back_when_mutagen_fails_and_caps_probe_output(
    tmp_path, monkeypatch
) -> None:
    source = tmp_path / "fallback.mp3"
    source.write_bytes(b"fake-audio")
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_mutagen",
        lambda _path: (_ for _ in ()).throw(ValueError("broken mutagen tags")),
    )
    monkeypatch.setattr(
        audio_metadata_module,
        "_read_with_ffprobe",
        lambda _path, timeout_seconds: {
            "title": "可回退",
            "duration_ms": 5_000,
            "codec": "mp3",
            "chapters": [],
        },
    )
    assert parse_audio_metadata(source).title == "可回退"

    with pytest.raises(ValueError, match="stdout 输出超过"):
        audio_metadata_module._run_process_with_output_limit(
            [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'x' * 4096)"],
            timeout_seconds=5,
            max_stdout_bytes=128,
            max_stderr_bytes=128,
        )


def test_audio_cover_validation_rejects_unknown_oversized_and_high_pixel_images(
    monkeypatch,
) -> None:
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

    class HugeImage:
        format = "PNG"
        size = (10_000, 10_000)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def verify(self):
            raise AssertionError("pixel bound must be checked before decode")

    monkeypatch.setattr(audio_cover_module.Image, "open", lambda _source: HugeImage())
    assert audio_cover_module.validated_audio_cover(output.getvalue()) is None


def test_scanned_audio_volume_enriches_only_prebound_topology(
    db_session,
    test_settings,
    monkeypatch,
    tmp_path: Path,
) -> None:
    _initialize_schema(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
    audio_dir = tmp_path / "Book" / "Vol.1"
    audio_dir.mkdir(parents=True)
    (audio_dir / "01.mp3").write_bytes(b"first-track")
    (audio_dir / "02.mp3").write_bytes(b"second-track")
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _fake_audio_metadata(path),
    )
    work = LibraryWork(
        id="audio-topology-work",
        library_id="test-library",
        origin="WATCH",
        source_key="work:Book",
        title="Book",
        normalized_title="book",
        tags="[]",
        organized=True,
        organize_status="APPLIED",
    )
    version = LibraryVersion(
        id="audio-topology-version",
        work_id=work.id,
        source_key="version:Book",
    )
    volume = LibraryVolume(
        id="audio-topology-volume",
        version_id=version.id,
        origin="WATCH",
        title="Vol.1",
        format="AUDIO",
        resource_key="volume:Book/Vol.1",
        import_status="PENDING",
    )
    db_session.add(work)
    db_session.commit()
    db_session.add(version)
    db_session.commit()
    db_session.add(volume)
    db_session.commit()
    task = ImportTask(
        id="audio-topology-task",
        library_id="test-library",
        work_id=work.id,
        volume_id=volume.id,
        origin="WATCH",
        status="PROCESSING",
        original_name=audio_dir.name,
        source_path=str(audio_dir),
    )
    db_session.add(task)
    db_session.commit()

    result = import_managed_book(
        db_session,
        test_settings,
        _options(
            source_file_path=audio_dir,
            origin="WATCH",
            original_name=audio_dir.name,
            topology_work_id=work.id,
            topology_volume_id=volume.id,
            import_task_id=task.id,
        ),
    )

    db_session.expire_all()
    stored_work = db_session.get(LibraryWork, work.id)
    stored_volume = db_session.get(LibraryVolume, volume.id)
    assert result.work_id == work.id
    assert result.version_id == version.id
    assert result.volume_id == volume.id
    assert result.merge_reason == "topology-bound"
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryWork")).scalar() == 1
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryVersion")).scalar() == 1
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryVolume")).scalar() == 1
    assert stored_work is not None and stored_work.title == "Book"
    assert stored_volume is not None and stored_volume.title == "Vol.1"
    assert stored_volume.import_status == "COMPLETED"
    assert stored_volume.track_count == 2


def test_audio_bootstrap_range_head_and_completion_follow_volume_progress(
    client, db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    result, _audio_dir = _import_audio_fixture(
        db_session, test_settings, monkeypatch, tmp_path
    )

    bootstrap_response = client.get(
        f"/api/reader/v4/volumes/{result.volume_id}/bootstrap"
    )
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["readerType"] == "audio"
    assert bootstrap["version"]["id"] == bootstrap["volume"]["versionId"]
    assert "mediaKind" not in bootstrap["version"]
    assert "mediaVersion" not in bootstrap
    assert "publicationFingerprint" not in bootstrap
    assert [track["trackNumber"] for track in bootstrap["files"]] == [2, 10]
    assert {track["codec"] for track in bootstrap["files"]} == {"mp3"}
    assert bootstrap["volume"]["durationMs"] == 1_200_000
    assert len(bootstrap["units"]) == 2

    first_track = bootstrap["files"][0]
    full = client.get(first_track["url"])
    assert full.status_code == 200
    assert full.headers["accept-ranges"] == "bytes"
    partial = client.get(first_track["url"], headers={"Range": "bytes=2-6"})
    assert partial.status_code == 206
    assert partial.headers["content-range"].startswith("bytes 2-6/")
    suffix = client.get(first_track["url"], headers={"Range": "bytes=-4"})
    assert suffix.status_code == 206
    invalid = client.get(first_track["url"], headers={"Range": "bytes=999999-"})
    assert invalid.status_code == 416
    head = client.head(first_track["url"])
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == full.headers["content-length"]
    assert head.headers["etag"] == full.headers["etag"]
    assert head.headers["accept-ranges"] == "bytes"

    # Our lightweight file validator is intentionally weak. RFC 9110 forbids
    # weak entity-tag comparison for If-Range, so it must fall back to 200.
    weak_if_range = client.get(
        first_track["url"],
        headers={"Range": "bytes=2-6", "If-Range": full.headers["etag"]},
    )
    assert weak_if_range.status_code == 200
    assert "content-range" not in weak_if_range.headers
    matching_date_if_range = client.get(
        first_track["url"],
        headers={"Range": "bytes=2-6", "If-Range": full.headers["last-modified"]},
    )
    assert matching_date_if_range.status_code == 206
    stale_date_if_range = client.get(
        first_track["url"],
        headers={"Range": "bytes=2-6", "If-Range": "Thu, 01 Jan 1970 00:00:00 GMT"},
    )
    assert stale_date_if_range.status_code == 200

    final_track = bootstrap["files"][-1]
    common = {
        "schemaVersion": 4,
        "clientId": "audio-player",
        "locator": {
            "kind": "audio",
            "fileId": final_track["id"],
            "positionMillis": 0,
        },
    }
    seek = client.put(
        f"/api/reader/v4/volumes/{result.volume_id}/progress",
        json={
            **common,
            "mutationId": str(uuid4()),
            "baseRevision": 0,
            "capturedAtEpochMillis": 1_700_000_001_000,
        },
    )
    assert seek.status_code == 200
    assert seek.json()["data"]["revision"] == 1
    assert (
        client.get(f"/api/reader/v4/volumes/{result.volume_id}/bootstrap").json()[
            "data"
        ]["versionCompleted"]
        is False
    )

    ended = client.put(
        f"/api/reader/v4/volumes/{result.volume_id}/progress",
        json={
            **common,
            "mutationId": str(uuid4()),
            "baseRevision": 1,
            "capturedAtEpochMillis": 1_700_000_002_000,
            "locator": {
                **common["locator"],
                "positionMillis": final_track["durationMs"],
            },
        },
    )
    assert ended.status_code == 200
    assert ended.json()["data"]["displayPercent"] == 100
    assert (
        client.get(f"/api/reader/v4/volumes/{result.volume_id}/bootstrap").json()[
            "data"
        ]["versionCompleted"]
        is True
    )

    paused_after_finish = client.put(
        f"/api/reader/v4/volumes/{result.volume_id}/progress",
        json={
            **common,
            "mutationId": str(uuid4()),
            "baseRevision": 2,
            "capturedAtEpochMillis": 1_700_000_003_000,
            "locator": {
                **common["locator"],
                "fileId": first_track["id"],
                "positionMillis": first_track["durationMs"] // 10,
            },
        },
    )
    assert paused_after_finish.status_code == 200
    assert (
        client.get(f"/api/reader/v4/volumes/{result.volume_id}/bootstrap").json()[
            "data"
        ]["versionCompleted"]
        is False
    )


def test_three_media_filters_tabs_preferences_and_completion_are_user_scoped(
    client, db_session
) -> None:
    _initialize_schema(db_session)
    user_a = _login(client, db_session, email="listener-a@example.com")
    db_session.add(
        LibraryWork(
            library_id="test-library",
            id="mixed-work",
            origin="MANUAL",
            title="Mixed media work",
            normalized_title="mixed media work",
            author="Author",
            normalized_author="author",
            tags="[]",
        )
    )
    db_session.commit()
    for volume_id, media_kind, fmt in (
        ("mixed-ebook-volume", "EBOOK", "EPUB"),
        ("mixed-comic-volume", "COMIC", "COMIC"),
        ("mixed-audio-volume", "AUDIOBOOK", "AUDIO"),
    ):
        _insert_media_volume(
            db_session,
            volume_id=volume_id,
            work_id="mixed-work",
            media_kind=media_kind,
            fmt=fmt,
        )

    for filter_value in ("ebook", "COMIC", "audiobook"):
        response = client.get("/api/works", params={"type": filter_value})
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["data"]["books"]] == [
            "mixed-work"
        ]

    detail = client.get("/api/works/mixed-work").json()["data"]["book"]
    assert [version["sourceKey"] for version in detail["versions"]] == [
        IMPLICIT_VERSION_SOURCE_KEY
    ]
    assert {volume["id"] for volume in detail["versions"][0]["volumes"]} == {
        "mixed-ebook-volume",
        "mixed-comic-volume",
        "mixed-audio-volume",
    }

    for index, volume_id in enumerate(
        ("mixed-ebook-volume", "mixed-comic-volume", "mixed-audio-volume"),
        start=1,
    ):
        is_audio = volume_id == "mixed-audio-volume"
        db_session.add(
            LibraryReadingProgress(
                id=f"progress-a-{index}",
                user_id=user_a.id,
                volume_id=volume_id,
                reader_type="audio" if is_audio else "epub",
                position="complete",
                percent=100,
                extra="{}",
                schema_version=3,
                location_type="audio" if is_audio else "epub",
                location_json=json.dumps(
                    {"type": "audio", "positionMs": 1}
                    if is_audio
                    else {"type": "epub", "href": "chapter.xhtml", "progression": 1}
                ),
            )
        )
    db_session.commit()
    completed_for_a = client.get("/api/works/mixed-work").json()["data"]["book"]
    assert completed_for_a["completed"] is True
    assert all(item["completed"] for item in completed_for_a["versions"])

    _login(client, db_session, email="listener-b@example.com")
    detail_for_b = client.get("/api/works/mixed-work").json()["data"]["book"]
    assert detail_for_b["completed"] is False
    assert all(
        volume["progress"] == 0
        for version in detail_for_b["versions"]
        for volume in version["volumes"]
    )

    _login(client, db_session, email="listener-a@example.com")
    db_session.add(
        LibraryVolume(
            id="mixed-ebook-volume-2",
            version_id=_ensure_test_implicit_version(db_session, "mixed-work").id,
            origin="MANUAL",
            title="Second ebook",
            sort_order=1,
            format="PDF",
            resource_key="test:mixed-ebook-volume-2",
        )
    )
    db_session.commit()
    after_new_volume = client.get("/api/works/mixed-work").json()["data"]["book"]
    assert after_new_volume["completed"] is False
    assert after_new_volume["continueVolumeId"] == "mixed-ebook-volume-2"


def test_active_audio_volume_and_continue_reading_follow_volume_progress(
    client, db_session
) -> None:
    _initialize_schema(db_session)
    user = _login(client, db_session, email="volume-switch@example.com")
    work = LibraryWork(
        library_id="test-library",
        id="switch-work",
        origin="MANUAL",
        title="Two audio volumes",
        normalized_title="two audio volumes",
        tags="[]",
    )
    version = LibraryVersion(
        id="switch-version",
        work_id=work.id,
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    volumes = [
        LibraryVolume(
            id=f"audio-{suffix}-volume",
            version_id=version.id,
            origin="MANUAL",
            title=f"Volume {suffix.upper()}",
            sort_order=index,
            format="AUDIO",
            resource_key=f"test:audio-{suffix}-volume",
            duration_ms=100_000,
        )
        for index, suffix in enumerate(("a", "b"))
    ]
    db_session.add(work)
    db_session.flush()
    db_session.add(version)
    db_session.flush()
    db_session.add_all(volumes)
    db_session.flush()
    db_session.add(
        LibraryReadingProgress(
            id="progress-b",
            user_id=user.id,
            volume_id=volumes[1].id,
            reader_type="audio",
            position="50000",
            percent=80,
            extra='{"positionMs":50000}',
            schema_version=3,
            location_type="audio",
            location_json=json.dumps({"type": "audio", "positionMs": 50_000}),
        )
    )
    db_session.commit()

    detail = client.get("/api/works/switch-work").json()["data"]
    assert len(detail["book"]["versions"]) == 1
    assert [volume["id"] for volume in detail["book"]["versions"][0]["volumes"]] == [
        "audio-a-volume",
        "audio-b-volume",
    ]
    assert detail["book"]["continueVolumeId"] == "audio-b-volume"
    volumes_by_id = {
        volume["id"]: volume for volume in detail["book"]["versions"][0]["volumes"]
    }
    assert volumes_by_id["audio-a-volume"]["progress"] == 0
    assert volumes_by_id["audio-b-volume"]["progress"] == 80
    assert volumes_by_id["audio-a-volume"]["versionId"] == "switch-version"

    now = datetime.now(UTC)
    db_session.add(
        LibraryReadingProgress(
            id="progress-a",
            user_id=user.id,
            volume_id=volumes[0].id,
            reader_type="audio",
            position="100000",
            percent=100,
            extra='{"positionMs":100000}',
            schema_version=3,
            location_type="audio",
            location_json=json.dumps({"type": "audio", "positionMs": 100_000}),
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
        )
    )
    db_session.query(LibraryReadingProgress).filter(
        LibraryReadingProgress.id == "progress-b"
    ).update({"percent": 100, "updated_at": now})
    db_session.commit()
    completed = client.get("/api/works/switch-work").json()["data"]["book"]
    assert completed["completed"] is True
    assert completed["versions"][0]["completed"] is True
    assert completed["continueVolumeId"] == "audio-b-volume"


def test_multi_audio_upload_saves_raw_tracks_without_creating_bundle_task(
    client, db_session, test_settings
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    target = test_settings.resolved_monitor_root / "uploads"
    target.mkdir(parents=True, exist_ok=True)
    _enable_upload_monitor(client, target, "Audio uploads")
    response = client.post(
        "/api/works/import",
        data={"targetPath": str(target)},
        files=[
            ("files", ("01.mp3", b"first-track", "audio/mpeg")),
            ("files", ("02.mp3", b"second-track", "audio/mpeg")),
        ],
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["saved"] == 2
    assert data["autoImport"] is True
    assert [item["file"] for item in data["results"]] == ["01.mp3", "02.mp3"]
    assert (target / "01.mp3").read_bytes() == b"first-track"
    assert (target / "02.mp3").read_bytes() == b"second-track"
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM `ImportTask`")).scalar_one() == 0
    )
    assert not any(".part" in path.name for path in target.iterdir())


def test_manual_multi_audio_upload_keeps_aggregate_byte_limit(
    client, db_session, test_settings
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    target = test_settings.resolved_monitor_root / "limited-upload"
    target.mkdir(parents=True, exist_ok=True)
    _enable_upload_monitor(client, target, "Limited audio uploads")
    test_settings.audiobook_max_file_bytes = 1024
    test_settings.audiobook_max_bundle_bytes = 20

    response = client.post(
        "/api/works/import",
        data={"targetPath": str(target)},
        files=[
            ("files", ("01.mp3", b"first-upload-track", "audio/mpeg")),
            ("files", ("02.mp3", b"second-upload-track", "audio/mpeg")),
        ],
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "上传文件超过允许的大小"
    assert list(target.iterdir()) == []
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM `ImportTask`")).scalar_one() == 0
    )


def test_failed_audio_upload_removes_staging_files_and_never_creates_task(
    client, db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    target = test_settings.resolved_monitor_root / "failed-upload"
    target.mkdir(parents=True, exist_ok=True)
    _enable_upload_monitor(client, target, "Failed audio uploads")

    def fail_after_partial_write(_source, staged_target: Path, *, max_bytes):
        staged_target.write_bytes(b"partial")
        raise OSError("simulated interrupted copy")

    monkeypatch.setattr(
        AtomicUploadedFilePublisher,
        "_copy_stream",
        staticmethod(fail_after_partial_write),
    )
    response = client.post(
        "/api/works/import",
        data={"targetPath": str(target)},
        files=[
            ("files", ("01.mp3", b"first-track", "audio/mpeg")),
            ("files", ("02.mp3", b"second-track", "audio/mpeg")),
        ],
    )
    assert response.status_code == 500
    assert list(target.iterdir()) == []
    assert db_session.execute(text("SELECT COUNT(*) FROM `ImportTask`")).scalar() == 0


def test_audio_directory_structure_rejects_mixed_tracks_and_keeps_unmatched_children_independent(
    tmp_path,
) -> None:
    mixed = tmp_path / "Mixed Book"
    volume = mixed / "Vol.1"
    volume.mkdir(parents=True)
    (mixed / "00.mp3").write_bytes(b"direct")
    (volume / "01.mp3").write_bytes(b"volume")
    with pytest.raises(ValueError, match="不能同时包含直属音轨和卷目录"):
        audio_metadata_module.inspect_audio_bundle(mixed)

    collection = tmp_path / "Author Name"
    independent_book = collection / "Independent Book"
    independent_book.mkdir(parents=True)
    (independent_book / "01.mp3").write_bytes(b"independent")
    assert audio_metadata_module.inspect_audio_bundle(collection) is None
    independent = audio_metadata_module.inspect_audio_bundle(independent_book)
    assert independent is not None
    assert independent.title == "Independent Book"
    assert independent.author is None


@pytest.mark.parametrize("track_count", [9_999, 10_000])
def test_audio_bundle_accepts_tracks_up_to_the_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    track_count: int,
) -> None:
    root = tmp_path / "Bounded Audio"
    root.mkdir()
    monkeypatch.setattr(
        audio_metadata_module.os,
        "scandir",
        lambda _path: (
            _FakeAudioDirectoryEntry(root, index) for index in range(track_count)
        ),
    )

    structure = audio_metadata_module.inspect_audio_bundle(root)

    assert structure is not None
    assert len(structure.files) == track_count
    assert track_count <= MAX_AUDIO_BUNDLE_TRACKS


def test_audio_bundle_stops_buffering_at_track_limit_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "Overflow Audio"
    root.mkdir()
    yielded = 0

    def entries(_path):
        nonlocal yielded
        for index in range(1_800_000):
            yielded += 1
            yield _FakeAudioDirectoryEntry(root, index)

    monkeypatch.setattr(audio_metadata_module.os, "scandir", entries)

    with pytest.raises(AudioTrackLimitExceededError) as raised:
        audio_metadata_module.inspect_audio_bundle(root)

    assert raised.value.limit == 10_000
    assert raised.value.observed_count == 10_001
    assert yielded == 10_001


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("我靠充值当武帝590-没听进去.m4a", 590),
        ("2020版-我靠充值当武帝第590集-没听进去.m4a", 590),
        ("001-标题2020.m4a", 1),
    ],
)
def test_audio_episode_number_falls_back_to_digits_anywhere_after_explicit_rules(
    file_name: str,
    expected: int,
) -> None:
    assert importer_module._audio_episode_number(Path(file_name)) == expected
