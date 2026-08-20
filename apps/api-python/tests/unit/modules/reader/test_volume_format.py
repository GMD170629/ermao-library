import pytest

from app.modules.reader.domain.volume_format import (
    ReaderType,
    reader_type_for_volume_format,
)


@pytest.mark.parametrize("volume_format", ["EPUB", "MOBI", "AZW", "AZW3", "PRC", "TXT"])
def test_all_native_reflowable_formats_are_directly_readable(
    volume_format: str,
) -> None:
    assert reader_type_for_volume_format(volume_format) == ReaderType.REFLOWABLE


@pytest.mark.parametrize(
    ("volume_format", "reader_type"),
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
    volume_format: str,
    reader_type: ReaderType,
) -> None:
    assert reader_type_for_volume_format(volume_format) == reader_type


@pytest.mark.parametrize("volume_format", ["FB2", "COMIC"])
def test_formats_without_a_p2_native_adapter_are_not_advertised(
    volume_format: str,
) -> None:
    assert reader_type_for_volume_format(volume_format) is None
