from __future__ import annotations

from dataclasses import dataclass, replace

from app.modules.library.application.resource_details import (
    ListResourceDetails,
    ResourceAssetDetail,
    ResourceCurrentChapter,
    ResourceDetailAccessScope,
    ResourceDetailItem,
    ResourceDetailResource,
)

SCOPE = ResourceDetailAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    library_ids=(),
)


@dataclass
class FakeQueries:
    resource: ResourceDetailResource
    units: tuple[ResourceDetailItem, ...] = ()
    assets: tuple[ResourceAssetDetail, ...] = ()
    resolved_page_count: int | None = None
    requested_asset_id: str | None = None
    requested_navigation_key: str | None = None
    current_chapter: ResourceCurrentChapter | None = None

    def get_resource(self, **_kwargs: object) -> ResourceDetailResource:
        return self.resource

    def list_navigation_units(
        self,
        *,
        asset_id: str | None,
        limit: int,
        offset: int,
        **_kwargs: object,
    ) -> tuple[tuple[ResourceDetailItem, ...], int]:
        self.requested_asset_id = asset_id
        return self.units[offset : offset + limit], len(self.units)

    def list_assets(self, **_kwargs: object) -> tuple[ResourceAssetDetail, ...]:
        return self.assets

    def count_chapters(self, **_kwargs: object) -> int:
        return sum(bool(unit.href) for unit in self.units)

    def resolve_pdf_page_count(self, **_kwargs: object) -> int | None:
        return self.resolved_page_count

    def resolve_current_chapter(
        self, *, navigation_key: str, **_kwargs: object
    ) -> ResourceCurrentChapter | None:
        self.requested_navigation_key = navigation_key
        return self.current_chapter


@dataclass
class FakeNavigation:
    asset_id: str = "asset-1"
    calls: int = 0

    def ensure(self, **_kwargs: object) -> str:
        self.calls += 1
        return self.asset_id


def details(
    queries: FakeQueries,
    navigation: FakeNavigation | None = None,
) -> ListResourceDetails:
    return ListResourceDetails(queries, navigation or FakeNavigation())


def resource(
    source_format: str, *, page_count: int | None = None
) -> ResourceDetailResource:
    return ResourceDetailResource(
        id="resource-1",
        book_id="book-1",
        format=source_format,
        page_count=page_count,
        progress=25,
        current_href=None,
        current_page_number=None,
        current_position=None,
    )


def asset(
    asset_id: str,
    title: str,
    *,
    role: str,
    track: int | None = None,
) -> ResourceAssetDetail:
    return ResourceAssetDetail(
        id=asset_id,
        role=role,
        title=title,
        media_type="audio/mpeg" if role == "TRACK" else "image/jpeg",
        sort_key=title,
        sort_order=track or 0,
        duration_ms=60_000 if role == "TRACK" else None,
        disc_number=1 if role == "TRACK" else None,
        track_number=track,
    )


def test_reflowable_details_keep_toc_level_and_apply_pagination() -> None:
    units = tuple(
        ResourceDetailItem(
            id=f"chapter-{index}",
            unit_type="chapter",
            title=f"Chapter {index}",
            sort_order=index,
            href=f"chapter-{index}.xhtml",
            level=2,
            navigation_key=f"chapter-{index}",
        )
        for index in range(55)
    )
    queries = FakeQueries(resource("EPUB"), units=units)
    navigation = FakeNavigation()
    query = details(queries, navigation)

    result = query.execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=2, page_size=50
    )

    assert result.total == 55
    assert [unit.id for unit in result.units] == [
        f"chapter-{index}" for index in range(50, 55)
    ]
    assert all(unit.level == 2 for unit in result.units)
    assert navigation.calls == 1
    assert queries.requested_asset_id == "asset-1"


def test_reflowable_details_prepare_missing_server_navigation() -> None:
    navigation = FakeNavigation()
    result = details(FakeQueries(resource("MOBI")), navigation).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=1, page_size=50
    )

    assert result.units == ()
    assert result.total == 0
    assert navigation.calls == 1


def test_current_chapter_uses_shared_key_instead_of_client_index_or_href() -> None:
    queries = FakeQueries(
        replace(
            resource("EPUB"),
            current_chapter_navigation_key="chapter-4",
            current_chapter_index=99,
            current_href="wrong.xhtml",
        ),
        current_chapter=ResourceCurrentChapter(4, "Fourth", 4, "body.xhtml#fourth"),
    )
    result = details(queries).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=1, page_size=50
    )
    assert queries.requested_navigation_key == "chapter-4"
    assert result.current_chapter_sort_order == 4
    assert result.current_chapter_title == "Fourth"


def test_unknown_current_chapter_is_not_guessed_from_client_presentation() -> None:
    queries = FakeQueries(
        replace(resource("EPUB"), current_chapter_index=1, current_href="chapter.xhtml")
    )
    result = details(queries).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=1, page_size=50
    )
    assert queries.requested_navigation_key is None
    assert result.current_chapter_sort_order is None


def test_pdf_details_are_synthesized_without_page_rows() -> None:
    navigation = FakeNavigation()
    result = details(FakeQueries(resource("PDF", page_count=26)), navigation).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=2, page_size=24
    )

    assert result.total == 26
    assert [unit.page_number for unit in result.units] == [25, 26]
    assert result.units[0].preview_url == "/api/resources/resource-1/previews/24"
    assert navigation.calls == 0


def test_pdf_details_resolve_page_count_when_legacy_metadata_is_missing() -> None:
    result = details(FakeQueries(resource("PDF"), resolved_page_count=3)).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=1, page_size=24
    )

    assert result.total == 3
    assert [unit.page_number for unit in result.units] == [1, 2, 3]


def test_directory_pages_use_natural_order_and_audio_uses_imported_order() -> None:
    image_assets = (
        asset("page-10", "page10.jpg", role="PAGE"),
        asset("page-2", "page2.jpg", role="PAGE"),
        asset("page-1", "page1.jpg", role="PAGE"),
    )
    image_result = details(
        FakeQueries(resource("IMAGE_DIR"), assets=image_assets)
    ).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=1, page_size=24
    )
    assert [unit.title for unit in image_result.units] == [
        "page1.jpg",
        "page2.jpg",
        "page10.jpg",
    ]
    assert [unit.page_number for unit in image_result.units] == [1, 2, 3]

    audio_assets = (
        asset("track-10", "Track 10.mp3", role="TRACK", track=1),
        asset("track-2", "Track 2.mp3", role="TRACK", track=99),
    )
    audio_result = details(
        FakeQueries(resource("AUDIOBOOK_DIR"), assets=audio_assets)
    ).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=1, page_size=50
    )
    assert [unit.asset_id for unit in audio_result.units] == ["track-10", "track-2"]
    assert [unit.track_number for unit in audio_result.units] == [1, 99]


def test_audio_details_paginate_imported_sequence_and_preserve_tags() -> None:
    tracks = tuple(
        replace(
            asset(name, name, role="TRACK", track=track_number),
            sort_order=sequence,
        )
        for name, track_number, sequence in (
            ("01-mp3.mp3", 1, 0),
            ("02-aac.aac", 2, 3),
            ("03-m4a.m4a", 1, 1),
            ("04-m4b.m4b", 1, 2),
        )
    )
    queries = FakeQueries(
        resource("AUDIOBOOK_DIR"),
        assets=tracks + (asset("cover", "cover.jpg", role="COVER"),),
    )
    result = details(queries).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=2, page_size=2
    )

    assert result.total == 4
    assert [unit.asset_id for unit in result.units] == ["04-m4b.m4b", "02-aac.aac"]
    assert [unit.sort_order for unit in result.units] == [2, 3]
    assert [unit.track_number for unit in result.units] == [1, 2]


def test_single_audio_primary_asset_stays_a_playable_track() -> None:
    primary = replace(
        asset("single", "book.m4b", role="PRIMARY"), media_type="audio/mp4"
    )
    result = details(FakeQueries(resource("AUDIO"), assets=(primary,))).execute(
        context=SCOPE, book_id="book-1", resource_id="resource-1", page=1, page_size=50
    )

    assert result.total == 1
    assert result.units[0].asset_id == "single"
    assert result.units[0].unit_type == "track"
    assert result.units[0].media_type == "audio/mp4"
