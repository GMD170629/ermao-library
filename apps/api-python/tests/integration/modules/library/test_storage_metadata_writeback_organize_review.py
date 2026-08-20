from __future__ import annotations

from pathlib import Path

import pytest

from app.models.library import (
    LibraryFile,
    LibraryReadingUnit,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.domain.version_identity import IMPLICIT_VERSION_SOURCE_KEY
from app.modules.library.infrastructure.storage import collect_storage_values
from app.modules.metadata.infrastructure.writeback_queue import (
    load_metadata_writeback_projection,
)
from app.modules.organize.infrastructure.eligibility import (
    first_version_selection_for_work,
)
from app.modules.organize.infrastructure.review import (
    earliest_volume_id,
    list_volumes_for_work,
)

API_ROOT = Path(__file__).resolve().parents[4]
READ_PATH_SOURCES = (
    API_ROOT / "app/modules/library/infrastructure/storage.py",
    API_ROOT / "app/modules/metadata/infrastructure/writeback_queue.py",
    API_ROOT / "app/modules/organize/infrastructure/eligibility.py",
    API_ROOT / "app/modules/organize/infrastructure/review.py",
)
FORBIDDEN_BINDINGS = (
    "LibraryMediaVersion",
)


def _add_work(db_session, *, work_id: str = "work-1") -> LibraryWork:
    work = LibraryWork(
        library_id="test-library",
        id=work_id,
        title="Binding work",
        normalized_title="binding work",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    db_session.add(work)
    db_session.flush()
    return work


def _add_version(
    db_session,
    *,
    work_id: str,
    version_id: str = "version-default",
    source_key: str = IMPLICIT_VERSION_SOURCE_KEY,
    source_name: str | None = None,
) -> LibraryVersion:
    version = LibraryVersion(
        id=version_id,
        work_id=work_id,
        source_key=source_key,
        source_name=source_name,
    )
    db_session.add(version)
    db_session.flush()
    return version


def _add_volume(
    db_session,
    *,
    version_id: str,
    volume_id: str,
    title: str,
    fmt: str,
    sort_order: int = 0,
) -> LibraryVolume:
    volume = LibraryVolume(
        id=volume_id,
        version_id=version_id,
        title=title,
        sort_order=sort_order,
        format=fmt,
        resource_key=f"resource:{volume_id}",
        import_status="READY",
    )
    db_session.add(volume)
    db_session.flush()
    return volume


def _add_file(db_session, *, volume_id: str, file_id: str) -> LibraryFile:
    file = LibraryFile(
        id=file_id,
        volume_id=volume_id,
        path=f"/library/{file_id}.bin",
        kind="BOOK",
        mime_type="application/octet-stream",
        size_bytes=12,
        sort_order=0,
    )
    db_session.add(file)
    db_session.flush()
    return file


def _seed_mismatched_ebook_work(db_session) -> None:
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-default")
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="volume-1",
        title="第一卷",
        fmt="EPUB",
    )
    _add_file(db_session, volume_id="volume-1", file_id="file-1")
    db_session.add(
        LibraryReadingUnit(
            id="unit-1",
            volume_id="volume-1",
            unit_type="chapter",
            title="Chapter 1",
            href="chapter-1",
            sort_order=0,
            metadata_json="{}",
        )
    )
    db_session.commit()


def test_storage_collects_complete_graph_when_version_ids_differ(db_session) -> None:
    _seed_mismatched_ebook_work(db_session)

    work_cover, volumes, files = collect_storage_values(db_session, "work-1")

    assert work_cover is None
    assert [row["id"] for row in volumes] == ["volume-1"]
    assert [row["versionId"] for row in volumes] == ["version-default"]
    assert [row["id"] for row in files] == ["file-1"]
    assert db_session.get(LibraryVersion, "version-default") is not None
    assert db_session.get(LibraryReadingUnit, "unit-1") is not None
    assert db_session.get(LibraryReadingUnit, "unit-1").volume_id == "volume-1"


def test_metadata_writeback_projection_uses_directory_version_id(
    db_session,
) -> None:
    _seed_mismatched_ebook_work(db_session)

    projection = load_metadata_writeback_projection(db_session, work_id="work-1")

    assert projection.version_ids == ("version-default",)
    assert len(projection.volumes) == 1
    assert projection.volumes[0].version_id == "version-default"
    assert projection.volumes[0].id == "volume-1"


def test_explicit_version_id_selects_only_that_directory_version(db_session) -> None:
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-ebook")
    _add_version(
        db_session,
        work_id=work.id,
        version_id="version-audiobook",
        source_key="audio-source",
    )
    _add_volume(
        db_session,
        version_id="version-ebook",
        volume_id="ebook-volume",
        title="电子书",
        fmt="EPUB",
        sort_order=1,
    )
    _add_volume(
        db_session,
        version_id="version-audiobook",
        volume_id="audio-volume",
        title="有声书",
        fmt="MP3",
        sort_order=0,
    )
    db_session.commit()

    projection = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        version_id="version-audiobook",
    )

    assert projection.version_ids == ("version-audiobook",)
    assert [volume.id for volume in projection.volumes] == ["audio-volume"]
    assert projection.volumes[0].version_id == "version-audiobook"


def test_explicit_volume_id_belongs_to_work_through_library_version(
    db_session,
) -> None:
    work = _add_work(db_session)
    other = _add_work(db_session, work_id="work-2")
    _add_version(db_session, work_id=work.id, version_id="version-default")
    _add_version(
        db_session,
        work_id=other.id,
        version_id="version-other",
        source_key="other-source",
    )
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="owned-volume",
        title="本作品",
        fmt="EPUB",
    )
    _add_volume(
        db_session,
        version_id="version-other",
        volume_id="foreign-volume",
        title="其他作品",
        fmt="EPUB",
    )
    db_session.commit()

    owned = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        volume_id="owned-volume",
    )
    assert [volume.id for volume in owned.volumes] == ["owned-volume"]
    assert owned.volumes[0].version_id == "version-default"

    foreign = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        volume_id="foreign-volume",
    )
    assert foreign.volumes == ()

    with pytest.raises(ValueError, match="版本不存在"):
        load_metadata_writeback_projection(
            db_session,
            work_id="work-1",
            version_id="version-other",
        )


def test_writeback_needs_only_directory_version_and_volume(
    db_session,
) -> None:
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-default")
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="volume-1",
        title="无媒介行",
        fmt="EPUB",
    )
    db_session.commit()

    projection = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        volume_id="volume-1",
    )

    assert projection.version_ids == ("version-default",)
    assert [volume.id for volume in projection.volumes] == ["volume-1"]


def test_eligibility_returns_directory_version_and_volume_when_ids_differ(
    db_session,
) -> None:
    _seed_mismatched_ebook_work(db_session)

    selection = first_version_selection_for_work(db_session, "work-1")

    assert selection == ("version-default", "EBOOK", "volume-1")


def test_review_lists_all_volumes_without_id_alignment(db_session) -> None:
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-default")
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="volume-b",
        title="后卷",
        fmt="EPUB",
        sort_order=2,
    )
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="volume-a",
        title="前卷",
        fmt="PDF",
        sort_order=1,
    )
    db_session.commit()

    assert earliest_volume_id(db_session, "work-1") == "volume-a"
    assert [volume["id"] for volume in list_volumes_for_work(db_session, "work-1")] == [
        "volume-a",
        "volume-b",
    ]


def test_review_orders_volumes_by_stable_version_then_volume_keys(
    db_session,
) -> None:
    work = _add_work(db_session)
    _add_version(
        db_session,
        work_id=work.id,
        version_id="version-named",
        source_key="named-source",
        source_name="Alpha",
    )
    _add_version(
        db_session,
        work_id=work.id,
        version_id="version-default",
        source_key=IMPLICIT_VERSION_SOURCE_KEY,
    )
    _add_version(
        db_session,
        work_id=work.id,
        version_id="version-zeta",
        source_key="zeta-source",
        source_name="Zulu",
    )
    _add_volume(
        db_session,
        version_id="version-zeta",
        volume_id="zeta-volume",
        title="Zulu",
        fmt="EPUB",
        sort_order=0,
    )
    _add_volume(
        db_session,
        version_id="version-named",
        volume_id="named-volume",
        title="Alpha",
        fmt="EPUB",
        sort_order=0,
    )
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="implicit-late",
        title="隐式后",
        fmt="EPUB",
        sort_order=8,
    )
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="implicit-early",
        title="隐式前",
        fmt="EPUB",
        sort_order=1,
    )
    db_session.commit()

    assert [volume["id"] for volume in list_volumes_for_work(db_session, "work-1")] == [
        "implicit-early",
        "implicit-late",
        "named-volume",
        "zeta-volume",
    ]
    assert earliest_volume_id(db_session, "work-1") == "implicit-early"


def test_read_paths_do_not_use_legacy_media_versions() -> None:
    for source_path in READ_PATH_SOURCES:
        source = source_path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_BINDINGS:
            assert fragment not in source, f"{fragment} found in {source_path}"
