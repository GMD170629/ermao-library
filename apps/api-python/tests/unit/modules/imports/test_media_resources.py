from app.modules.imports.domain.media_resources import (
    CreateVolumeResource,
    MediaKind,
    VolumeFormat,
    initial_volume_order,
)


def _resource(path: str, index: float | None) -> CreateVolumeResource:
    return CreateVolumeResource(
        media_version_id="media-1",
        source_path=path,
        format=VolumeFormat.EPUB,
        title=path,
        volume_index=index,
    )


def test_every_supported_format_maps_to_exactly_one_media_kind() -> None:
    assert VolumeFormat.PDF.media_kind is MediaKind.EBOOK
    assert VolumeFormat.AZW3.media_kind is MediaKind.EBOOK
    assert VolumeFormat.CBR.media_kind is MediaKind.COMIC
    assert VolumeFormat.CBZ.media_kind is MediaKind.COMIC
    assert VolumeFormat.RAR.media_kind is MediaKind.COMIC
    assert VolumeFormat.MP3.media_kind is MediaKind.AUDIOBOOK


def test_duplicate_and_missing_volume_numbers_are_valid_resources() -> None:
    resources = [
        _resource("book-10.epub", 1),
        _resource("book-2.epub", 1),
        _resource("appendix.epub", None),
    ]

    ordered = initial_volume_order(resources)

    assert [resource.source_path for resource in ordered] == [
        "book-2.epub",
        "book-10.epub",
        "appendix.epub",
    ]
    assert ordered[0].volume_index == ordered[1].volume_index == 1


def test_resource_identity_ignores_descriptive_volume_number() -> None:
    first = _resource("same/book.epub", 1)
    renamed = _resource("same/book.epub", 99)
    other_path = _resource("other/book.epub", 1)

    assert first.resource_key == renamed.resource_key
    assert first.resource_key != other_path.resource_key
