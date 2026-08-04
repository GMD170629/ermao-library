from pathlib import Path

from app.modules.imports.application.audio_types import AudioFileMetadata
from app.modules.imports.application.dto import BookIdentityDTO
from app.modules.imports.application.import_audio import audio_embedded_metadata


def _identity() -> BookIdentityDTO:
    return BookIdentityDTO(
        title="路径作品",
        author="路径作者",
        volume_index=None,
        source="regex",
        confidence=0.8,
        logical_path="book.mp3",
    )


def _audio(
    *,
    series_name: str | None = "系列作品",
    volume_index: float | None = 2,
    disc_number: int | None = 3,
) -> AudioFileMetadata:
    return AudioFileMetadata(
        path=Path("book.mp3"),
        title="卷册副标题",
        album="专辑标题",
        author="标签作者",
        narrator=None,
        duration_ms=60_000,
        codec="mp3",
        bitrate=128_000,
        sample_rate=44_100,
        channels=2,
        disc_number=disc_number,
        track_number=1,
        series_name=series_name,
        volume_index=volume_index,
    )


def test_audio_embedded_metadata_maps_explicit_series_and_volume_tags() -> None:
    metadata = audio_embedded_metadata(_identity(), [_audio()])

    assert metadata.title == "系列作品"
    assert metadata.volume_title == "卷册副标题"
    assert metadata.series_name == "系列作品"
    assert metadata.series_index == 2
    assert metadata.volume_index == 2


def test_audio_disc_number_is_not_used_as_volume_number() -> None:
    metadata = audio_embedded_metadata(
        _identity(),
        [_audio(series_name=None, volume_index=None, disc_number=3)],
    )

    assert metadata.title == "专辑标题"
    assert metadata.volume_index is None
