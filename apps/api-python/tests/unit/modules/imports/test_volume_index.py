from app.modules.imports.domain.volume_index import parse_structured_volume_index


def test_structured_volume_index_accepts_supported_comic_and_audio_forms() -> None:
    assert parse_structured_volume_index("1") == 1
    assert parse_structured_volume_index("2.5") == 2.5
    assert parse_structured_volume_index("1 of 23") == 1
    assert parse_structured_volume_index("1/23") == 1
    assert parse_structured_volume_index("第 3 卷") == 3
    assert parse_structured_volume_index("Vol. 4") == 4


def test_structured_volume_index_rejects_total_count_and_ambiguous_text() -> None:
    assert parse_structured_volume_index("共23卷") is None
    assert parse_structured_volume_index("23 volumes") is None
    assert parse_structured_volume_index("第一卷") is None
    assert parse_structured_volume_index("chapter 3") is None
    assert parse_structured_volume_index("nan") is None
