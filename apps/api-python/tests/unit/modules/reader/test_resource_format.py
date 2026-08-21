import pytest

from app.modules.reader.domain.resource_format import (
    ReaderType,
    reader_type_for_format,
)


@pytest.mark.parametrize("resource_format", ["EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT"])
def test_all_native_reflowable_formats_are_directly_readable(
    resource_format: str,
) -> None:
    assert reader_type_for_format(resource_format) == ReaderType.REFLOWABLE


@pytest.mark.parametrize(
    ("resource_format", "reader_type"),
    [
        ("PDF", ReaderType.PDF),
        ("CBZ", ReaderType.COMIC),
        ("ZIP", ReaderType.COMIC),
        ("CBR", ReaderType.COMIC),
        ("RAR", ReaderType.COMIC),
        ("M4B", ReaderType.AUDIO),
        ("M4A", ReaderType.AUDIO),
        ("MP3", ReaderType.AUDIO),
    ],
)
def test_fixed_layout_and_audio_formats_are_directly_readable(
    resource_format: str,
    reader_type: ReaderType,
) -> None:
    assert reader_type_for_format(resource_format) == reader_type


@pytest.mark.parametrize("resource_format", ["FB2", "COMIC"])
def test_formats_without_a_p2_native_adapter_are_not_advertised(
    resource_format: str,
) -> None:
    assert reader_type_for_format(resource_format) is None
