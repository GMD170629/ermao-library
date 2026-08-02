from __future__ import annotations

from app.modules.imports.application.dto import BookIdentityDTO
from app.modules.imports.application.identity_resolution import (
    EmbeddedIdentityMetadata,
    resolve_import_identity,
)


def _path_identity(
    *,
    title: str,
    author: str = "未知作者",
    confidence: float = 0.62,
    volume_index: float | None = None,
    source: str = "regex",
) -> BookIdentityDTO:
    return BookIdentityDTO(
        title=title,
        author=author,
        volume_index=volume_index,
        source=source,
        confidence=confidence,
        logical_path=f"我的书库/{title}.epub",
    )


def test_complete_embedded_metadata_replaces_low_confidence_sanitized_filename() -> (
    None
):
    resolved = resolve_import_identity(
        _path_identity(title="白夜行 (东野圭吾) (z-library.sk 1lib.sk z-lib.sk)"),
        embedded=EmbeddedIdentityMetadata(
            title="白夜行",
            author="(日)东野圭吾",
            source="epub_opf",
            confidence=0.95,
        ),
    )

    assert (resolved.title, resolved.author) == ("白夜行", "(日)东野圭吾")
    assert resolved.source == "epub_opf"
    assert resolved.selection_reason == "embedded_metadata_over_incomplete_path"
    assert [evidence.source for evidence in resolved.evidence] == [
        "regex",
        "epub_opf",
    ]


def test_high_confidence_complete_filename_beats_conflicting_embedded_metadata() -> (
    None
):
    resolved = resolve_import_identity(
        _path_identity(
            title="斯泰尔斯庄园奇案",
            author="阿加莎·克里斯蒂",
            confidence=0.9,
        ),
        embedded=EmbeddedIdentityMetadata(
            title="岛田庄司精选作品合集共14册",
            author="岛田庄司",
            source="epub_opf",
            confidence=0.95,
        ),
    )

    assert (resolved.title, resolved.author) == (
        "斯泰尔斯庄园奇案",
        "阿加莎·克里斯蒂",
    )
    assert resolved.source == "regex"
    assert resolved.selection_reason == "complete_high_confidence_path"


def test_explicit_fields_override_other_sources_field_by_field() -> None:
    resolved = resolve_import_identity(
        _path_identity(title="损坏文件名"),
        embedded=EmbeddedIdentityMetadata(
            title="白夜行",
            author="东野圭吾",
            source="epub_opf",
            confidence=0.95,
        ),
        requested_title="白夜行·典藏版",
    )

    assert (resolved.title, resolved.author) == ("白夜行·典藏版", "东野圭吾")
    assert resolved.source == "requested"
    assert resolved.selection_reason == "explicit_user_fields"


def test_series_volume_identity_is_not_replaced_by_volume_embedded_metadata() -> None:
    resolved = resolve_import_identity(
        _path_identity(
            title="系列作品",
            author="系列作者",
            confidence=0.98,
            volume_index=3,
        ),
        embedded=EmbeddedIdentityMetadata(
            title="第三卷 独立标题",
            author="系列作者",
            source="epub_opf",
            confidence=0.95,
        ),
    )

    assert (resolved.title, resolved.author, resolved.volume_index) == (
        "系列作品",
        "系列作者",
        3,
    )
    assert resolved.selection_reason == "series_volume_path"


def test_series_volume_identity_fills_unknown_author_from_embedded_metadata() -> None:
    resolved = resolve_import_identity(
        _path_identity(
            title="荒島求生記",
            author="未知作者",
            confidence=0.62,
            volume_index=1,
        ),
        embedded=EmbeddedIdentityMetadata(
            title=None,
            author="高桥义广",
            source="pdf_metadata",
            confidence=0.9,
        ),
    )

    assert (resolved.title, resolved.author, resolved.volume_index) == (
        "荒島求生記",
        "高桥义广",
        1,
    )
    assert resolved.source == "pdf_metadata"
    assert resolved.selection_reason == "embedded_author_over_incomplete_path"


def test_placeholder_embedded_metadata_does_not_replace_path_identity() -> None:
    resolved = resolve_import_identity(
        _path_identity(title="活着", author="余华", confidence=0.88),
        embedded=EmbeddedIdentityMetadata(
            title="Unknown",
            author="未知作者",
            source="epub_opf",
            confidence=0.95,
        ),
    )

    assert (resolved.title, resolved.author) == ("活着", "余华")
    assert resolved.source == "regex"
    assert resolved.selection_reason == "path_fallback"
