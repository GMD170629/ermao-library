from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
    EnsurePublicationNavigationOutcome,
)
from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationFingerprint,
    PublicationLink,
    PublicationTocEntry,
    PublicationUnsupportedError,
)
from app.modules.publications.domain.navigation import (
    CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION,
    PublicationParserProfile,
)
from app.modules.publications.infrastructure.models import PublicationNavigationCache
from app.modules.publications.infrastructure.navigation_cache import (
    ConfiguredPublicationParserProfiles,
)
from app.modules.publications.infrastructure.uow import (
    SqlAlchemyPublicationNavigationLookupUnitOfWork,
    SqlAlchemyPublicationNavigationUnitOfWork,
)


def _seed_volume(
    db_session: Session, source_path: Path
) -> tuple[LibraryVolume, LibraryFile]:
    work = LibraryWork(
        id="navigation-work",
        origin="MANUAL",
        title="Publication Navigation",
        normalized_title="publication navigation",
        author="作者",
        normalized_author="作者",
        tags="[]",
    )
    media = LibraryMediaVersion(
        id="navigation-media",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volume = LibraryVolume(
        id="navigation-volume",
        media_version_id=media.id,
        title="卷册",
        sort_order=0,
        format="EPUB",
        resource_key="manual:navigation",
        import_status="COMPLETED",
        chapter_count=9,
    )
    source = LibraryFile(
        id="navigation-file",
        volume_id=volume.id,
        path=str(source_path),
        fingerprint="fingerprint",
        full_hash="a" * 64,
        hash_status="COMPLETED",
        mtime_ms=1,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=1,
        sort_order=0,
    )
    db_session.add_all([work, media, volume, source])
    db_session.commit()
    return volume, source


def _publication(
    *,
    toc: tuple[PublicationTocEntry, ...],
    original_file_hash: str = "a" * 64,
) -> NormalizedPublication:
    return NormalizedPublication(
        identifier="urn:test:publication-navigation",
        title="卷册",
        author="作者",
        language="zh-CN",
        reading_progression="ltr",
        fingerprint=PublicationFingerprint(
            original_file_hash=f"sha256:{original_file_hash}",
            parser="epub-package:test",
            normalization="epub-normalization:test",
        ),
        reading_order=(
            PublicationLink("Text/one.xhtml", "application/xhtml+xml"),
            PublicationLink("Text/two.xhtml", "application/xhtml+xml"),
        ),
        resources=(),
        toc=toc,
    )


class _Adapter:
    def __init__(self, publication: NormalizedPublication) -> None:
        self.publication = publication
        self.open_count = 0
        self.raise_corrupt = False

    def open(self, source: PublicationSource) -> NormalizedPublication:
        self.open_count += 1
        if self.raise_corrupt:
            raise PublicationCorruptError("broken")
        return self.publication

    def read_resource(self, source: PublicationSource, href: str):
        raise AssertionError("navigation generation must not read a resource")


def _ensure(
    db_session: Session,
    adapter: _Adapter,
) -> EnsurePublicationNavigation:
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    profile = PublicationParserProfile(
        parser=adapter.publication.fingerprint.parser,
        normalization=adapter.publication.fingerprint.normalization,
    )
    return EnsurePublicationNavigation(
        lookup_unit_of_work_factory=lambda: (
            SqlAlchemyPublicationNavigationLookupUnitOfWork(factory)
        ),
        publication_adapter=adapter,
        profile_resolver=ConfiguredPublicationParserProfiles({"epub": profile}),
        unit_of_work_factory=lambda: SqlAlchemyPublicationNavigationUnitOfWork(factory),
    )


_ADMIN = PublicationAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    monitor_folder_ids=(),
)


def test_first_access_replaces_legacy_chapters_and_second_access_hits_cache(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, source = _seed_volume(db_session, tmp_path / "book.epub")
    db_session.add_all(
        [
            LibraryReadingUnit(
                id="legacy-chapter",
                volume_id=volume.id,
                file_id=source.id,
                unit_type="chapter",
                title="旧目录",
                href="old.xhtml",
                sort_order=4,
                metadata_json="{}",
            ),
            LibraryReadingUnit(
                id="preserved-page",
                volume_id=volume.id,
                file_id=source.id,
                unit_type="page",
                title="Page 1",
                href="page-1",
                sort_order=0,
                metadata_json="{}",
            ),
        ]
    )
    db_session.commit()
    adapter = _Adapter(
        _publication(
            toc=(
                PublicationTocEntry(
                    href="Text/one.xhtml#one",
                    title="第一部",
                    children=(
                        PublicationTocEntry(
                            href="Text/two.xhtml#two",
                            title="第二章",
                        ),
                    ),
                ),
            )
        )
    )
    ensure = _ensure(db_session, adapter)

    first = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)
    second = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)

    assert first.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert second.outcome == EnsurePublicationNavigationOutcome.CACHED
    assert adapter.open_count == 1
    db_session.expire_all()
    chapters = db_session.scalars(
        select(LibraryReadingUnit)
        .where(LibraryReadingUnit.unit_type == "chapter")
        .order_by(LibraryReadingUnit.sort_order)
    ).all()
    assert [chapter.title for chapter in chapters] == ["第一部", "第二章"]
    assert [chapter.sort_order for chapter in chapters] == [0, 1]
    assert db_session.get(LibraryReadingUnit, "legacy-chapter") is None
    assert db_session.get(LibraryReadingUnit, "preserved-page") is not None
    metadata = [json.loads(chapter.metadata_json) for chapter in chapters]
    assert [item["level"] for item in metadata] == [0, 1]
    assert [item["path"] for item in metadata] == [[0], [0, 0]]
    assert [item["readingOrderPosition"] for item in metadata] == [1, 2]
    assert all(item["exactNavigation"] is True for item in metadata)
    assert all(item["hrefBase"] == "publication-root" for item in metadata)
    assert all(
        item["navigationKey"] == chapter.id for item, chapter in zip(metadata, chapters)
    )
    cache = db_session.get(PublicationNavigationCache, volume.id)
    assert cache is not None
    assert cache.file_id == source.id
    assert cache.original_file_hash == "sha256:" + "a" * 64
    assert cache.chapter_count == 2
    assert cache.projection_version == CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
    assert db_session.get(LibraryVolume, volume.id).chapter_count == 2


def test_stale_projection_version_regenerates_without_a_source_change(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, _source = _seed_volume(db_session, tmp_path / "projection.epub")
    adapter = _Adapter(
        _publication(toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),))
    )
    ensure = _ensure(db_session, adapter)
    ensure.execute(volume_id=volume.id, access_scope=_ADMIN)
    cache = db_session.get(PublicationNavigationCache, volume.id)
    assert cache is not None
    cache.projection_version = CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION - 1
    db_session.commit()

    regenerated = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)

    assert regenerated.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert adapter.open_count == 2
    db_session.expire_all()
    refreshed = db_session.get(PublicationNavigationCache, volume.id)
    assert refreshed is not None
    assert (
        refreshed.projection_version
        == CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
    )


def test_successful_empty_toc_is_cached_without_reparsing(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, _source = _seed_volume(db_session, tmp_path / "empty.epub")
    adapter = _Adapter(_publication(toc=()))
    ensure = _ensure(db_session, adapter)

    first = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)
    second = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)

    assert first.chapter_count == 0
    assert second.outcome == EnsurePublicationNavigationOutcome.CACHED
    assert second.chapter_count == 0
    assert adapter.open_count == 1
    db_session.expire_all()
    assert db_session.get(PublicationNavigationCache, volume.id).chapter_count == 0
    assert db_session.get(LibraryVolume, volume.id).chapter_count == 0


def test_open_and_ensure_reuses_its_single_parse_on_miss_and_hit(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, _source = _seed_volume(db_session, tmp_path / "manifest.epub")
    publication = _publication(
        toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),)
    )
    adapter = _Adapter(publication)
    ensure = _ensure(db_session, adapter)

    generated = ensure.open_and_ensure(volume_id=volume.id, access_scope=_ADMIN)
    cached = ensure.open_and_ensure(volume_id=volume.id, access_scope=_ADMIN)

    assert generated.publication is publication
    assert generated.navigation.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert cached.publication is publication
    assert cached.navigation.outcome == EnsurePublicationNavigationOutcome.CACHED
    assert adapter.open_count == 2


def test_cache_mismatch_is_invalidated_before_parse_failure(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, source = _seed_volume(db_session, tmp_path / "broken.epub")
    db_session.add(
        LibraryReadingUnit(
            id="stale-chapter",
            volume_id=volume.id,
            file_id=source.id,
            unit_type="chapter",
            title="过期章节",
            href="stale.xhtml",
            sort_order=0,
            metadata_json="{}",
        )
    )
    db_session.commit()
    adapter = _Adapter(_publication(toc=()))
    adapter.raise_corrupt = True

    with pytest.raises(PublicationCorruptError):
        _ensure(db_session, adapter).execute(volume_id=volume.id, access_scope=_ADMIN)

    db_session.expire_all()
    assert db_session.get(LibraryReadingUnit, "stale-chapter") is None
    assert db_session.get(PublicationNavigationCache, volume.id) is None
    assert db_session.get(LibraryVolume, volume.id).chapter_count is None


def test_manifest_parse_failure_invalidates_a_matching_cache_before_reraising(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, _source = _seed_volume(db_session, tmp_path / "later-broken.epub")
    adapter = _Adapter(
        _publication(toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),))
    )
    ensure = _ensure(db_session, adapter)
    ensure.execute(volume_id=volume.id, access_scope=_ADMIN)
    adapter.raise_corrupt = True

    with pytest.raises(PublicationCorruptError):
        ensure.open_and_ensure(volume_id=volume.id, access_scope=_ADMIN)

    db_session.expire_all()
    assert db_session.scalars(select(LibraryReadingUnit)).all() == []
    assert db_session.get(PublicationNavigationCache, volume.id) is None
    assert db_session.get(LibraryVolume, volume.id).chapter_count is None


def test_source_hash_change_during_parse_cannot_publish_stale_projection(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, source = _seed_volume(db_session, tmp_path / "changing.epub")
    publication = _publication(
        toc=(PublicationTocEntry(href="Text/one.xhtml", title="第一章"),)
    )
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    class _ChangingAdapter(_Adapter):
        def open(self, publication_source: PublicationSource) -> NormalizedPublication:
            opened = super().open(publication_source)
            with factory.begin() as mutation:
                current = mutation.get(LibraryFile, source.id)
                assert current is not None
                current.full_hash = "b" * 64
            return opened

    result = _ensure(db_session, _ChangingAdapter(publication)).execute(
        volume_id=volume.id,
        access_scope=_ADMIN,
    )

    assert result.outcome == EnsurePublicationNavigationOutcome.SOURCE_CHANGED
    db_session.expire_all()
    assert db_session.scalars(select(LibraryReadingUnit)).all() == []
    assert db_session.get(PublicationNavigationCache, volume.id) is None
    assert db_session.get(LibraryVolume, volume.id).chapter_count is None


def test_selected_file_change_regenerates_navigation_for_the_new_file(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, _source = _seed_volume(db_session, tmp_path / "first.epub")
    adapter = _Adapter(
        _publication(toc=(PublicationTocEntry(href="Text/one.xhtml", title="旧章"),))
    )
    ensure = _ensure(db_session, adapter)
    first = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)

    replacement_hash = "b" * 64
    replacement = LibraryFile(
        id="replacement-navigation-file",
        volume_id=volume.id,
        path=str(tmp_path / "replacement.epub"),
        fingerprint="replacement-fingerprint",
        full_hash=replacement_hash,
        hash_status="COMPLETED",
        mtime_ms=2,
        kind="EPUB",
        mime_type="application/epub+zip",
        size_bytes=2,
        sort_order=-1,
    )
    db_session.add(replacement)
    db_session.commit()
    adapter.publication = _publication(
        toc=(PublicationTocEntry(href="Text/two.xhtml", title="新章"),),
        original_file_hash=replacement_hash,
    )

    regenerated = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)

    assert first.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert regenerated.outcome == EnsurePublicationNavigationOutcome.GENERATED
    assert adapter.open_count == 2
    db_session.expire_all()
    chapters = db_session.scalars(
        select(LibraryReadingUnit).where(
            LibraryReadingUnit.volume_id == volume.id,
            LibraryReadingUnit.unit_type == "chapter",
        )
    ).all()
    assert [(chapter.title, chapter.file_id) for chapter in chapters] == [
        ("新章", replacement.id)
    ]
    cache = db_session.get(PublicationNavigationCache, volume.id)
    assert cache is not None
    assert cache.file_id == replacement.id
    assert cache.original_file_hash == f"sha256:{replacement_hash}"


def test_unsupported_format_never_invalidates_non_publication_units(
    db_session: Session,
    tmp_path: Path,
) -> None:
    volume, source = _seed_volume(db_session, tmp_path / "comic.cbz")
    volume.format = "CBZ"
    source.kind = "CBZ"
    db_session.add_all(
        [
            LibraryReadingUnit(
                id="comic-chapter-shaped-unit",
                volume_id=volume.id,
                file_id=source.id,
                unit_type="chapter",
                title="Archive metadata",
                href="metadata",
                sort_order=0,
                metadata_json="{}",
            ),
            LibraryReadingUnit(
                id="comic-page",
                volume_id=volume.id,
                file_id=source.id,
                unit_type="page",
                title="Page 1",
                href="page-1",
                sort_order=0,
                metadata_json="{}",
            ),
        ]
    )
    db_session.commit()
    adapter = _Adapter(_publication(toc=()))
    ensure = _ensure(db_session, adapter)

    result = ensure.execute(volume_id=volume.id, access_scope=_ADMIN)

    assert result.outcome == EnsurePublicationNavigationOutcome.UNSUPPORTED
    with pytest.raises(PublicationUnsupportedError):
        ensure.open_and_ensure(volume_id=volume.id, access_scope=_ADMIN)
    assert adapter.open_count == 0
    db_session.expire_all()
    assert db_session.get(LibraryReadingUnit, "comic-chapter-shaped-unit") is not None
    assert db_session.get(LibraryReadingUnit, "comic-page") is not None
    assert db_session.get(LibraryVolume, volume.id).chapter_count == 9
