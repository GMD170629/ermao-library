from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import text

import app.api.routes.compat as compat_module
import app.services.audio_metadata as audio_metadata_module
import app.worker.importer as importer_module
import app.worker.watcher as watcher_module
from app.core.auth import hash_password
from app.db.base import Base
from app.db.bootstrap import apply_schema
from app.models.auth import User
from app.services.audio_metadata import (
    AudioChapterMetadata,
    AudioFileMetadata,
    parse_audio_metadata,
)
from app.worker.importer import ImportOptions, import_managed_book
from app.worker.persistent_import_queue import enqueue_import_task, process_import_task
from app.worker.watcher import (
    MonitorFolderConfig,
    WatchState,
    WorkerManager,
    scan_directory_for_imports,
)
from tests.test_worker_importer import write_epub_metadata_fixture


def _initialize_schema(db_session) -> None:
    db_session.rollback()
    Base.metadata.create_all(db_session.get_bind())
    apply_schema(db_session.get_bind())
    db_session.expire_all()


def _login(client, db_session, *, email: str = "audio-admin@example.com", password: str = "starshipnas") -> User:
    user = db_session.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(email=email, name=email.split("@", 1)[0], password_hash=hash_password(password), role="admin")
        db_session.add(user)
        db_session.commit()
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return user


def _fake_audio_metadata(path: Path, *, album: str = "三体", author: str = "刘慈欣") -> AudioFileMetadata:
    number = int("".join(character for character in path.stem if character.isdigit()) or "1")
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
            AudioChapterMetadata(title=f"第 {number} 章", start_ms=0, end_ms=duration_ms),
        ),
        raw_tags={"test": True},
    )


def _episode_audio_metadata(path: Path) -> AudioFileMetadata:
    number = int("".join(character for character in path.stem.split("第")[-1].split("集")[0] if character.isdigit()) or "1")
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
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _fake_audio_metadata)
    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=audio_dir, origin="MANUAL", original_name=audio_dir.name),
    )
    return result, audio_dir


def _insert_edition(
    db_session,
    *,
    edition_id: str,
    work_id: str,
    media_kind: str,
    fmt: str,
    primary: bool = True,
) -> None:
    db_session.execute(
        text(
            "INSERT INTO `LibraryEdition` "
            "(`id`, `workId`, `origin`, `mediaKind`, `format`, `versionName`, `versionKey`, `importStatus`, "
            "`sizeBytes`, `coverStatus`, `primary`, `hidden`, `createdAt`, `updatedAt`) "
            "VALUES (:id, :work_id, 'MANUAL', :media_kind, :format, :name, :key, 'COMPLETED', "
            "0, 'PENDING', :primary, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "id": edition_id,
            "work_id": work_id,
            "media_kind": media_kind,
            "format": fmt,
            "name": media_kind,
            "key": f"test:{edition_id}",
            "primary": 1 if primary else 0,
        },
    )
    db_session.commit()


def test_m4a_alac_is_rejected_and_container_extension_never_implies_aac(tmp_path, monkeypatch) -> None:
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
    assert audio_metadata_module._mutagen_codec(source, SimpleNamespace(codec_description="Apple Lossless Audio Codec")) == "alac"
    assert audio_metadata_module._mutagen_codec(source, SimpleNamespace(codec_description="AAC LC")) == "aac"
    assert audio_metadata_module._mutagen_codec(source, SimpleNamespace(codec_description="mp4a.40.2")) == "aac"
    assert audio_metadata_module._mutagen_codec(source, SimpleNamespace(codec_description="mp4a.40.5")) == "aac"
    assert audio_metadata_module._mutagen_codec(source, SimpleNamespace(codec_description="mp4a.40.29")) == "aac"
    assert audio_metadata_module._mutagen_codec(source, SimpleNamespace(codec_description="mp4a.40.36")) == "mp4a.40.36"


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
    monkeypatch.setattr(audio_metadata_module, "_read_with_ffprobe", lambda _path, timeout_seconds: {})

    parsed = parse_audio_metadata(source)

    assert parsed.codec == "aac"
    assert parsed.title == "RFC 6381 AAC"


def test_audio_parser_repairs_gbk_bytes_misdeclared_as_latin1(tmp_path, monkeypatch) -> None:
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
        sub_frames=SimpleNamespace(getall=lambda key: [chapter_title] if key == "TIT2" else []),
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
            info=SimpleNamespace(length=60, bitrate=128_000, sample_rate=44_100, channels=2),
        ),
    )
    monkeypatch.setattr(audio_metadata_module, "_read_with_ffprobe", lambda _path, timeout_seconds: {})

    parsed = parse_audio_metadata(source)

    assert parsed.title == "01.祥林嫂之死"
    assert parsed.album == "百家讲坛_《鲁迅》"
    assert parsed.author == "孔庆东"
    assert [chapter.title for chapter in parsed.chapters] == ["第一章"]
    repairs = parsed.raw_tags["mutagen"]["encodingRepairs"]
    assert [(item["tag"], item["declaredEncoding"], item["detectedEncoding"]) for item in repairs] == [
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
        ("Beyoncé".encode("utf-8").decode("latin-1"), "Beyoncé", "utf-8"),
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
def test_misdeclared_tag_repair_preserves_normal_english_and_western_text(value: str) -> None:
    assert audio_metadata_module._repair_misdecoded_text(value) == (value, None)


def test_misdeclared_tag_repair_keeps_ambiguous_legacy_text_unchanged() -> None:
    ambiguous = "宮崎駿".encode("shift_jis").decode("latin-1")

    assert audio_metadata_module._repair_misdecoded_text(
        ambiguous,
        declared_encoding="latin-1",
    ) == (ambiguous, None)


def test_audio_parser_falls_back_when_mutagen_fails_and_caps_probe_output(tmp_path, monkeypatch) -> None:
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


def test_audio_cover_validation_rejects_unknown_oversized_and_high_pixel_images(monkeypatch) -> None:
    output = io.BytesIO()
    Image.new("RGB", (16, 16), "navy").save(output, format="PNG")
    valid = importer_module._validated_audio_cover(output.getvalue())
    assert valid is not None
    assert valid[1] == ".png"
    assert importer_module._validated_audio_cover(b"not-an-image") is None
    assert importer_module._validated_audio_cover(b"x" * (importer_module.MAX_AUDIO_COVER_BYTES + 1)) is None

    class HugeImage:
        format = "PNG"
        size = (10_000, 10_000)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def verify(self):
            raise AssertionError("pixel bound must be checked before decode")

    monkeypatch.setattr(importer_module.Image, "open", lambda _source: HugeImage())
    assert importer_module._validated_audio_cover(output.getvalue()) is None


def test_audio_bundle_import_merges_with_existing_epub_and_orders_tracks(db_session, test_settings, monkeypatch, tmp_path) -> None:
    _initialize_schema(db_session)
    test_settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
    epub = tmp_path / "[三体][刘慈欣].epub"
    write_epub_metadata_fixture(epub, "三体", "刘慈欣")
    epub_result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=epub, origin="MANUAL", original_name=epub.name),
    )
    audio_result, _audio_dir = _import_audio_fixture(db_session, test_settings, monkeypatch, tmp_path)

    assert audio_result.work_id == epub_result.work_id
    editions = db_session.execute(
        text("SELECT `mediaKind`, `format`, `versionName`, `primary` FROM `LibraryEdition` WHERE `workId` = :work_id ORDER BY `mediaKind`"),
        {"work_id": audio_result.work_id},
    ).mappings().all()
    assert [(row["mediaKind"], row["format"], row["versionName"], row["primary"]) for row in editions] == [
        ("AUDIOBOOK", "AUDIO", "有声书 · 演播者甲", 1),
        ("EBOOK", "EPUB", "EPUB", 1),
    ]
    tracks = db_session.execute(
        text("SELECT `trackNumber`, `sortOrder`, `durationMs`, `codec` FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder`"),
        {"edition_id": audio_result.edition_id},
    ).mappings().all()
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [(2, 0), (10, 1)]
    assert sum(int(row["durationMs"]) for row in tracks) == 1_200_000
    assert {row["codec"] for row in tracks} == {"mp3"}
    task = db_session.execute(
        text("SELECT `taskKind`, `assetCount`, `processedAssetCount`, `status` FROM `ImportTask` WHERE `editionId` = :edition_id"),
        {"edition_id": audio_result.edition_id},
    ).mappings().one()
    assert dict(task) == {"taskKind": "AUDIO_BUNDLE", "assetCount": 2, "processedAssetCount": 2, "status": "COMPLETED"}
    assert db_session.execute(
        text("SELECT COUNT(*) FROM `ImportAsset` WHERE `importTaskId` = (SELECT `id` FROM `ImportTask` WHERE `editionId` = :edition_id) AND `status` = 'COMPLETED'"),
        {"edition_id": audio_result.edition_id},
    ).scalar() == 2


def test_audio_content_dedup_is_lazy_on_first_import_and_reuses_moved_files(
    db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    real_content_hash = importer_module._content_hash
    hashed_paths: list[Path] = []

    def tracked_content_hash(path: Path) -> str:
        hashed_paths.append(path)
        return real_content_hash(path)

    monkeypatch.setattr(importer_module, "_content_hash", tracked_content_hash)
    first, original_dir = _import_audio_fixture(db_session, test_settings, monkeypatch, tmp_path)
    assert hashed_paths == []
    initial_hashes = db_session.execute(
        text("SELECT `fullHash`, `hashStatus` FROM `LibraryFile` WHERE `editionId` = :edition_id"),
        {"edition_id": first.edition_id},
    ).mappings().all()
    assert all(row["fullHash"] is None for row in initial_hashes)
    assert {row["hashStatus"] for row in initial_hashes} == {"PARTIAL_PENDING"}

    moved_dir = test_settings.resolved_monitor_root / "moved-copy"
    moved_dir.mkdir()
    for source in original_dir.iterdir():
        (moved_dir / source.name).write_bytes(source.read_bytes())

    duplicate = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=moved_dir, origin="MANUAL", original_name=moved_dir.name),
    )
    assert duplicate.duplicate is True
    assert duplicate.edition_id == first.edition_id
    assert duplicate.merge_reason == "duplicate-audio-content"
    assert db_session.execute(
        text("SELECT COUNT(*) FROM `LibraryEdition` WHERE `workId` = :work_id AND `mediaKind` = 'AUDIOBOOK'"),
        {"work_id": first.work_id},
    ).scalar() == 1
    assert len(hashed_paths) == 4
    hashes = db_session.execute(
        text("SELECT `fullHash`, `hashStatus` FROM `LibraryFile` WHERE `editionId` = :edition_id"),
        {"edition_id": first.edition_id},
    ).mappings().all()
    assert all(row["fullHash"] and len(row["fullHash"]) == 64 for row in hashes)
    assert {row["hashStatus"] for row in hashes} == {"COMPLETED"}


def test_audio_sample_collision_uses_full_hash_and_does_not_false_deduplicate(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    folder = test_settings.resolved_monitor_root / "sample-collision"
    folder.mkdir(parents=True)
    sample_size = 1024 * 1024
    first_path = folder / "first.mp3"
    second_path = folder / "second.mp3"
    first_path.write_bytes(b"H" * sample_size + b"A" * sample_size + b"T" * sample_size)
    second_path.write_bytes(b"H" * sample_size + b"B" * sample_size + b"T" * sample_size)
    assert importer_module._sample_fingerprint(first_path) == importer_module._sample_fingerprint(second_path)
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _fake_audio_metadata)

    first = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=first_path, origin="MANUAL", requested_title="采样碰撞", requested_author="测试作者"),
    )
    assert db_session.execute(
        text("SELECT `fullHash` FROM `LibraryFile` WHERE `editionId` = :edition_id"),
        {"edition_id": first.edition_id},
    ).scalar() is None

    second = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=second_path, origin="MANUAL", requested_title="采样碰撞", requested_author="测试作者"),
    )
    assert second.duplicate is False
    assert second.work_id == first.work_id
    assert second.edition_id != first.edition_id
    hashes = db_session.execute(
        text(
            "SELECT `fullHash`, `hashStatus` FROM `LibraryFile` "
            "WHERE `editionId` IN (:first_id, :second_id) ORDER BY `editionId`"
        ),
        {"first_id": first.edition_id, "second_id": second.edition_id},
    ).mappings().all()
    assert len({row["fullHash"] for row in hashes}) == 2
    assert {row["hashStatus"] for row in hashes} == {"COMPLETED"}


def test_audio_bundle_keeps_byte_identical_tracks_as_distinct_chapters(db_session, test_settings, monkeypatch) -> None:
    _initialize_schema(db_session)
    folder = test_settings.resolved_monitor_root / "duplicate-tracks"
    folder.mkdir(parents=True)
    payload = b"the-same-track-bytes"
    (folder / "01.mp3").write_bytes(payload)
    (folder / "02.mp3").write_bytes(payload)
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _fake_audio_metadata)

    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=folder, origin="MANUAL", requested_title="重复音轨", requested_author="测试作者"),
    )

    files = db_session.execute(
        text(
            "SELECT `id`, `path`, `fingerprint`, `sortOrder` FROM `LibraryFile` "
            "WHERE `editionId` = :edition_id ORDER BY `sortOrder`"
        ),
        {"edition_id": result.edition_id},
    ).mappings().all()
    chapters = db_session.execute(
        text(
            "SELECT `fileId`, `title`, `sortOrder` FROM `LibraryReadingUnit` "
            "WHERE `editionId` = :edition_id AND `unitType` = 'audio_chapter' ORDER BY `sortOrder`"
        ),
        {"edition_id": result.edition_id},
    ).mappings().all()
    assert len(files) == 2
    assert len({row["id"] for row in files}) == 2
    assert len({row["path"] for row in files}) == 2
    assert len({row["fingerprint"] for row in files}) == 1
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
    assert sum(path.stat().st_size for path in folder.iterdir()) > local_settings.audiobook_max_bundle_bytes
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _fake_audio_metadata)

    result = import_managed_book(
        db_session,
        local_settings,
        ImportOptions(source_file_path=folder, origin="WATCH", requested_title="大型本地有声书"),
    )

    assert db_session.execute(
        text("SELECT COUNT(*) FROM `LibraryFile` WHERE `editionId` = :edition_id"),
        {"edition_id": result.edition_id},
    ).scalar_one() == 2


def test_two_single_file_audio_editions_in_one_folder_have_distinct_version_keys(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    folder = test_settings.resolved_monitor_root / "single-files"
    folder.mkdir(parents=True)
    first_path = folder / "first.mp3"
    second_path = folder / "second.mp3"
    first_path.write_bytes(b"first-distinct-audio")
    second_path.write_bytes(b"second-distinct-audio")
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _fake_audio_metadata)
    first = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=first_path, origin="MANUAL", requested_title="同一本书", requested_author="同一作者"),
    )
    second = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=second_path, origin="MANUAL", requested_title="同一本书", requested_author="同一作者"),
    )
    assert first.work_id == second.work_id
    assert first.edition_id != second.edition_id
    keys = db_session.execute(
        text("SELECT `versionKey` FROM `LibraryEdition` WHERE `workId` = :work_id ORDER BY `id`"),
        {"work_id": first.work_id},
    ).scalars().all()
    assert len(keys) == 2
    assert len(set(keys)) == 2


def test_audio_bootstrap_range_head_and_completion_requires_explicit_ended_signal(
    client, db_session, test_settings, monkeypatch, tmp_path
) -> None:
    _initialize_schema(db_session)
    user = _login(client, db_session)
    result, _audio_dir = _import_audio_fixture(db_session, test_settings, monkeypatch, tmp_path)

    bootstrap_response = client.get(f"/api/reader/v2/editions/{result.edition_id}/bootstrap")
    assert bootstrap_response.status_code == 200
    bootstrap = bootstrap_response.json()["data"]
    assert bootstrap["readerType"] == "audio"
    assert [track["trackNumber"] for track in bootstrap["tracks"]] == [2, 10]
    assert bootstrap["totalDurationMs"] == 1_200_000
    assert len(bootstrap["chapters"]) == 2

    first_track = bootstrap["tracks"][0]
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

    final_track = bootstrap["tracks"][-1]
    common = {
        "schemaVersion": 2,
        "userId": user.id,
        "clientId": "audio-player",
        "contentFingerprint": bootstrap["contentFingerprint"],
        "volumeId": result.volume_id,
        "location": {
            "type": "audio",
            "volumeId": result.volume_id,
            "fileId": final_track["fileId"],
            "chapterId": bootstrap["chapters"][-1]["id"],
            "positionMs": final_track["durationMs"],
        },
    }
    seek = client.put(
        f"/api/reader/v2/editions/{result.edition_id}/progress",
        json={**common, "mutationId": "seek-to-end", "clientSequence": 1, "percent": 99.999},
    )
    assert seek.status_code == 200
    assert seek.json()["data"]["progress"]["percent"] == 99.999
    assert db_session.execute(
        text("SELECT `status` FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id AND `mediaKind` = 'AUDIOBOOK'"),
        {"user_id": user.id, "work_id": result.work_id},
    ).scalar() == "READING"

    ended = client.put(
        f"/api/reader/v2/editions/{result.edition_id}/progress",
        json={**common, "mutationId": "media-ended", "clientSequence": 2, "percent": 100},
    )
    assert ended.status_code == 200
    assert ended.json()["data"]["progress"]["percent"] == 100
    assert db_session.execute(
        text("SELECT `status` FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id AND `mediaKind` = 'AUDIOBOOK'"),
        {"user_id": user.id, "work_id": result.work_id},
    ).scalar() == "FINISHED"

    paused_after_finish = client.put(
        f"/api/reader/v2/editions/{result.edition_id}/progress",
        json={
            **common,
            "mutationId": "pause-after-finish",
            "clientSequence": 3,
            "percent": 10,
            "location": {
                "type": "audio",
                "volumeId": result.volume_id,
                "fileId": first_track["fileId"],
                "chapterId": bootstrap["chapters"][0]["id"],
                "positionMs": 10_000,
            },
        },
    )
    assert paused_after_finish.status_code == 200
    assert db_session.execute(
        text("SELECT `status` FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id AND `mediaKind` = 'AUDIOBOOK'"),
        {"user_id": user.id, "work_id": result.work_id},
    ).scalar() == "FINISHED"


def test_three_media_filters_tabs_preferences_targets_and_user_status_are_isolated(client, db_session) -> None:
    _initialize_schema(db_session)
    user_a = _login(client, db_session, email="listener-a@example.com")
    db_session.execute(
        text(
            "INSERT INTO `LibraryWork` "
            "(`id`, `origin`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`, `workType`, `status`, `tags`, `updatedAt`) "
            "VALUES ('mixed-work', 'MANUAL', '三媒介作品', '三媒介作品', '作者', '作者', 'EPUB', 'UNREAD', '[]', CURRENT_TIMESTAMP)"
        )
    )
    db_session.commit()
    _insert_edition(db_session, edition_id="mixed-ebook", work_id="mixed-work", media_kind="EBOOK", fmt="EPUB")
    _insert_edition(db_session, edition_id="mixed-comic", work_id="mixed-work", media_kind="COMIC", fmt="COMIC")
    _insert_edition(db_session, edition_id="mixed-audio", work_id="mixed-work", media_kind="AUDIOBOOK", fmt="AUDIO")

    for filter_value in ("ebook", "COMIC", "audiobook"):
        response = client.get("/api/works", params={"type": filter_value})
        assert response.status_code == 200
        assert [item["id"] for item in response.json()["data"]["books"]] == ["mixed-work"]

    db_session.execute(
        text(
            "INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) "
            "VALUES ('workDetail.tabOrder', :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (`key`) DO UPDATE SET `value` = excluded.`value`, `updatedAt` = CURRENT_TIMESTAMP"
        ),
        {"value": '["AUDIOBOOK","COMIC","EBOOK","STRUCTURE"]'},
    )
    db_session.commit()
    detail = client.get("/api/works/mixed-work").json()["data"]
    assert [tab["key"] for tab in detail["book"]["detailTabs"]] == ["AUDIOBOOK", "COMIC", "EBOOK", "STRUCTURE"]
    assert detail["book"]["selectedDetailTab"] == "AUDIOBOOK"
    saved = client.put("/api/works/mixed-work/detail-preference", json={"selectedTab": "COMIC"})
    assert saved.status_code == 200
    assert client.get("/api/works/mixed-work").json()["data"]["book"]["selectedDetailTab"] == "COMIC"

    db_session.execute(
        text(
            "INSERT INTO `LibraryWork` (`id`, `origin`, `title`, `normalizedTitle`, `workType`, `status`, `tags`, `updatedAt`) "
            "VALUES ('other-work', 'MANUAL', '其他作品', '其他作品', 'AUDIO', 'UNREAD', '[]', CURRENT_TIMESTAMP)"
        )
    )
    db_session.commit()
    _insert_edition(db_session, edition_id="other-audio", work_id="other-work", media_kind="AUDIOBOOK", fmt="AUDIO")
    invalid = client.patch(
        "/api/works/mixed-work",
        json={"mediaKind": "AUDIOBOOK", "status": "READING", "editionId": "other-audio"},
    )
    assert invalid.status_code == 422
    assert db_session.execute(
        text("SELECT COUNT(*) FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = 'mixed-work'"),
        {"user_id": user_a.id},
    ).scalar() == 0

    started = client.patch(
        "/api/works/mixed-work",
        json={"mediaKind": "AUDIOBOOK", "status": "READING", "editionId": "mixed-audio"},
    )
    assert started.status_code == 200
    assert started.json()["data"]["book"]["statusValue"] == "READING"
    assert [item["id"] for item in client.get("/api/works", params={"status": "READING"}).json()["data"]["books"]] == ["mixed-work"]

    user_b = _login(client, db_session, email="listener-b@example.com")
    user_b_detail = client.get("/api/works/mixed-work").json()["data"]["book"]
    assert user_b_detail["statusValue"] == "UNREAD"
    assert user_b_detail["selectedDetailTab"] == "AUDIOBOOK"
    assert client.get("/api/works", params={"status": "READING"}).json()["data"]["books"] == []
    assert {item["id"] for item in client.get("/api/works", params={"status": "UNREAD"}).json()["data"]["books"]} == {"other-work", "mixed-work"}
    assert db_session.execute(
        text("SELECT COUNT(*) FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = 'mixed-work'"),
        {"user_id": user_b.id},
    ).scalar() == 0

    _login(client, db_session, email="listener-a@example.com")
    for media_kind, edition_id in (("AUDIOBOOK", "mixed-audio"), ("EBOOK", "mixed-ebook")):
        response = client.patch(
            "/api/works/mixed-work",
            json={"mediaKind": media_kind, "status": "FINISHED", "editionId": edition_id},
        )
        assert response.status_code == 200
        assert response.json()["data"]["book"]["statusValue"] == "READING"
        assert client.get("/api/works", params={"status": "FINISHED"}).json()["data"]["books"] == []
    final = client.patch(
        "/api/works/mixed-work",
        json={"mediaKind": "COMIC", "status": "FINISHED", "editionId": "mixed-comic"},
    )
    assert final.status_code == 200
    assert final.json()["data"]["book"]["statusValue"] == "FINISHED"
    assert [item["id"] for item in client.get("/api/works", params={"status": "FINISHED"}).json()["data"]["books"]] == ["mixed-work"]


def test_active_media_and_consumption_hierarchy_follow_the_selected_audio_edition(client, db_session) -> None:
    _initialize_schema(db_session)
    user = _login(client, db_session, email="edition-switch@example.com")
    db_session.execute(
        text(
            "INSERT INTO `LibraryWork` (`id`, `origin`, `title`, `normalizedTitle`, `workType`, `status`, `tags`, `updatedAt`) "
            "VALUES ('switch-work', 'MANUAL', '双演播版', '双演播版', 'AUDIO', 'UNREAD', '[]', CURRENT_TIMESTAMP)"
        )
    )
    db_session.commit()
    _insert_edition(db_session, edition_id="audio-a", work_id="switch-work", media_kind="AUDIOBOOK", fmt="AUDIO")
    _insert_edition(db_session, edition_id="audio-b", work_id="switch-work", media_kind="AUDIOBOOK", fmt="AUDIO", primary=False)
    for suffix in ("a", "b"):
        db_session.execute(
            text(
                "INSERT INTO `LibraryVolume` (`id`, `editionId`, `title`, `sortOrder`, `durationMs`, `updatedAt`) "
                "VALUES (:volume_id, :edition_id, :title, 0, 100000, CURRENT_TIMESTAMP)"
            ),
            {"volume_id": f"volume-{suffix}", "edition_id": f"audio-{suffix}", "title": f"版本 {suffix.upper()}"},
        )
        db_session.execute(
            text(
                "INSERT INTO `LibraryReadingUnit` "
                "(`id`, `editionId`, `volumeId`, `unitType`, `title`, `href`, `sortOrder`, `startMs`, `endMs`, `durationMs`, `metadataJson`, `updatedAt`) "
                "VALUES (:unit_id, :edition_id, :volume_id, 'audio_chapter', :title, :href, 1, 0, 100000, 100000, '{}', CURRENT_TIMESTAMP)"
            ),
            {
                "unit_id": f"unit-{suffix}",
                "edition_id": f"audio-{suffix}",
                "volume_id": f"volume-{suffix}",
                    "title": f"章节 {suffix.upper()}",
                    "href": f"audio:file-{suffix}#t=0,100",
                },
        )
    db_session.commit()

    first = client.patch(
        "/api/works/switch-work",
        json={
            "mediaKind": "AUDIOBOOK",
            "status": "READING",
            "editionId": "audio-a",
            "volumeId": "volume-a",
            "unitId": "unit-a",
        },
    )
    assert first.status_code == 200
    switched = client.patch(
        "/api/works/switch-work",
        json={"mediaKind": "AUDIOBOOK", "status": "FINISHED", "editionId": "audio-b"},
    )
    assert switched.status_code == 200
    state = db_session.execute(
        text(
            "SELECT `lastEditionId`, `lastVolumeId`, `lastUnitId`, `status` FROM `LibraryConsumptionState` "
            "WHERE `userId` = :user_id AND `workId` = 'switch-work' AND `mediaKind` = 'AUDIOBOOK'"
        ),
        {"user_id": user.id},
    ).mappings().one()
    assert dict(state) == {"lastEditionId": "audio-b", "lastVolumeId": None, "lastUnitId": None, "status": "FINISHED"}

    db_session.execute(
        text(
            "INSERT INTO `LibraryReadingProgress` "
                "(`id`, `userId`, `workId`, `editionId`, `volumeId`, `readerType`, `position`, `percent`, `extra`, "
                "`schemaVersion`, `locationType`, `locationJson`, `updatedAt`) "
                "VALUES ('progress-b', :user_id, 'switch-work', 'audio-b', 'volume-b', 'audio', '50000', 80, "
                ":extra, 2, 'audio', :location, "
                "CURRENT_TIMESTAMP)"
            ),
        {
            "user_id": user.id,
            "extra": '{"positionMs":50000}',
            "location": '{"type":"audio","volumeId":"volume-b","fileId":"file-b","chapterId":"unit-b","positionMs":50000}',
        },
    )
    db_session.commit()

    selected_a = client.get(
        "/api/works/switch-work",
        params={"detailTab": "AUDIOBOOK", "editionId": "audio-a"},
    ).json()["data"]["activeMedia"]
    assert selected_a["selectedEditionId"] == "audio-a"
    assert selected_a["progress"] == 0
    assert selected_a["status"] == "FINISHED"
    assert selected_a["progressStatus"] == "UNREAD"
    assert selected_a["positionLabel"] == "未开始"
    assert selected_a["primaryAction"]["label"] == "开始听"
    assert selected_a["primaryAction"]["href"] == "/works/switch-work?detailTab=AUDIOBOOK&editionId=audio-a"

    selected_b = client.get(
        "/api/works/switch-work",
        params={"detailTab": "AUDIOBOOK", "editionId": "audio-b"},
    ).json()["data"]["activeMedia"]
    assert selected_b["selectedEditionId"] == "audio-b"
    assert selected_b["progress"] == 80
    assert selected_b["status"] == "FINISHED"
    assert selected_b["progressStatus"] == "READING"
    assert selected_b["positionLabel"] == "章节 B · 0:50"
    assert selected_b["primaryAction"]["label"] == "继续听"
    assert selected_b["primaryAction"]["href"] == "/works/switch-work?detailTab=AUDIOBOOK&editionId=audio-b"


def test_manual_multi_audio_upload_creates_one_bundle_task_and_assets(client, db_session, test_settings, monkeypatch) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    target = test_settings.resolved_monitor_root / "uploads"
    target.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/works/import",
        data={"targetPath": str(target), "bookTitle": "上传有声书", "bookAuthor": "上传作者"},
        files=[
            ("files", ("01.mp3", b"first-track", "audio/mpeg")),
            ("files", ("02.mp3", b"second-track", "audio/mpeg")),
        ],
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["queued"] == 1
    assert data["saved"] == 2
    assert data["taskKind"] == "AUDIO_BUNDLE"
    assert data["assetCount"] == 2
    task_id = data["tasks"][0]["id"]
    task = db_session.execute(text("SELECT * FROM `ImportTask` WHERE `id` = :task_id"), {"task_id": task_id}).mappings().one()
    assert task["requestedTitle"] == "上传有声书"
    assert task["requestedAuthor"] == "上传作者"
    assets = db_session.execute(
        text("SELECT `sourcePath`, `status`, `sortOrder` FROM `ImportAsset` WHERE `importTaskId` = :task_id ORDER BY `sortOrder`"),
        {"task_id": task_id},
    ).mappings().all()
    assert [row["sortOrder"] for row in assets] == [0, 1]
    assert {row["status"] for row in assets} == {"PENDING"}
    assert all(Path(row["sourcePath"]).parent.name.startswith("上传有声书-有声书") for row in assets)

    monkeypatch.setattr(importer_module, "parse_audio_metadata", _fake_audio_metadata)
    imported = process_import_task(db_session, test_settings, dict(task))
    work = db_session.execute(
        text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :work_id"),
        {"work_id": imported.work_id},
    ).mappings().one()
    assert dict(work) == {"title": "上传有声书", "author": "上传作者"}
    assert not any(".part" in path.name for path in target.iterdir())


def test_manual_multi_audio_upload_keeps_aggregate_byte_limit(client, db_session, test_settings) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    target = test_settings.resolved_monitor_root / "limited-upload"
    target.mkdir(parents=True, exist_ok=True)
    test_settings.audiobook_max_file_bytes = 1024
    test_settings.audiobook_max_bundle_bytes = 20

    response = client.post(
        "/api/works/import",
        data={"targetPath": str(target), "bookTitle": "超过上传上限"},
        files=[
            ("files", ("01.mp3", b"first-upload-track", "audio/mpeg")),
            ("files", ("02.mp3", b"second-upload-track", "audio/mpeg")),
        ],
    )

    assert response.status_code == 400
    assert "有声书文件总量超过上限 20 bytes" in response.json()["error"]["message"]
    assert list(target.iterdir()) == []
    assert db_session.execute(text("SELECT COUNT(*) FROM `ImportTask`")).scalar_one() == 0


def test_failed_audio_upload_removes_staging_files_and_never_queues(client, db_session, test_settings, monkeypatch) -> None:
    _initialize_schema(db_session)
    _login(client, db_session)
    target = test_settings.resolved_monitor_root / "failed-upload"
    target.mkdir(parents=True, exist_ok=True)

    def fail_after_partial_write(_source, staged_target: Path, max_bytes=None):
        staged_target.write_bytes(b"partial")
        raise OSError("simulated interrupted copy")

    monkeypatch.setattr(compat_module, "_copy_upload_stream", fail_after_partial_write)
    response = client.post(
        "/api/works/import",
        data={"targetPath": str(target), "bookTitle": "不能落盘"},
        files=[
            ("files", ("01.mp3", b"first-track", "audio/mpeg")),
            ("files", ("02.mp3", b"second-track", "audio/mpeg")),
        ],
    )
    assert response.status_code == 500
    assert list(target.iterdir()) == []
    assert db_session.execute(text("SELECT COUNT(*) FROM `ImportTask`")).scalar() == 0


def test_failed_audio_bundle_can_be_retried_and_resets_all_assets(client, db_session, test_settings) -> None:
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
        {"id": task["id"]},
    )
    db_session.execute(
        text(
            "UPDATE `ImportAsset` SET `status` = 'FAILED', `errorCode` = 'AUDIO_IMPORT_FAILED', "
            "`errorSummary` = 'bad tags' WHERE `importTaskId` = :id"
        ),
        {"id": task["id"]},
    )
    db_session.commit()

    response = client.post(f"/api/import-tasks/{task['id']}/retry")
    assert response.status_code == 200
    reset_task = db_session.execute(
        text(
            "SELECT `status`, `retryable`, `progress`, `processedAssetCount`, `errorCode`, `errorSummary` "
            "FROM `ImportTask` WHERE `id` = :id"
        ),
        {"id": task["id"]},
    ).mappings().one()
    assert dict(reset_task) == {
        "status": "PENDING",
        "retryable": 0,
        "progress": 0,
        "processedAssetCount": 0,
        "errorCode": None,
        "errorSummary": None,
    }
    assets = db_session.execute(
        text("SELECT `status`, `fileId`, `errorCode`, `errorSummary` FROM `ImportAsset` WHERE `importTaskId` = :id"),
        {"id": task["id"]},
    ).mappings().all()
    assert len(assets) == 2
    assert all(dict(row) == {"status": "PENDING", "fileId": None, "errorCode": None, "errorSummary": None} for row in assets)


def test_completed_directory_bundle_can_enqueue_again_after_a_new_episode(
    db_session, test_settings
) -> None:
    _initialize_schema(db_session)
    bundle = test_settings.resolved_monitor_root / "连载有声书"
    bundle.mkdir(parents=True)
    (bundle / "《连载有声书》第1集.m4a").write_bytes(b"episode-one")
    first, first_created = enqueue_import_task(db_session, bundle, origin="WATCH", original_name=bundle.name)
    assert first_created is True
    db_session.execute(
        text("UPDATE `ImportTask` SET `status` = 'COMPLETED' WHERE `id` = :id"),
        {"id": first["id"]},
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
    assert second["id"] != first["id"]
    assert second["assetCount"] == 2
    assert db_session.execute(
        text("SELECT COUNT(*) FROM `ImportAsset` WHERE `importTaskId` = :id"),
        {"id": second["id"]},
    ).scalar() == 2


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

    assert audio_metadata_module.audio_bundle_root(tracks[0], test_settings.resolved_monitor_root) == book_dir.resolve()
    assert set(audio_metadata_module.collect_audio_bundle_files(book_dir)) == {
        tracks[0].resolve(),
        tracks[1].resolve(),
        tracks[2].resolve(),
    }
    queue = _RecordingQueue()
    summary = scan_directory_for_imports(
        test_settings.resolved_monitor_root,
        MonitorFolderConfig(id="emby", root_path=str(test_settings.resolved_monitor_root), min_file_size_bytes=0),
        queue,
    )
    assert summary.candidates_found == 1
    assert queue.paths == [book_dir.resolve()]

    monkeypatch.setattr(importer_module, "parse_audio_metadata", _emby_audio_metadata)
    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=book_dir, origin="WATCH", original_name=book_dir.name),
    )

    work = db_session.execute(
        text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
        {"id": result.work_id},
    ).mappings().one()
    assert dict(work) == {"title": "The Left Hand of Darkness", "author": "未知作者"}
    imported_tracks = db_session.execute(
        text(
            "SELECT `discNumber`, `trackNumber`, `sortOrder` FROM `LibraryFile` "
            "WHERE `editionId` = :edition_id ORDER BY `sortOrder`"
        ),
        {"edition_id": result.edition_id},
    ).mappings().all()
    assert [
        (row["discNumber"], row["trackNumber"], row["sortOrder"])
        for row in imported_tracks
    ] == [(1, 1, 0), (1, 2, 1), (2, 1, 2)]
    cover_path = db_session.execute(
        text("SELECT `coverPath` FROM `LibraryEdition` WHERE `id` = :id"),
        {"id": result.edition_id},
    ).scalar_one()
    assert Path(cover_path).suffix == ".png"
    assert Path(cover_path).read_bytes() == cover.getvalue()


def test_multivolume_directory_uses_embedded_identity_and_filters_reader_bootstrap(
    client, db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    user = _login(client, db_session, email="multi-volume-audio@example.com")
    book_dir = test_settings.resolved_monitor_root / "[Ghost Blows Out the Light][Author A]"
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

    monkeypatch.setattr(importer_module, "parse_audio_metadata", _emby_audio_metadata)
    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=book_dir, origin="WATCH", original_name=book_dir.name),
    )

    work = db_session.execute(
        text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
        {"id": result.work_id},
    ).mappings().one()
    assert dict(work) == {"title": "Ghost Blows Out the Light", "author": "Author A"}
    volumes = db_session.execute(
        text(
            "SELECT `id`, `title`, `volumeIndex`, `sortOrder`, `chapterCount` "
            "FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder`"
        ),
        {"edition_id": result.edition_id},
    ).mappings().all()
    assert [(row["title"], row["volumeIndex"], row["sortOrder"], row["chapterCount"]) for row in volumes] == [
        ("Vol.1", 1, 0, 1),
        ("Ghost Blows Out the Light Desert", None, 1, 1),
    ]

    first_bootstrap = client.get(
        f"/api/reader/v2/editions/{result.edition_id}/bootstrap?volume={volumes[0]['id']}"
    )
    second_bootstrap = client.get(
        f"/api/reader/v2/editions/{result.edition_id}/bootstrap?volume={volumes[1]['id']}"
    )
    assert first_bootstrap.status_code == 200
    assert second_bootstrap.status_code == 200
    assert [track["title"] for track in first_bootstrap.json()["data"]["tracks"]] == ["Chapter 1"]
    assert [track["title"] for track in second_bootstrap.json()["data"]["tracks"]] == ["Chapter 2"]

    for index, (volume, percent) in enumerate(zip(volumes, (100, 0), strict=True), start=1):
        db_session.execute(
            text(
                "INSERT INTO `LibraryReadingProgress` "
                "(`id`, `userId`, `workId`, `editionId`, `volumeId`, `readerType`, `position`, `percent`, "
                "`extra`, `schemaVersion`, `locationType`, `locationJson`, `updatedAt`) "
                "VALUES (:id, :user_id, :work_id, :edition_id, :volume_id, 'audio', '0', :percent, "
                "'{}', 2, 'audio', '{}', :updated_at)"
            ),
            {
                "id": f"multi-volume-progress-{index}",
                "user_id": user.id,
                "work_id": result.work_id,
                "edition_id": result.edition_id,
                "volume_id": volume["id"],
                "percent": percent,
                "updated_at": f"2026-07-24T00:00:0{index}+00:00",
            },
        )
    db_session.commit()
    detail = client.get(
        f"/api/works/{result.work_id}",
        params={"detailTab": "AUDIOBOOK", "editionId": result.edition_id},
    ).json()["data"]
    selected_edition = next(item for item in detail["book"]["editions"] if item["id"] == result.edition_id)
    assert selected_edition["progress"] == 50
    assert detail["activeMedia"]["progress"] == 50


def test_audio_directory_structure_rejects_mixed_tracks_and_keeps_unmatched_children_independent(tmp_path) -> None:
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


def test_emby_flat_layout_appends_strictly_named_chapters_to_one_edition(
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
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _emby_audio_metadata)

    results = [
        import_managed_book(
            db_session,
            test_settings,
            ImportOptions(source_file_path=path, origin="WATCH", original_name=path.name),
        )
        for path in paths
    ]

    assert {result.work_id for result in results} == {results[0].work_id}
    assert {result.edition_id for result in results} == {results[0].edition_id}
    work = db_session.execute(
        text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
        {"id": results[0].work_id},
    ).mappings().one()
    assert dict(work) == {"title": "Flat Book", "author": "未知作者"}
    editions = db_session.execute(
        text(
            "SELECT `id`, `trackCount`, `chapterCount` FROM `LibraryEdition` "
            "WHERE `workId` = :work_id AND `hidden` = 0"
        ),
        {"work_id": results[0].work_id},
    ).mappings().all()
    assert [dict(row) for row in editions] == [
        {"id": results[0].edition_id, "trackCount": 3, "chapterCount": 3}
    ]
    tracks = db_session.execute(
        text(
            "SELECT `trackNumber`, `sortOrder` FROM `LibraryFile` "
            "WHERE `editionId` = :edition_id ORDER BY `sortOrder`"
        ),
        {"edition_id": results[0].edition_id},
    ).mappings().all()
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [(1, 0), (2, 1), (10, 2)]
    bootstrap = client.get(f"/api/reader/v2/editions/{results[0].edition_id}/bootstrap")
    assert bootstrap.status_code == 200
    assert [track["trackNumber"] for track in bootstrap.json()["data"]["tracks"]] == [1, 2, 10]

    ordinary = root / "01 - Ordinary Standalone.m4b"
    missing_prefix = root / "Flat Book - Chapter 1.mp3"
    ordinary.write_bytes(b"ordinary")
    missing_prefix.write_bytes(b"missing-prefix")
    assert importer_module._flat_audio_filename_title(ordinary) is None
    assert importer_module._flat_audio_filename_title(missing_prefix) is None


class _RecordingQueue:
    def __init__(self) -> None:
        self.paths: list[Path] = []

    def enqueue(self, path: Path, _folder: MonitorFolderConfig) -> None:
        self.paths.append(path.resolve())


def test_watcher_live_and_rescan_only_bundle_proven_book_directories(tmp_path) -> None:
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
    manager.stable_delay_seconds = 60
    manager.import_queue = _RecordingQueue()
    state = WatchState(observer=None, root_path=root.resolve(), config_signature="test")  # type: ignore[arg-type]
    try:
        manager.schedule_import(book_a, folder, state)
        manager.schedule_import(book_b, folder, state)
        assert set(state.timers) == {book_a, book_b}
        manager.schedule_import(first_track, folder, state)
        manager.schedule_import(second_track, folder, state)
        assert split_book in state.timers
        assert first_track not in state.timers
        assert second_track not in state.timers
    finally:
        for timer in state.timers.values():
            timer.cancel()


def test_directory_first_episode_bundle_imports_as_one_ordered_audiobook(
    db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    book_dir = test_settings.resolved_monitor_root / "我当阴阳先生的那几年（多人有声剧）"
    book_dir.mkdir(parents=True)
    names = [
        "《我当阴阳先生那几年》 第153集.m4a",
        "《我当阴阳先生那几年》第12集.m4a",
        "《我当阴阳先生那几年》第1集.m4a",
    ]
    for index, name in enumerate(names, start=1):
        (book_dir / name).write_bytes((f"episode-{index}-" * index).encode())
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _episode_audio_metadata)

    result = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=book_dir, origin="WATCH", original_name=book_dir.name),
    )

    work = db_session.execute(
        text("SELECT `title`, `author` FROM `LibraryWork` WHERE `id` = :id"),
        {"id": result.work_id},
    ).mappings().one()
    assert work["title"] == book_dir.name
    assert work["author"] == "未知作者"
    editions = db_session.execute(
        text("SELECT `id`, `trackCount`, `chapterCount` FROM `LibraryEdition` WHERE `workId` = :work_id AND `hidden` = 0"),
        {"work_id": result.work_id},
    ).mappings().all()
    assert [dict(row) for row in editions] == [{"id": result.edition_id, "trackCount": 3, "chapterCount": 3}]
    tracks = db_session.execute(
        text("SELECT `trackNumber`, `sortOrder`, `path` FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder`"),
        {"edition_id": result.edition_id},
    ).mappings().all()
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [(1, 0), (12, 1), (153, 2)]
    units = db_session.execute(
        text("SELECT `title`, `sortOrder` FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id ORDER BY `sortOrder`"),
        {"edition_id": result.edition_id},
    ).mappings().all()
    assert [row["sortOrder"] for row in units] == [1, 2, 3]
    assert [row["title"] for row in units] == [Path(name).stem for name in [names[2], names[1], names[0]]]

    added = book_dir / "《我当阴阳先生那几年》第2集.m4a"
    added.write_bytes(b"new-episode-two")
    updated = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=book_dir, origin="WATCH", original_name=book_dir.name),
    )
    assert updated.edition_id == result.edition_id
    updated_tracks = db_session.execute(
        text("SELECT `trackNumber`, `sortOrder` FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder`"),
        {"edition_id": result.edition_id},
    ).mappings().all()
    assert [(row["trackNumber"], row["sortOrder"]) for row in updated_tracks] == [(1, 0), (2, 1), (12, 2), (153, 3)]


def test_rescan_reconciles_tracks_split_across_versions_and_preserves_progress(
    client, db_session, test_settings, monkeypatch
) -> None:
    _initialize_schema(db_session)
    user = _login(client, db_session, email="reconcile-audio@example.com")
    book_dir = test_settings.resolved_monitor_root / "我当阴阳先生的那几年（多人有声剧）"
    book_dir.mkdir(parents=True)
    paths = [book_dir / f"《我当阴阳先生那几年》第{number}集.m4a" for number in [3, 1, 2]]
    for index, path in enumerate(paths, start=1):
        path.write_bytes((f"legacy-episode-{index}-" * index).encode())
    monkeypatch.setattr(importer_module, "parse_audio_metadata", _episode_audio_metadata)

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
    failed_bundle_task, failed_bundle_created = enqueue_import_task(
        db_session,
        book_dir,
        origin="WATCH",
        original_name=book_dir.name,
    )
    assert failed_bundle_created is True
    db_session.execute(
        text("UPDATE `ImportTask` SET `status` = 'FAILED' WHERE `id` = :id"),
        {"id": failed_bundle_task["id"]},
    )
    db_session.commit()
    known_paths = watcher_module.load_known_import_paths(db_session)
    assert book_dir.resolve() not in known_paths
    rescan_queue = _RecordingQueue()
    scan_directory_for_imports(
        test_settings.resolved_monitor_root,
        MonitorFolderConfig(id="watch", root_path=str(test_settings.resolved_monitor_root), min_file_size_bytes=0),
        rescan_queue,
        known_paths=known_paths,
    )
    assert book_dir.resolve() in rescan_queue.paths
    legacy_unit_ids = {
        row["id"]
        for row in db_session.execute(
            text("SELECT `id` FROM `LibraryReadingUnit` WHERE `editionId` IN (:first, :second, :third)"),
            {
                "first": legacy_results[0].edition_id,
                "second": legacy_results[1].edition_id,
                "third": legacy_results[2].edition_id,
            },
        ).mappings()
    }
    legacy_resume = db_session.execute(
        text(
            "SELECT file.`id` AS `fileId`, unit.`id` AS `unitId` "
            "FROM `LibraryFile` file JOIN `LibraryReadingUnit` unit ON unit.`fileId` = file.`id` "
            "WHERE file.`editionId` = :edition_id LIMIT 1"
        ),
        {"edition_id": legacy_results[1].edition_id},
    ).mappings().one()
    legacy_location = {
        "type": "audio",
        "volumeId": legacy_results[1].volume_id,
        "fileId": legacy_resume["fileId"],
        "chapterId": legacy_resume["unitId"],
        "positionMs": 12_345,
    }
    db_session.execute(
        text(
            "INSERT INTO `LibraryReadingProgress` "
            "(`id`, `userId`, `workId`, `editionId`, `volumeId`, `readerType`, `position`, `percent`, `extra`, "
            "`contentFingerprint`, `locationType`, `locationJson`, `createdAt`, `updatedAt`) "
            "VALUES ('legacy-progress', :user_id, :work_id, :edition_id, :volume_id, 'audio', '12345', 42, :extra, "
            "'sha256:legacy-single-track', 'audio', :location, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "user_id": user.id,
            "work_id": legacy_results[1].work_id,
            "edition_id": legacy_results[1].edition_id,
            "volume_id": legacy_results[1].volume_id,
            "extra": json.dumps({key: value for key, value in legacy_location.items() if key != "type"}),
            "location": json.dumps(legacy_location),
        },
    )
    db_session.commit()

    reconciled = import_managed_book(
        db_session,
        test_settings,
        ImportOptions(source_file_path=book_dir, origin="WATCH", original_name=book_dir.name),
    )

    visible_works = db_session.execute(
        text("SELECT `id`, `title` FROM `LibraryWork` WHERE `hidden` = 0 AND `workType` = 'AUDIO'"),
    ).mappings().all()
    assert [dict(row) for row in visible_works] == [{"id": reconciled.work_id, "title": book_dir.name}]
    visible_editions = db_session.execute(
        text("SELECT `id`, `trackCount`, `chapterCount` FROM `LibraryEdition` WHERE `hidden` = 0 AND `mediaKind` = 'AUDIOBOOK'"),
    ).mappings().all()
    assert [dict(row) for row in visible_editions] == [{"id": reconciled.edition_id, "trackCount": 3, "chapterCount": 3}]
    tracks = db_session.execute(
        text("SELECT `editionId`, `trackNumber`, `sortOrder` FROM `LibraryFile` WHERE UPPER(`kind`) = 'AUDIO' ORDER BY `sortOrder`"),
    ).mappings().all()
    assert {(row["editionId"]) for row in tracks} == {reconciled.edition_id}
    assert [(row["trackNumber"], row["sortOrder"]) for row in tracks] == [(1, 0), (2, 1), (3, 2)]
    assert {
        row["id"]
        for row in db_session.execute(
            text("SELECT `id` FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id"),
            {"edition_id": reconciled.edition_id},
        ).mappings()
    } == legacy_unit_ids
    progress = db_session.execute(
        text("SELECT `workId`, `editionId`, `volumeId`, `percent`, `position`, `contentFingerprint`, `locationJson` FROM `LibraryReadingProgress` WHERE `id` = 'legacy-progress'"),
    ).mappings().one()
    assert progress["workId"] == reconciled.work_id
    assert progress["editionId"] == reconciled.edition_id
    assert progress["volumeId"] == reconciled.volume_id
    assert progress["position"] == "12345"
    assert progress["percent"] == pytest.approx(12_345 / (60_001 + 60_002 + 60_003) * 100)
    assert progress["contentFingerprint"].startswith("sha256:")
    assert progress["contentFingerprint"] != "sha256:legacy-single-track"
    assert json.loads(progress["locationJson"])["volumeId"] == reconciled.volume_id
    detail = client.get(f"/api/works/{reconciled.work_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["book"]["versionCount"] == 1
    bootstrap = client.get(f"/api/reader/v2/editions/{reconciled.edition_id}/bootstrap")
    assert bootstrap.status_code == 200
    bootstrap_data = bootstrap.json()["data"]
    assert [track["trackNumber"] for track in bootstrap_data["tracks"]] == [1, 2, 3]
    assert bootstrap_data["resumeFingerprintMismatch"] is False
    assert bootstrap_data["resumeLocation"] == legacy_location | {"volumeId": reconciled.volume_id}
