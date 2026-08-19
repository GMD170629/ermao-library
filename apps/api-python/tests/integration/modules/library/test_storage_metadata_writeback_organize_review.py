from __future__ import annotations

from pathlib import Path

import pytest

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
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
    first_media_selection_for_work,
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
    "LibraryMediaVersion.id == LibraryVolume.version_id",
    "LibraryVolume.version_id.in_(media_version_ids)",
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


def _add_media(
    db_session,
    *,
    work_id: str,
    media_id: str,
    media_kind: str,
) -> LibraryMediaVersion:
    media = LibraryMediaVersion(
        id=media_id,
        work_id=work_id,
        media_kind=media_kind,
    )
    db_session.add(media)
    db_session.flush()
    return media


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
    _add_media(
        db_session,
        work_id=work.id,
        media_id="media-ebook",
        media_kind="EBOOK",
    )
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

    work_cover, media_rows, volumes, files = collect_storage_values(
        db_session, "work-1"
    )

    assert work_cover is None
    assert [row["id"] for row in media_rows] == ["media-ebook"]
    assert [row["id"] for row in volumes] == ["volume-1"]
    assert [row["versionId"] for row in volumes] == ["version-default"]
    assert [row["id"] for row in files] == ["file-1"]
    assert db_session.get(LibraryVersion, "version-default") is not None
    assert db_session.get(LibraryReadingUnit, "unit-1") is not None
    assert db_session.get(LibraryReadingUnit, "unit-1").volume_id == "volume-1"


def test_metadata_writeback_projection_uses_real_media_version_id(
    db_session,
) -> None:
    _seed_mismatched_ebook_work(db_session)

    projection = load_metadata_writeback_projection(db_session, work_id="work-1")

    assert projection.media_version_ids == ("media-ebook",)
    assert len(projection.volumes) == 1
    assert projection.volumes[0].media_version_id == "media-ebook"
    assert projection.volumes[0].media_version_id != "version-default"
    assert projection.volumes[0].id == "volume-1"


def test_explicit_media_version_id_selects_volume_by_media_kind(db_session) -> None:
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-default")
    _add_media(db_session, work_id=work.id, media_id="media-ebook", media_kind="EBOOK")
    _add_media(
        db_session,
        work_id=work.id,
        media_id="media-audiobook",
        media_kind="AUDIOBOOK",
    )
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="ebook-volume",
        title="电子书",
        fmt="EPUB",
        sort_order=1,
    )
    _add_volume(
        db_session,
        version_id="version-default",
        volume_id="audio-volume",
        title="有声书",
        fmt="MP3",
        sort_order=0,
    )
    db_session.commit()

    projection = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        media_version_id="media-audiobook",
    )

    assert projection.media_version_ids == ("media-audiobook",)
    assert [volume.id for volume in projection.volumes] == ["audio-volume"]
    assert projection.volumes[0].media_version_id == "media-audiobook"
    assert projection.volumes[0].media_version_id != "version-default"


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
    _add_media(db_session, work_id=work.id, media_id="media-ebook", media_kind="EBOOK")
    _add_media(
        db_session,
        work_id=other.id,
        media_id="media-other",
        media_kind="EBOOK",
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
    assert owned.volumes[0].media_version_id == "media-ebook"
    assert owned.volumes[0].media_version_id != "version-default"

    foreign = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        volume_id="foreign-volume",
    )
    assert foreign.volumes == ()

    with pytest.raises(ValueError, match="媒介版本不存在"):
        load_metadata_writeback_projection(
            db_session,
            work_id="work-1",
            media_version_id="media-other",
        )


def test_writeback_does_not_forge_media_version_id_without_media_row(
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

    assert projection.media_version_ids == ()
    assert projection.volumes == ()


def test_eligibility_returns_real_media_row_and_volume_when_ids_differ(
    db_session,
) -> None:
    _seed_mismatched_ebook_work(db_session)

    selection = first_media_selection_for_work(db_session, "work-1")

    assert selection == ("media-ebook", "EBOOK", "volume-1")
    assert selection[0] != "version-default"


def test_review_lists_all_volumes_without_id_alignment(db_session) -> None:
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-default")
    _add_media(db_session, work_id=work.id, media_id="media-ebook", media_kind="EBOOK")
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


def test_read_paths_do_not_bind_media_version_ids_to_volumes() -> None:
    for source_path in READ_PATH_SOURCES:
        source = source_path.read_text(encoding="utf-8")
        for fragment in FORBIDDEN_BINDINGS:
            assert fragment not in source, f"{fragment} found in {source_path}"


# ---------------------------------------------------------------------------
# Tests A / B / C: version_id structural filter must not be confused with
# media_version_id.  These IDs are intentionally disjoint in every fixture.
# ---------------------------------------------------------------------------


def test_version_id_filter_returns_volumes_under_that_version(db_session) -> None:
    """Test A: version_id (LibraryVersion.id) filters volumes structurally.

    LibraryVersion.id and LibraryMediaVersion.id are completely different.
    Passing version_id must not raise "媒介版本不存在" and must include only
    volumes belonging to that LibraryVersion.
    """
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-a")
    _add_media(db_session, work_id=work.id, media_id="media-ebook", media_kind="EBOOK")
    _add_media(
        db_session, work_id=work.id, media_id="media-comic", media_kind="COMIC"
    )
    _add_volume(
        db_session,
        version_id="version-a",
        volume_id="volume-epub",
        title="EPUB 卷",
        fmt="EPUB",
        sort_order=1,
    )
    _add_volume(
        db_session,
        version_id="version-a",
        volume_id="volume-cbz",
        title="CBZ 卷",
        fmt="CBZ",
        sort_order=2,
    )
    db_session.commit()

    # These IDs must be completely disjoint to prove there is no confusion.
    assert "version-a" not in {"media-ebook", "media-comic"}

    projection = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        version_id="version-a",
    )

    volume_ids = {v.id for v in projection.volumes}
    assert volume_ids == {"volume-epub", "volume-cbz"}
    # media_version_ids must carry real LibraryMediaVersion ids, not version-a
    assert "version-a" not in projection.media_version_ids
    # version_id filter must not have touched LibraryVolume.version_id
    for v in projection.volumes:
        raw = db_session.get(LibraryVolume, v.id)
        assert raw is not None
        assert raw.version_id == "version-a"


def test_version_id_filter_excludes_volumes_in_other_versions(db_session) -> None:
    """Test B: version_id filter is structural — same media kind does not spill over.

    Two versions each with one EPUB volume.  Applying version_id=version-a must
    include only volume-a; volume-b must not appear even though both are EPUB.
    Both volumes must retain their original version_id after the query.
    """
    work = _add_work(db_session)
    _add_version(
        db_session,
        work_id=work.id,
        version_id="version-a",
        source_key="source-a",
        source_name="Source A",
    )
    _add_version(
        db_session,
        work_id=work.id,
        version_id="version-b",
        source_key="source-b",
        source_name="Source B",
    )
    _add_media(db_session, work_id=work.id, media_id="media-ebook", media_kind="EBOOK")
    _add_volume(
        db_session,
        version_id="version-a",
        volume_id="volume-a",
        title="版本 A 的卷",
        fmt="EPUB",
        sort_order=1,
    )
    _add_volume(
        db_session,
        version_id="version-b",
        volume_id="volume-b",
        title="版本 B 的卷",
        fmt="EPUB",
        sort_order=1,
    )
    db_session.commit()

    projection_a = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        version_id="version-a",
    )
    assert [v.id for v in projection_a.volumes] == ["volume-a"]

    # volume-b must not be included despite having the same media kind
    volume_b_ids = {v.id for v in projection_a.volumes}
    assert "volume-b" not in volume_b_ids

    # Both volumes retain their original version_id
    assert db_session.get(LibraryVolume, "volume-a").version_id == "version-a"
    assert db_session.get(LibraryVolume, "volume-b").version_id == "version-b"

    # Symmetric: version-b only sees volume-b
    projection_b = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        version_id="version-b",
    )
    assert [v.id for v in projection_b.volumes] == ["volume-b"]
    assert "volume-a" not in {v.id for v in projection_b.volumes}


def test_version_id_is_not_queried_as_media_version_id(db_session) -> None:
    """Test C: passing version_id must never be used to look up LibraryMediaVersion.

    If the infrastructure mistakenly treats version_id as media_version_id,
    it would raise ValueError("媒介版本不存在") because no LibraryMediaVersion
    row has id == "version-a".  This test ensures the error does not occur.
    """
    work = _add_work(db_session)
    _add_version(db_session, work_id=work.id, version_id="version-a")
    _add_media(db_session, work_id=work.id, media_id="media-ebook", media_kind="EBOOK")
    _add_volume(
        db_session,
        version_id="version-a",
        volume_id="volume-1",
        title="正文卷",
        fmt="EPUB",
        sort_order=1,
    )
    db_session.commit()

    # Confirm no LibraryMediaVersion row has id == "version-a"
    from sqlalchemy import select as sa_select

    bad_row = db_session.scalar(
        sa_select(LibraryMediaVersion).where(LibraryMediaVersion.id == "version-a")
    )
    assert bad_row is None, "fixture error: media row must not have id == version-a"

    # Must not raise "媒介版本不存在"
    projection = load_metadata_writeback_projection(
        db_session,
        work_id="work-1",
        version_id="version-a",
    )

    assert len(projection.volumes) == 1
    assert projection.volumes[0].id == "volume-1"
    # media_version_ids must contain real LibraryMediaVersion ids
    assert set(projection.media_version_ids) == {"media-ebook"}
    assert "version-a" not in projection.media_version_ids
