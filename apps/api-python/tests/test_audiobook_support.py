from __future__ import annotations

import io
import json
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import text

import app.modules.imports.application.import_audio as importer_module
import app.modules.imports.application.managed_book as managed_book_module
import app.modules.imports.infrastructure.audio_cover as audio_cover_module
import app.services.audio_metadata as audio_metadata_module
import app.worker.watcher as watcher_module
from app.bootstrap.imports import (
    enqueue_import_task,
    import_managed_book,
    load_known_import_paths,
    scan_directory_for_imports,
)
from app.core.auth import hash_password
from app.db.base import Base
from app.db.bootstrap import apply_schema
from app.models.auth import User
from app.models.library import (
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.modules.imports.application.audio_types import MAX_AUDIO_BUNDLE_TRACKS
from app.modules.imports.application.dto import ImportOptions
from app.modules.imports.application.errors import AudioTrackLimitExceededError
from app.modules.imports.infrastructure.orchestration_services import (
    SessionImportOrchestrationServices,
)
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)
from app.services.audio_metadata import (
    AudioChapterMetadata,
    AudioFileMetadata,
    parse_audio_metadata,
)
from app.worker.watcher import (
    MonitorFolderConfig,
    WatchState,
    WorkerManager,
)
from tests.test_worker_importer import write_epub_metadata_fixture


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
    Base.metadata.create_all(db_session.get_bind())
    apply_schema(db_session.get_bind())
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
    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=audio_dir, origin="MANUAL", original_name=audio_dir.name
        ),
    )
    return result, audio_dir


def _insert_media_volume(
    db_session,
    *,
    media_version_id: str,
    volume_id: str,
    work_id: str,
    media_kind: str,
    fmt: str,
) -> None:
    db_session.execute(
        text(
            "INSERT INTO `LibraryMediaVersion` "
            "(`id`, `workId`, `mediaKind`, `createdAt`, `updatedAt`) "
            "VALUES (:id, :work_id, :media_kind, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "id": media_version_id,
            "work_id": work_id,
            "media_kind": media_kind,
        },
    )
    db_session.execute(
        text(
            "INSERT INTO `LibraryVolume` "
            "(`id`, `mediaVersionId`, `origin`, `title`, `sortOrder`, `format`, `resourceKey`, "
            "`importStatus`, `sizeBytes`, `coverStatus`, `hidden`, `createdAt`, `updatedAt`) "
            "VALUES (:id, :media_version_id, 'MANUAL', :title, 0, :format, :key, "
            "'COMPLETED', 0, 'PENDING', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "id": volume_id,
            "media_version_id": media_version_id,
            "title": media_kind,
            "format": fmt,
            "key": f"test:{volume_id}",
        },
    )
    db_session.commit()


def test_m4a_alac_is_rejected_and_container_extension_never_implies_aac(
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

    with pytest.raises(ValueError, match="alac"):
        parse_audio_metadata(source)

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


def test_audio_bundle_import_merges_with_existing_epub_and_orders_tracks(
    db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
    epub = tmp_path / "[三体][刘慈欣].epub"
    write_epub_metadata_fixture(epub, "三体", "刘慈欣")
    epub_result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )
    audio_result, _audio_dir = _import_audio_fixture(
        db_session, test_settings, monkeypatch, tmp_path
    )

    assert audio_result.work_id == epub_result.work_id
    media_volumes = (
        db_session.execute(
            text(
                "SELECT media.mediaKind, volume.format, volume.title "
                "FROM LibraryMediaVersion AS media "
                "JOIN LibraryVolume AS volume ON volume.mediaVersionId = media.id "
                "WHERE media.workId = :work_id ORDER BY media.mediaKind"
            ),
            {"work_id": audio_result.work_id},
        )
        .mappings()
        .all()
    )
    assert [
        (row["mediaKind"], row["format"], row["title"]) for row in media_volumes
    ] == [
        ("AUDIOBOOK", "AUDIO", "正文"),
        ("EBOOK", "EPUB", "[三体][刘慈欣]"),
    ]
    tracks = (
        db_session.execute(
            text(
                "SELECT `trackNumber`, `sortOrder`, `durationMs`, `codec` FROM `LibraryFile` WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": audio_result.volume_id},
        )
        .mappings()
        .all()
    )
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [
        (2, 0),
        (10, 1),
    ]
    assert sum(int(row["durationMs"]) for row in tracks) == 1_200_000
    assert {row["codec"] for row in tracks} == {"mp3"}
    task = (
        db_session.execute(
            text(
                "SELECT `taskKind`, `assetCount`, `processedAssetCount`, `status` FROM `ImportTask` WHERE `volumeId` = :volume_id"
            ),
            {"volume_id": audio_result.volume_id},
        )
        .mappings()
        .one()
    )
    assert dict(task) == {
        "taskKind": "AUDIO_BUNDLE",
        "assetCount": 2,
        "processedAssetCount": 2,
        "status": "COMPLETED",
    }
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM `ImportAsset` WHERE `importTaskId` = (SELECT `id` FROM `ImportTask` WHERE `volumeId` = :volume_id) AND `status` = 'COMPLETED'"
            ),
            {"volume_id": audio_result.volume_id},
        ).scalar()
        == 2
    )


def test_audio_bundle_does_not_guess_between_duplicate_path_scoped_works(
    db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
    first_dir = tmp_path / "edition-a"
    second_dir = tmp_path / "edition-b"
    first_dir.mkdir()
    second_dir.mkdir()
    first_epub = first_dir / "[三体][刘慈欣].epub"
    second_epub = second_dir / "[三体][刘慈欣].epub"
    write_epub_metadata_fixture(first_epub, "三体", "刘慈欣", ["edition-a"])
    write_epub_metadata_fixture(second_epub, "三体", "刘慈欣", ["edition-b"])

    first = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=first_epub,
            origin="MANUAL",
            original_name=first_epub.name,
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=second_epub,
            origin="MANUAL",
            original_name=second_epub.name,
        ),
    )
    audio, _audio_dir = _import_audio_fixture(
        db_session, test_settings, monkeypatch, tmp_path
    )

    assert first.work_id != second.work_id
    assert audio.work_id not in {first.work_id, second.work_id}
    assert db_session.execute(text("SELECT COUNT(*) FROM LibraryWork")).scalar() == 3


def test_audio_moved_copy_runs_normal_import_without_content_hashing(
    db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    first, original_dir = _import_audio_fixture(
        db_session, test_settings, monkeypatch, tmp_path
    )
    same_path = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=original_dir,
            origin="MANUAL",
            original_name=original_dir.name,
        ),
    )
    assert same_path.duplicate is True
    assert same_path.media_version_id == first.media_version_id
    assert same_path.volume_id == first.volume_id

    moved_dir = test_settings.resolved_monitor_root / "moved-copy"
    moved_dir.mkdir()
    for source in original_dir.iterdir():
        (moved_dir / source.name).write_bytes(source.read_bytes())

    real_path_open = Path.open

    def reject_audio_content_reads(path: Path, *args, **kwargs):
        mode = str(args[0] if args else kwargs.get("mode", "r"))
        if path.suffix.lower() in {".mp3", ".m4a", ".m4b"} and "r" in mode:
            raise AssertionError(f"audio content was read for hashing: {path}")
        return real_path_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_audio_content_reads)
    moved = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=moved_dir,
            origin="MANUAL",
            original_name=moved_dir.name,
            requested_title="三体",
            requested_author="刘慈欣",
        ),
    )
    assert moved.duplicate is False
    assert moved.work_id == first.work_id
    assert moved.media_version_id == first.media_version_id
    assert moved.volume_id != first.volume_id
    assert moved.merge_reason == "new-audio-volume"
    assert (
        db_session.execute(
            text(
                "SELECT COUNT(*) FROM `LibraryMediaVersion` WHERE `workId` = :work_id AND `mediaKind` = 'AUDIOBOOK'"
            ),
            {"work_id": first.work_id},
        ).scalar()
        == 1
    )
    files = (
        db_session.execute(
            text(
                "SELECT `path`, `fingerprint`, `fullHash`, `hashStatus` "
                "FROM `LibraryFile` WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": moved.volume_id},
        )
        .mappings()
        .all()
    )
    assert len(files) == 2
    assert all(str(row["path"]).startswith(str(moved_dir)) for row in files)
    assert all(row["fingerprint"] is None for row in files)
    assert all(row["fullHash"] is None for row in files)
    assert {row["hashStatus"] for row in files} == {"PARTIAL_PENDING"}


def test_audio_partial_content_overlap_runs_normal_import(
    db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    first, original_dir = _import_audio_fixture(
        db_session, test_settings, monkeypatch, tmp_path
    )
    overlap_dir = test_settings.resolved_monitor_root / "partial-overlap"
    overlap_dir.mkdir()
    (overlap_dir / "02.mp3").write_bytes((original_dir / "02.mp3").read_bytes())
    (overlap_dir / "11.mp3").write_bytes(b"new-track-eleven")
    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=overlap_dir,
            origin="MANUAL",
            original_name=overlap_dir.name,
            requested_title="三体",
            requested_author="刘慈欣",
        ),
    )
    assert result.duplicate is False
    assert result.work_id == first.work_id
    assert result.media_version_id == first.media_version_id
    assert result.volume_id != first.volume_id
    files = (
        db_session.execute(
            text(
                "SELECT `fingerprint`, `fullHash` FROM `LibraryFile` "
                "WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    assert len(files) == 2
    assert all(row["fingerprint"] is None for row in files)
    assert all(row["fullHash"] is None for row in files)


def test_audio_bundle_keeps_byte_identical_tracks_as_distinct_chapters(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    folder = test_settings.resolved_monitor_root / "duplicate-tracks"
    folder.mkdir(parents=True)
    payload = b"the-same-track-bytes"
    (folder / "01.mp3").write_bytes(payload)
    (folder / "02.mp3").write_bytes(payload)
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _fake_audio_metadata(path),
    )

    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=folder,
            origin="MANUAL",
            requested_title="重复音轨",
            requested_author="测试作者",
        ),
    )

    files = (
        db_session.execute(
            text(
                "SELECT `id`, `path`, `fingerprint`, `sortOrder` FROM `LibraryFile` "
                "WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    chapters = (
        db_session.execute(
            text(
                "SELECT `fileId`, `title`, `sortOrder` FROM `LibraryReadingUnit` "
                "WHERE `volumeId` = :volume_id AND `unitType` = 'audio_chapter' ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    assert len(files) == 2
    assert len({row["id"] for row in files}) == 2
    assert len({row["path"] for row in files}) == 2
    assert all(row["fingerprint"] is None for row in files)
    assert [row["sortOrder"] for row in files] == [0, 1]
    assert [row["fileId"] for row in chapters] == [row["id"] for row in files]
    assert [row["sortOrder"] for row in chapters] == [1, 2]


def test_file_import_does_not_apply_browser_upload_bundle_byte_limit(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    folder = test_settings.resolved_monitor_root / "large-local-audiobook"
    folder.mkdir(parents=True)
    (folder / "01.mp3").write_bytes(b"first-local-track")
    (folder / "02.mp3").write_bytes(b"second-local-track")
    local_settings = test_settings.model_copy(
        update={
            "audiobook_max_file_bytes": 1024,
            "audiobook_max_bundle_bytes": 20,
        }
    )
    assert (
        sum(path.stat().st_size for path in folder.iterdir())
        > local_settings.audiobook_max_bundle_bytes
    )
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _fake_audio_metadata(path),
    )

    result = import_managed_book(
        db_session,
        local_settings,
        ImportOptions(
            source_file_path=folder, origin="WATCH", requested_title="大型本地有声书"
        ),
    )

    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM `LibraryFile` WHERE `volumeId` = :volume_id"),
            {"volume_id": result.volume_id},
        ).scalar_one()
        == 2
    )


def test_single_audio_file_task_imports_parent_directory_as_one_bundle(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    folder = test_settings.resolved_monitor_root / "single-files"
    folder.mkdir(parents=True)
    first_path = folder / "first.mp3"
    second_path = folder / "second.mp3"
    first_path.write_bytes(b"first-distinct-audio")
    second_path.write_bytes(b"second-distinct-audio")
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _fake_audio_metadata(path),
    )
    first = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=first_path,
            origin="MANUAL",
            requested_title="同一本书",
            requested_author="同一作者",
        ),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=second_path,
            origin="MANUAL",
            requested_title="同一本书",
            requested_author="同一作者",
        ),
    )
    assert first.work_id == second.work_id
    assert first.media_version_id == second.media_version_id
    assert first.volume_id == second.volume_id
    assert second.duplicate is True
    volumes = (
        db_session.execute(
            text(
                "SELECT volume.id, volume.trackCount, volume.chapterCount "
                "FROM LibraryVolume AS volume "
                "JOIN LibraryMediaVersion AS media ON media.id = volume.mediaVersionId "
                "WHERE media.workId = :work_id AND volume.hidden = 0"
            ),
            {"work_id": first.work_id},
        )
        .mappings()
        .all()
    )
    assert [dict(row) for row in volumes] == [
        {"id": first.volume_id, "trackCount": 2, "chapterCount": 2}
    ]


def test_audio_bootstrap_range_head_and_completion_follow_volume_progress(
    client, db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    result, _audio_dir = _import_audio_fixture(
        db_session, test_settings, monkeypatch, tmp_path
    )
    stored_hashes = (
        db_session.execute(
            text(
                "SELECT `fingerprint`, `fullHash` FROM `LibraryFile` "
                "WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    assert stored_hashes
    assert all(row["fingerprint"] is None for row in stored_hashes)
    assert all(row["fullHash"] is None for row in stored_hashes)

    bootstrap_response = client.get(
        f"/api/reader/v3/volumes/{result.volume_id}/bootstrap"
    )
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["readerType"] == "audio"
    assert bootstrap["contentFingerprint"].startswith("sha256:")
    assert (
        client.get(f"/api/reader/v3/volumes/{result.volume_id}/bootstrap").json()[
            "data"
        ]["contentFingerprint"]
        == bootstrap["contentFingerprint"]
    )
    assert [track["trackNumber"] for track in bootstrap["files"]] == [2, 10]
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
        "schemaVersion": 3,
        "clientId": "audio-player",
        "contentFingerprint": bootstrap["contentFingerprint"],
        "location": {
            "type": "audio",
            "fileId": final_track["id"],
            "chapterId": bootstrap["units"][-1]["id"],
            "positionMs": final_track["durationMs"],
        },
    }
    seek = client.put(
        f"/api/reader/v3/volumes/{result.volume_id}/progress",
        json={
            **common,
            "mutationId": "seek-to-end",
            "clientSequence": 1,
            "percent": 99.999,
        },
    )
    assert seek.status_code == 200
    assert seek.json()["data"]["progress"]["percent"] == 99.999
    assert (
        client.get(f"/api/reader/v3/volumes/{result.volume_id}/bootstrap").json()[
            "data"
        ]["mediaVersion"]["completed"]
        is False
    )

    ended = client.put(
        f"/api/reader/v3/volumes/{result.volume_id}/progress",
        json={
            **common,
            "mutationId": "media-ended",
            "clientSequence": 2,
            "percent": 100,
        },
    )
    assert ended.status_code == 200
    assert ended.json()["data"]["progress"]["percent"] == 100
    assert (
        client.get(f"/api/reader/v3/volumes/{result.volume_id}/bootstrap").json()[
            "data"
        ]["mediaVersion"]["completed"]
        is True
    )

    paused_after_finish = client.put(
        f"/api/reader/v3/volumes/{result.volume_id}/progress",
        json={
            **common,
            "mutationId": "pause-after-finish",
            "clientSequence": 3,
            "percent": 10,
            "location": {
                "type": "audio",
                "fileId": first_track["id"],
                "chapterId": bootstrap["units"][0]["id"],
                "positionMs": 10_000,
            },
        },
    )
    assert paused_after_finish.status_code == 200
    assert (
        client.get(f"/api/reader/v3/volumes/{result.volume_id}/bootstrap").json()[
            "data"
        ]["mediaVersion"]["completed"]
        is False
    )


def test_three_media_filters_tabs_preferences_and_completion_are_user_scoped(
    client, db_session
) -> None:
    _initialize_schema(db_session)
    user_a = _login(client, db_session, email="listener-a@example.com")
    db_session.add(
        LibraryWork(
            id="mixed-work",
            origin="MANUAL",
            title="Mixed media work",
            normalized_title="mixed media work",
            author="Author",
            normalized_author="author",
            work_type="EPUB",
            tags="[]",
        )
    )
    db_session.commit()
    for media_version_id, volume_id, media_kind, fmt in (
        ("mixed-ebook", "mixed-ebook-volume", "EBOOK", "EPUB"),
        ("mixed-comic", "mixed-comic-volume", "COMIC", "COMIC"),
        ("mixed-audio", "mixed-audio-volume", "AUDIOBOOK", "AUDIO"),
    ):
        _insert_media_volume(
            db_session,
            media_version_id=media_version_id,
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

    db_session.execute(
        text(
            "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES ('workDetail.tabOrder', :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = CURRENT_TIMESTAMP"
        ),
        {"value": '["AUDIOBOOK","COMIC","EBOOK","STRUCTURE"]'},
    )
    db_session.commit()
    detail = client.get("/api/works/mixed-work").json()["data"]["book"]
    assert [tab["key"] for tab in detail["detailTabs"]] == [
        "AUDIOBOOK",
        "COMIC",
        "EBOOK",
        "STRUCTURE",
    ]
    saved = client.put(
        "/api/works/mixed-work/detail-preference", json={"selectedTab": "COMIC"}
    )
    assert saved.status_code == 200
    assert (
        client.get("/api/works/mixed-work").json()["data"]["book"]["selectedDetailTab"]
        == "COMIC"
    )

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
    assert all(item["completed"] for item in completed_for_a["mediaVersions"])

    _login(client, db_session, email="listener-b@example.com")
    detail_for_b = client.get("/api/works/mixed-work").json()["data"]["book"]
    assert detail_for_b["completed"] is False
    assert all(
        volume["progress"] == 0
        for media_version in detail_for_b["mediaVersions"]
        for volume in media_version["volumes"]
    )

    _login(client, db_session, email="listener-a@example.com")
    db_session.add(
        LibraryVolume(
            id="mixed-ebook-volume-2",
            media_version_id="mixed-ebook",
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
        id="switch-work",
        origin="MANUAL",
        title="Two audio volumes",
        normalized_title="two audio volumes",
        work_type="AUDIO",
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id="switch-audio", work_id=work.id, media_kind="AUDIOBOOK"
    )
    volumes = [
        LibraryVolume(
            id=f"audio-{suffix}-volume",
            media_version_id=media_version.id,
            origin="MANUAL",
            title=f"Volume {suffix.upper()}",
            sort_order=index,
            format="AUDIO",
            resource_key=f"test:audio-{suffix}-volume",
            duration_ms=100_000,
        )
        for index, suffix in enumerate(("a", "b"))
    ]
    db_session.add_all([work, media_version, *volumes])
    db_session.flush()
    db_session.add_all(
        [
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
            ),
            UserMediaHistory(
                id="switch-history",
                user_id=user.id,
                media_version_id=media_version.id,
                last_volume_id=volumes[1].id,
            ),
        ]
    )
    db_session.commit()

    detail = client.get("/api/works/switch-work").json()["data"]
    assert len(detail["book"]["mediaVersions"]) == 1
    assert [
        volume["id"] for volume in detail["book"]["mediaVersions"][0]["volumes"]
    ] == ["audio-a-volume", "audio-b-volume"]
    assert detail["book"]["continueVolumeId"] == "audio-a-volume"

    selected_a = client.get(
        "/api/works/switch-work",
        params={"detailTab": "AUDIOBOOK", "volumeId": "audio-a-volume"},
    ).json()["data"]["activeMedia"]
    assert selected_a["mediaVersionId"] == "switch-audio"
    assert selected_a["selectedVolumeId"] == "audio-a-volume"
    assert selected_a["progress"] == 0
    assert selected_a["status"] == "UNREAD"
    assert selected_a["primaryAction"]["href"] == "/listen/audio-a-volume"

    selected_b = client.get(
        "/api/works/switch-work",
        params={"detailTab": "AUDIOBOOK", "volumeId": "audio-b-volume"},
    ).json()["data"]["activeMedia"]
    assert selected_b["selectedVolumeId"] == "audio-b-volume"
    assert selected_b["progress"] == 80
    assert selected_b["progressStatus"] == "READING"
    assert selected_b["primaryAction"]["href"] == "/listen/audio-b-volume"

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
        )
    )
    db_session.query(LibraryReadingProgress).filter(
        LibraryReadingProgress.id == "progress-b"
    ).update({"percent": 100})
    db_session.commit()
    completed = client.get("/api/works/switch-work").json()["data"]["book"]
    assert completed["completed"] is True
    assert completed["mediaVersions"][0]["completed"] is True
    assert completed["continueVolumeId"] == "audio-b-volume"


def test_multi_audio_upload_saves_raw_tracks_without_creating_bundle_task(
    client, db_session, test_settings
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    target = test_settings.resolved_monitor_root / "uploads"
    target.mkdir(parents=True, exist_ok=True)
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
    assert data["autoImport"] is False
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


def test_failed_audio_bundle_can_be_retried_and_resets_all_assets(
    client, db_session, test_settings
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    bundle = test_settings.resolved_monitor_root / "retry-bundle"
    bundle.mkdir(parents=True)
    (bundle / "01.mp3").write_bytes(b"first")
    (bundle / "02.mp3").write_bytes(b"second")
    task, _created = enqueue_import_task(
        db_session,
        bundle,
        origin="MANUAL",
        original_name=bundle.name,
    )
    db_session.execute(
        text(
            "UPDATE `ImportTask` SET `status` = 'FAILED', `retryable` = 1, `progress` = 100, "
            "`processedAssetCount` = 1, `errorCode` = 'AUDIO_IMPORT_FAILED', `errorSummary` = 'bad tags' WHERE `id` = :id"
        ),
        {"id": task.id},
    )
    db_session.execute(
        text(
            "UPDATE `ImportAsset` SET `status` = 'FAILED', `errorCode` = 'AUDIO_IMPORT_FAILED', "
            "`errorSummary` = 'bad tags' WHERE `importTaskId` = :id"
        ),
        {"id": task.id},
    )
    db_session.commit()

    response = client.post(f"/api/import-tasks/{task.id}/retry")
    assert response.status_code == 200
    reset_task = (
        db_session.execute(
            text(
                "SELECT `status`, `retryable`, `progress`, `processedAssetCount`, `errorCode`, `errorSummary` "
                "FROM `ImportTask` WHERE `id` = :id"
            ),
            {"id": task.id},
        )
        .mappings()
        .one()
    )
    assert dict(reset_task) == {
        "status": "PENDING",
        "retryable": 0,
        "progress": 0,
        "processedAssetCount": 0,
        "errorCode": None,
        "errorSummary": None,
    }
    assets = (
        db_session.execute(
            text(
                "SELECT `status`, `fileId`, `errorCode`, `errorSummary` FROM `ImportAsset` WHERE `importTaskId` = :id"
            ),
            {"id": task.id},
        )
        .mappings()
        .all()
    )
    assert len(assets) == 2
    assert all(
        dict(row)
        == {
            "status": "PENDING",
            "fileId": None,
            "errorCode": None,
            "errorSummary": None,
        }
        for row in assets
    )


def test_completed_directory_bundle_can_enqueue_again_after_a_new_episode(
    db_session, test_settings
) -> None:
    _initialize_schema(db_session)
    bundle = test_settings.resolved_monitor_root / "连载有声书"
    bundle.mkdir(parents=True)
    (bundle / "《连载有声书》第1集.m4a").write_bytes(b"episode-one")
    first, first_created = enqueue_import_task(
        db_session, bundle, origin="WATCH", original_name=bundle.name
    )
    assert first_created is True
    db_session.execute(
        text("UPDATE `ImportTask` SET `status` = 'COMPLETED' WHERE `id` = :id"),
        {"id": first.id},
    )
    db_session.commit()

    (bundle / "《连载有声书》第2集.m4a").write_bytes(b"episode-two")
    second, second_created = enqueue_import_task(
        db_session,
        bundle,
        origin="WATCH",
        original_name=bundle.name,
        allow_terminal_requeue=True,
    )

    assert second_created is True
    assert second.id != first.id
    assert second.asset_count == 2
    assert (
        db_session.execute(
            text("SELECT COUNT(*) FROM `ImportAsset` WHERE `importTaskId` = :id"),
            {"id": second.id},
        ).scalar()
        == 2
    )


def test_nested_author_directory_is_not_used_as_audiobook_author(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    author_dir = test_settings.resolved_monitor_root / "Ursula K. Le Guin"
    book_dir = author_dir / "The Left Hand of Darkness"
    disc_one = book_dir / "Disc 1 of 2"
    disc_two = book_dir / "CD 2"
    disc_one.mkdir(parents=True)
    disc_two.mkdir()
    tracks = [
        disc_two / "01 - Chapter 3.mp3",
        disc_one / "02 - Chapter 2.mp3",
        disc_one / "01 - Chapter 1.mp3",
    ]
    for index, path in enumerate(tracks, start=1):
        path.write_bytes((f"emby-track-{index}-" * index).encode())
    cover = io.BytesIO()
    Image.new("RGB", (24, 32), "darkgreen").save(cover, format="PNG")
    (book_dir / "folder.jpg").write_bytes(cover.getvalue())

    assert (
        audio_metadata_module.audio_bundle_root(
            tracks[0], test_settings.resolved_monitor_root
        )
        == book_dir.resolve()
    )
    assert set(audio_metadata_module.collect_audio_bundle_files(book_dir)) == {
        tracks[0].resolve(),
        tracks[1].resolve(),
        tracks[2].resolve(),
    }
    queue = _RecordingQueue()
    summary = scan_directory_for_imports(
        test_settings.resolved_monitor_root,
        MonitorFolderConfig(
            id="emby",
            root_path=str(test_settings.resolved_monitor_root),
            min_file_size_bytes=0,
        ),
        queue,
    )
    assert summary.candidates_found == 1
    assert queue.paths == [book_dir.resolve()]

    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _emby_audio_metadata(path),
    )
    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=book_dir, origin="WATCH", original_name=book_dir.name
        ),
    )

    work = (
        db_session.execute(
            text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
            {"id": result.work_id},
        )
        .mappings()
        .one()
    )
    assert dict(work) == {"title": "The Left Hand of Darkness", "author": "未知作者"}
    imported_tracks = (
        db_session.execute(
            text(
                "SELECT `discNumber`, `trackNumber`, `sortOrder` FROM `LibraryFile` "
                "WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    assert [
        (row["discNumber"], row["trackNumber"], row["sortOrder"])
        for row in imported_tracks
    ] == [(1, 1, 0), (1, 2, 1), (2, 1, 2)]
    cover_path = db_session.execute(
        text("SELECT `coverPath` FROM `LibraryVolume` WHERE `id` = :id"),
        {"id": result.volume_id},
    ).scalar_one()
    assert Path(cover_path).suffix == ".png"
    assert Path(cover_path).read_bytes() == cover.getvalue()


def test_multivolume_directory_uses_embedded_identity_and_filters_reader_bootstrap(
    client, db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    user = _login(client, db_session, email="multi-volume-audio@example.com")
    book_dir = (
        test_settings.resolved_monitor_root / "[Ghost Blows Out the Light][Author A]"
    )
    first_volume = book_dir / "Vol.1"
    second_volume = book_dir / "Ghost Blows Out the Light Desert"
    first_volume.mkdir(parents=True)
    second_volume.mkdir()
    first_track = first_volume / "01.mp3"
    second_track = second_volume / "02.mp3"
    first_track.write_bytes(b"multi-volume-track-one")
    second_track.write_bytes(b"multi-volume-track-two")

    structure = audio_metadata_module.inspect_audio_bundle(book_dir)
    assert structure is not None
    assert structure.title == "Ghost Blows Out the Light"
    assert structure.author == "Author A"
    assert [volume.title for volume in structure.volumes] == [
        "Vol.1",
        "Ghost Blows Out the Light Desert",
    ]
    assert [volume.volume_index for volume in structure.volumes] == [1, None]
    queue = _RecordingQueue()
    scan_directory_for_imports(
        test_settings.resolved_monitor_root,
        MonitorFolderConfig(
            id="multi-volume",
            root_path=str(test_settings.resolved_monitor_root),
            min_file_size_bytes=0,
        ),
        queue,
    )
    assert queue.paths == [book_dir.resolve()]

    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _emby_audio_metadata(path),
    )
    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=book_dir, origin="WATCH", original_name=book_dir.name
        ),
    )

    work = (
        db_session.execute(
            text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
            {"id": result.work_id},
        )
        .mappings()
        .one()
    )
    assert dict(work) == {"title": "Ghost Blows Out the Light", "author": "Author A"}
    volumes = (
        db_session.execute(
            text(
                "SELECT `id`, `title`, `volumeIndex`, `sortOrder` "
                "FROM `LibraryVolume` WHERE `mediaVersionId` = :media_version_id ORDER BY `sortOrder`"
            ),
            {"media_version_id": result.media_version_id},
        )
        .mappings()
        .all()
    )
    assert [
        (row["title"], row["volumeIndex"], row["sortOrder"]) for row in volumes
    ] == [
        ("Vol.1", 1, 0),
        ("Ghost Blows Out the Light Desert", None, 1),
    ]

    first_bootstrap = client.get(f"/api/reader/v3/volumes/{volumes[0]['id']}/bootstrap")
    second_bootstrap = client.get(
        f"/api/reader/v3/volumes/{volumes[1]['id']}/bootstrap"
    )
    assert first_bootstrap.status_code == 200
    assert second_bootstrap.status_code == 200
    assert [
        track["trackNumber"] for track in first_bootstrap.json()["data"]["files"]
    ] == [1]
    assert [
        track["trackNumber"] for track in second_bootstrap.json()["data"]["files"]
    ] == [2]
    assert [unit["title"] for unit in first_bootstrap.json()["data"]["units"]] == [
        "Chapter 1"
    ]
    assert [unit["title"] for unit in second_bootstrap.json()["data"]["units"]] == [
        "Chapter 2"
    ]

    for index, (volume, percent) in enumerate(
        zip(volumes, (100, 0), strict=True), start=1
    ):
        db_session.execute(
            text(
                "INSERT INTO `LibraryReadingProgress` "
                "(`id`, `userId`, `volumeId`, `readerType`, `position`, `percent`, "
                "`extra`, `schemaVersion`, `locationType`, `locationJson`, `updatedAt`) "
                "VALUES (:id, :user_id, :volume_id, 'audio', '0', :percent, "
                "'{}', 3, 'audio', '{}', :updated_at)"
            ),
            {
                "id": f"multi-volume-progress-{index}",
                "user_id": user.id,
                "volume_id": volume["id"],
                "percent": percent,
                "updated_at": f"2026-07-24T00:00:0{index}+00:00",
            },
        )
    db_session.commit()
    detail = client.get(
        f"/api/works/{result.work_id}",
        params={"detailTab": "AUDIOBOOK", "volumeId": volumes[0]["id"]},
    ).json()["data"]
    selected_media_version = next(
        item
        for item in detail["book"]["mediaVersions"]
        if item["id"] == result.media_version_id
    )
    assert selected_media_version["completed"] is False
    assert [volume["progress"] for volume in selected_media_version["volumes"]] == [
        100,
        0,
    ]
    assert detail["book"]["continueVolumeId"] == volumes[1]["id"]
    assert detail["activeMedia"]["progress"] == 100


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


def test_emby_flat_layout_appends_strictly_named_chapters_to_one_volume(
    client, db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    _login(client, db_session, email="emby-flat@example.com")
    root = test_settings.resolved_monitor_root
    root.mkdir(parents=True, exist_ok=True)
    paths = [
        root / "10- Flat Book - Chapter 10.mp3",
        root / "1- Flat Book - Chapter 1.mp3",
        root / "2- Flat Book - Chapter 2.mp3",
    ]
    for index, path in enumerate(paths, start=1):
        path.write_bytes((f"flat-track-{index}-" * index).encode())
    ordinary = root / "01 - Ordinary Standalone.m4b"
    missing_prefix = root / "Flat Book - Chapter 1.mp3"
    sibling_epub = root / "Sibling Book.epub"
    ordinary.write_bytes(b"ordinary")
    missing_prefix.write_bytes(b"missing-prefix")
    sibling_epub.write_bytes(b"sibling")
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: replace(
            _emby_audio_metadata(path),
            album="Flat Book",
            author="Flat Author",
            track_number=1,
        ),
    )

    results = [
        import_managed_book(
            db_session,
            test_settings,
            ImportOptions(
                source_file_path=path, origin="WATCH", original_name=path.name
            ),
        )
        for path in paths
    ]

    assert {result.work_id for result in results} == {results[0].work_id}
    assert {result.volume_id for result in results} == {results[0].volume_id}
    work = (
        db_session.execute(
            text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
            {"id": results[0].work_id},
        )
        .mappings()
        .one()
    )
    assert dict(work) == {"title": "Flat Book", "author": "未知作者"}
    volumes = (
        db_session.execute(
            text(
                "SELECT volume.`id`, volume.`trackCount`, volume.`chapterCount` "
                "FROM `LibraryVolume` volume JOIN `LibraryMediaVersion` media "
                "ON media.`id` = volume.`mediaVersionId` "
                "WHERE media.`workId` = :work_id AND volume.`hidden` = 0"
            ),
            {"work_id": results[0].work_id},
        )
        .mappings()
        .all()
    )
    assert [dict(row) for row in volumes] == [
        {"id": results[0].volume_id, "trackCount": 3, "chapterCount": 3}
    ]
    tracks = (
        db_session.execute(
            text(
                "SELECT `trackNumber`, `sortOrder` FROM `LibraryFile` "
                "WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": results[0].volume_id},
        )
        .mappings()
        .all()
    )
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [
        (1, 0),
        (2, 1),
        (10, 2),
    ]
    bootstrap = client.get(f"/api/reader/v3/volumes/{results[0].volume_id}/bootstrap")
    assert bootstrap.status_code == 200
    assert [track["trackNumber"] for track in bootstrap.json()["data"]["files"]] == [
        1,
        2,
        10,
    ]

    assert importer_module._flat_audio_filename_title(ordinary) is None
    assert importer_module._flat_audio_filename_title(missing_prefix) is None


class _RecordingQueue:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def enqueue(self, path: Path, _folder: MonitorFolderConfig) -> None:
        self.paths.append(path.resolve())


def test_mixed_monitor_root_does_not_swallow_standalone_audio_files(tmp_path) -> None:
    root = tmp_path / "monitor"
    root.mkdir()
    flat_first = root / "01- Wiki Flat Book - Chapter 01.mp3"
    flat_second = root / "02- Wiki Flat Book - Chapter 02.mp3"
    standalone = root / "[Standalone Audiobook][Author].m4b"
    sibling_epub = root / "Sibling Book.epub"
    for path in (flat_first, flat_second, standalone, sibling_epub):
        path.write_bytes(b"fixture")
    folder = MonitorFolderConfig(
        id="watch",
        root_path=str(root),
        min_file_size_bytes=0,
    )

    queue = _RecordingQueue()
    summary = scan_directory_for_imports(root, folder, queue)

    assert summary.candidates_found == 4
    assert set(queue.paths) == {
        flat_first.resolve(),
        flat_second.resolve(),
        standalone.resolve(),
        sibling_epub.resolve(),
    }

    structure = audio_metadata_module.inspect_audio_bundle(root)
    assert structure is not None
    services = SimpleNamespace(inspect_audio_bundle=lambda _path: structure)
    assert managed_book_module._resolve_audio_import_source(services, flat_first) == (
        flat_first,
        None,
    )
    assert managed_book_module._resolve_audio_import_source(services, standalone) == (
        standalone,
        None,
    )


def test_watcher_live_and_rescan_only_bundle_proven_book_directories(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "monitor"
    author = root / "作者目录"
    author.mkdir(parents=True)
    book_a = author / "Book A.m4b"
    book_b = author / "Book B.m4b"
    sibling_epub = author / "Book C.epub"
    for path in (book_a, book_b, sibling_epub):
        path.write_bytes(b"fixture")
    split_book = root / "分轨书"
    split_book.mkdir()
    first_track = split_book / "01-序章.mp3"
    second_track = split_book / "02-正文.mp3"
    sibling_pdf = split_book / "附录.pdf"
    for path in (first_track, second_track, sibling_pdf):
        path.write_bytes(b"fixture")
    titled_split_book = root / "我当阴阳先生的那几年（多人有声剧）"
    titled_split_book.mkdir()
    titled_first = titled_split_book / "《我当阴阳先生那几年》 第1集.m4a"
    titled_second = titled_split_book / "《我当阴阳先生那几年》第153集.m4a"
    titled_appendix = titled_split_book / "附录.pdf"
    for path in (titled_first, titled_second, titled_appendix):
        path.write_bytes(b"fixture")
    folder = MonitorFolderConfig(id="watch", root_path=str(root), min_file_size_bytes=0)

    queue = _RecordingQueue()
    summary = scan_directory_for_imports(root, folder, queue)
    assert summary.candidates_found == 7
    assert set(queue.paths) == {
        book_a.resolve(),
        book_b.resolve(),
        sibling_epub.resolve(),
        split_book.resolve(),
        sibling_pdf.resolve(),
        titled_split_book.resolve(),
        titled_appendix.resolve(),
    }

    manager = object.__new__(WorkerManager)
    manager.db_factory = lambda: nullcontext(object())
    manager._imports_paused = False
    scheduled: list[Path] = []
    monkeypatch.setattr(
        watcher_module, "import_queue_at_high_watermark", lambda _db: False
    )
    monkeypatch.setattr(
        watcher_module,
        "schedule_import_scan_job",
        lambda _db, **kwargs: scheduled.append(kwargs["root_path"].resolve()),
    )
    monkeypatch.setattr(
        watcher_module,
        "enqueue_import_task",
        lambda *_args, **_kwargs: pytest.fail(
            "audio events must schedule a directory scan"
        ),
    )
    state = WatchState(observer=None, root_path=root.resolve(), config_signature="test")  # type: ignore[arg-type]
    manager.schedule_import(book_a, folder, state)
    manager.schedule_import(book_b, folder, state)
    manager.schedule_import(first_track, folder, state)
    manager.schedule_import(second_track, folder, state)
    assert scheduled == [
        author.resolve(),
        author.resolve(),
        split_book.resolve(),
        split_book.resolve(),
    ]


def test_audio_bundle_detection_applies_ignore_rules_before_mixed_content_check(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "monitor"
    book_dir = root / "我靠充值当武帝"
    book_dir.mkdir(parents=True)
    first_track = book_dir / "我靠充值当武帝001-穿越了.m4a"
    second_track = book_dir / "我靠充值当武帝002-充钱令人快乐.m4a"
    for path in (first_track, second_track):
        path.write_bytes(b"fixture")
    (book_dir / "desc.txt").write_text("description")
    (book_dir / "reader.txt").write_text("reader")
    folder = MonitorFolderConfig(
        id="watch",
        root_path=str(root),
        ignore_patterns="*.txt",
        min_file_size_bytes=0,
    )

    queue = _RecordingQueue()
    summary = scan_directory_for_imports(root, folder, queue)
    assert queue.paths == [book_dir.resolve()]
    assert summary.ignored_files == 2

    manager = object.__new__(WorkerManager)
    manager.db_factory = lambda: nullcontext(object())
    manager._imports_paused = False
    scheduled: list[Path] = []
    monkeypatch.setattr(
        watcher_module, "import_queue_at_high_watermark", lambda _db: False
    )
    monkeypatch.setattr(
        watcher_module,
        "schedule_import_scan_job",
        lambda _db, **kwargs: scheduled.append(kwargs["root_path"].resolve()),
    )
    monkeypatch.setattr(
        watcher_module,
        "enqueue_import_task",
        lambda *_args, **_kwargs: pytest.fail(
            "audio events must schedule a directory scan"
        ),
    )
    state = WatchState(observer=None, root_path=root.resolve(), config_signature="test")  # type: ignore[arg-type]
    manager.schedule_import(first_track, folder, state)
    assert scheduled == [book_dir.resolve()]


def test_audio_bundle_detection_applies_minimum_size_before_mixed_content_check(
    tmp_path,
) -> None:
    root = tmp_path / "monitor"
    book_dir = root / "没有章节号的有声书"
    book_dir.mkdir(parents=True)
    first_track = book_dir / "开场.m4a"
    second_track = book_dir / "继续.m4a"
    first_track.write_bytes(b"a" * 16)
    second_track.write_bytes(b"b" * 16)
    (book_dir / "desc.txt").write_bytes(b"x")
    folder = MonitorFolderConfig(
        id="watch",
        root_path=str(root),
        min_file_size_bytes=10,
    )

    queue = _RecordingQueue()
    summary = scan_directory_for_imports(root, folder, queue)

    assert queue.paths == [book_dir.resolve()]
    assert summary.candidates_found == 1
    assert summary.ignored_files == 1


def test_monitor_root_audio_tracks_are_enqueued_as_one_directory(
    tmp_path, monkeypatch
) -> None:
    root = tmp_path / "鬼出棺"
    root.mkdir()
    first_track = root / "鬼出棺第001章刑台屠军.m4a"
    second_track = root / "鬼出棺第002章谢半鬼.m4a"
    for path in (first_track, second_track):
        path.write_bytes(b"fixture")
    folder = MonitorFolderConfig(
        id="watch",
        root_path=str(root),
        min_file_size_bytes=0,
    )

    queue = _RecordingQueue()
    summary = scan_directory_for_imports(root, folder, queue)
    assert summary.candidates_found == 1
    assert queue.paths == [root.resolve()]

    manager = object.__new__(WorkerManager)
    manager.db_factory = lambda: nullcontext(object())
    manager._imports_paused = False
    scheduled: list[Path] = []
    monkeypatch.setattr(
        watcher_module, "import_queue_at_high_watermark", lambda _db: False
    )
    monkeypatch.setattr(
        watcher_module,
        "schedule_import_scan_job",
        lambda _db, **kwargs: scheduled.append(kwargs["root_path"].resolve()),
    )
    monkeypatch.setattr(
        watcher_module,
        "enqueue_import_task",
        lambda *_args, **_kwargs: pytest.fail(
            "audio events must schedule a directory scan"
        ),
    )
    state = WatchState(observer=None, root_path=root.resolve(), config_signature="test")  # type: ignore[arg-type]
    manager.schedule_import(first_track, folder, state)
    assert scheduled == [root.resolve()]


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


def test_directory_first_episode_bundle_imports_as_one_ordered_audiobook(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    book_dir = (
        test_settings.resolved_monitor_root / "我当阴阳先生的那几年（多人有声剧）"
    )
    book_dir.mkdir(parents=True)
    names = [
        "《我当阴阳先生那几年》 第153集.m4a",
        "《我当阴阳先生那几年》第12集.m4a",
        "《我当阴阳先生那几年》第1集.m4a",
    ]
    for index, name in enumerate(names, start=1):
        (book_dir / name).write_bytes((f"episode-{index}-" * index).encode())
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _episode_audio_metadata(path),
    )

    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=book_dir, origin="WATCH", original_name=book_dir.name
        ),
    )

    work = (
        db_session.execute(
            text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
            {"id": result.work_id},
        )
        .mappings()
        .one()
    )
    assert work["title"] == book_dir.name
    assert work["author"] == "未知作者"
    volumes = (
        db_session.execute(
            text(
                "SELECT volume.`id`, volume.`trackCount`, volume.`chapterCount` "
                "FROM `LibraryVolume` volume JOIN `LibraryMediaVersion` media "
                "ON media.`id` = volume.`mediaVersionId` "
                "WHERE media.`workId` = :work_id AND volume.`hidden` = 0"
            ),
            {"work_id": result.work_id},
        )
        .mappings()
        .all()
    )
    assert [dict(row) for row in volumes] == [
        {"id": result.volume_id, "trackCount": 3, "chapterCount": 3}
    ]
    tracks = (
        db_session.execute(
            text(
                "SELECT `trackNumber`, `sortOrder`, `path` FROM `LibraryFile` WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [
        (1, 0),
        (12, 1),
        (153, 2),
    ]
    units = (
        db_session.execute(
            text(
                "SELECT `title`, `sortOrder` FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    assert [row["sortOrder"] for row in units] == [1, 2, 3]
    assert [row["title"] for row in units] == [
        Path(name).stem for name in [names[2], names[1], names[0]]
    ]

    added = book_dir / "《我当阴阳先生那几年》第2集.m4a"
    added.write_bytes(b"new-episode-two")
    updated = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=book_dir, origin="WATCH", original_name=book_dir.name
        ),
    )
    assert updated.volume_id == result.volume_id
    updated_tracks = (
        db_session.execute(
            text(
                "SELECT `trackNumber`, `sortOrder` FROM `LibraryFile` WHERE `volumeId` = :volume_id ORDER BY `sortOrder`"
            ),
            {"volume_id": result.volume_id},
        )
        .mappings()
        .all()
    )
    assert [(row["trackNumber"], row["sortOrder"]) for row in updated_tracks] == [
        (1, 0),
        (2, 1),
        (12, 2),
        (153, 3),
    ]


def test_rescan_reconciles_tracks_split_across_volumes_and_preserves_progress(
    client, db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    user = _login(client, db_session, email="reconcile-audio@example.com")
    book_dir = (
        test_settings.resolved_monitor_root / "我当阴阳先生的那几年（多人有声剧）"
    )
    book_dir.mkdir(parents=True)
    paths = [
        book_dir / f"《我当阴阳先生那几年》第{number}集.m4a" for number in [3, 1, 2]
    ]
    for index, path in enumerate(paths, start=1):
        path.write_bytes((f"legacy-episode-{index}-" * index).encode())
    monkeypatch.setattr(
        SessionImportOrchestrationServices,
        "parse_audio_metadata",
        lambda _services, path: _episode_audio_metadata(path),
    )

    resolve_audio_import_source = managed_book_module._resolve_audio_import_source
    monkeypatch.setattr(
        managed_book_module,
        "_resolve_audio_import_source",
        lambda _services, source: (source, None),
    )
    legacy_results = [
        import_managed_book(
            db_session,
            test_settings,
            ImportOptions(
                source_file_path=path,
                origin="WATCH",
                original_name=path.name,
                requested_title=f"错误作品 {index}",
                requested_author="未知作者",
            ),
        )
        for index, path in enumerate(paths, start=1)
    ]
    monkeypatch.setattr(
        managed_book_module,
        "_resolve_audio_import_source",
        resolve_audio_import_source,
    )
    historical_hashes: dict[str, tuple[str, str]] = {}
    for index, result in enumerate(legacy_results, start=1):
        file_row = (
            db_session.execute(
                text("SELECT `id` FROM `LibraryFile` WHERE `volumeId` = :volume_id"),
                {"volume_id": result.volume_id},
            )
            .mappings()
            .one()
        )
        fingerprint = f"legacy-sample-{index}"
        full_hash = f"{index:064x}"
        historical_hashes[str(file_row["id"])] = (fingerprint, full_hash)
        db_session.execute(
            text(
                "UPDATE `LibraryFile` SET `fingerprint` = :fingerprint, "
                "`fullHash` = :full_hash, `hashStatus` = 'COMPLETED' "
                "WHERE `id` = :file_id"
            ),
            {
                "file_id": file_row["id"],
                "fingerprint": fingerprint,
                "full_hash": full_hash,
            },
        )
    db_session.commit()
    failed_bundle_task, failed_bundle_created = enqueue_import_task(
        db_session,
        book_dir,
        origin="WATCH",
        original_name=book_dir.name,
    )
    assert failed_bundle_created is True
    db_session.execute(
        text("UPDATE `ImportTask` SET `status` = 'FAILED' WHERE `id` = :id"),
        {"id": failed_bundle_task.id},
    )
    db_session.commit()
    known_paths = load_known_import_paths(db_session)
    assert book_dir.resolve() not in known_paths
    rescan_queue = _RecordingQueue()
    scan_directory_for_imports(
        test_settings.resolved_monitor_root,
        MonitorFolderConfig(
            id="watch",
            root_path=str(test_settings.resolved_monitor_root),
            min_file_size_bytes=0,
        ),
        rescan_queue,
        known_paths=known_paths,
    )
    assert book_dir.resolve() in rescan_queue.paths
    legacy_unit_ids = {
        row["id"]
        for row in db_session.execute(
            text(
                "SELECT `id` FROM `LibraryReadingUnit` WHERE `volumeId` IN (:first, :second, :third)"
            ),
            {
                "first": legacy_results[0].volume_id,
                "second": legacy_results[1].volume_id,
                "third": legacy_results[2].volume_id,
            },
        ).mappings()
    }
    legacy_resume = (
        db_session.execute(
            text(
                "SELECT file.`id` AS `fileId`, unit.`id` AS `unitId` "
                "FROM `LibraryFile` file JOIN `LibraryReadingUnit` unit ON unit.`fileId` = file.`id` "
                "WHERE file.`volumeId` = :volume_id LIMIT 1"
            ),
            {"volume_id": legacy_results[1].volume_id},
        )
        .mappings()
        .one()
    )
    legacy_location = {
        "type": "audio",
        "fileId": legacy_resume["fileId"],
        "chapterId": legacy_resume["unitId"],
        "positionMs": 12_345,
    }
    db_session.execute(
        text(
            "INSERT INTO `LibraryReadingProgress` "
            "(`id`, `userId`, `volumeId`, `readerType`, `position`, `percent`, `extra`, "
            "`contentFingerprint`, `locationType`, `locationJson`, `createdAt`, `updatedAt`) "
            "VALUES ('legacy-progress', :user_id, :volume_id, 'audio', '12345', 42, :extra, "
            "'sha256:legacy-single-track', 'audio', :location, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "user_id": user.id,
            "volume_id": legacy_results[1].volume_id,
            "extra": json.dumps(
                {key: value for key, value in legacy_location.items() if key != "type"}
            ),
            "location": json.dumps(legacy_location),
        },
    )
    db_session.commit()

    reconciled = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(
            source_file_path=book_dir, origin="WATCH", original_name=book_dir.name
        ),
    )

    visible_works = (
        db_session.execute(
            text(
                "SELECT `id`, `title` FROM `LibraryWork` WHERE `hidden` = 0 AND `workType` = 'AUDIO'"
            ),
        )
        .mappings()
        .all()
    )
    assert [dict(row) for row in visible_works] == [
        {"id": reconciled.work_id, "title": book_dir.name}
    ]
    visible_volumes = (
        db_session.execute(
            text(
                "SELECT volume.`id`, volume.`trackCount`, volume.`chapterCount` "
                "FROM `LibraryVolume` volume JOIN `LibraryMediaVersion` media "
                "ON media.`id` = volume.`mediaVersionId` "
                "WHERE volume.`hidden` = 0 AND media.`mediaKind` = 'AUDIOBOOK'"
            ),
        )
        .mappings()
        .all()
    )
    assert [dict(row) for row in visible_volumes] == [
        {"id": reconciled.volume_id, "trackCount": 3, "chapterCount": 3}
    ]
    tracks = (
        db_session.execute(
            text(
                "SELECT `id`, `volumeId`, `trackNumber`, `sortOrder`, "
                "`fingerprint`, `fullHash`, `hashStatus` FROM `LibraryFile` "
                "WHERE UPPER(`kind`) = 'AUDIO' ORDER BY `sortOrder`"
            ),
        )
        .mappings()
        .all()
    )
    assert {(row["volumeId"]) for row in tracks} == {reconciled.volume_id}
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [
        (1, 0),
        (2, 1),
        (3, 2),
    ]
    assert {
        str(row["id"]): (
            row["fingerprint"],
            row["fullHash"],
            row["hashStatus"],
        )
        for row in tracks
    } == {
        file_id: (fingerprint, full_hash, "COMPLETED")
        for file_id, (fingerprint, full_hash) in historical_hashes.items()
    }
    assert {
        row["id"]
        for row in db_session.execute(
            text("SELECT `id` FROM `LibraryReadingUnit` WHERE `volumeId` = :volume_id"),
            {"volume_id": reconciled.volume_id},
        ).mappings()
    } == legacy_unit_ids
    progress = (
        db_session.execute(
            text(
                "SELECT `volumeId`, `percent`, `position`, `contentFingerprint`, `locationJson` "
                "FROM `LibraryReadingProgress` WHERE `id` = 'legacy-progress'"
            ),
        )
        .mappings()
        .one()
    )
    assert progress["volumeId"] == reconciled.volume_id
    assert progress["position"] == "12345"
    assert progress["percent"] == pytest.approx(
        12_345 / (60_001 + 60_002 + 60_003) * 100
    )
    assert progress["contentFingerprint"].startswith("sha256:")
    assert progress["contentFingerprint"] != "sha256:legacy-single-track"
    detail = client.get(f"/api/works/{reconciled.work_id}")
    assert detail.status_code == 200
    book = detail.json()["data"]["book"]
    assert len(book["mediaVersions"]) == 1
    assert [volume["id"] for volume in book["mediaVersions"][0]["volumes"]] == [
        reconciled.volume_id
    ]
    bootstrap = client.get(f"/api/reader/v3/volumes/{reconciled.volume_id}/bootstrap")
    assert bootstrap.status_code == 200
    bootstrap_data = bootstrap.json()["data"]
    assert [track["trackNumber"] for track in bootstrap_data["files"]] == [1, 2, 3]
    assert bootstrap_data["resumeFingerprintMismatch"] is False
    assert bootstrap_data["resumeLocation"] == legacy_location | {
        "volumeId": reconciled.volume_id
    }, progress["locationJson"]
