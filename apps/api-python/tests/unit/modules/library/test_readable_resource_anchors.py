"""Pure domain coverage for Book/Resource/Asset exact path anchor scopes."""

from __future__ import annotations

import unicodedata

from app.modules.library.domain.readable_resource_anchors import (
    is_asset_path_within_resource_scope,
    is_resource_anchor_within_book_scope,
    is_same_or_descendant_path,
    is_strict_descendant_path,
)
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
)


def _path(raw: str) -> SourceNodeRelativePath:
    return SourceNodeRelativePath(raw)


def test_same_node_is_within_book_and_same_scope() -> None:
    anchor = _path("Series/Book")
    assert is_same_or_descendant_path(ancestor=anchor, candidate=anchor)
    assert is_resource_anchor_within_book_scope(
        book_anchor=anchor,
        book_anchor_kind=SourceNodePhysicalKind.DIRECTORY,
        resource_anchor=anchor,
    )


def test_directory_book_accepts_descendant_resource() -> None:
    book = _path("Series/Book")
    resource = _path("Series/Book/vol1.epub")
    assert is_strict_descendant_path(ancestor=book, candidate=resource)
    assert is_resource_anchor_within_book_scope(
        book_anchor=book,
        book_anchor_kind=SourceNodePhysicalKind.DIRECTORY,
        resource_anchor=resource,
    )


def test_file_book_rejects_sibling_resource() -> None:
    book = _path("novel.epub")
    other = _path("other.epub")
    assert not is_resource_anchor_within_book_scope(
        book_anchor=book,
        book_anchor_kind=SourceNodePhysicalKind.REGULAR_FILE,
        resource_anchor=other,
    )


def test_similar_prefix_is_not_a_descendant() -> None:
    book = _path("book")
    other = _path("book-other/file.epub")
    assert not is_strict_descendant_path(ancestor=book, candidate=other)
    assert not is_resource_anchor_within_book_scope(
        book_anchor=book,
        book_anchor_kind=SourceNodePhysicalKind.DIRECTORY,
        resource_anchor=other,
    )
    assert not is_asset_path_within_resource_scope(
        resource_anchor=book,
        resource_anchor_kind=SourceNodePhysicalKind.DIRECTORY,
        asset_path=other,
    )


def test_case_and_unicode_spellings_remain_distinct_scopes() -> None:
    directory = _path("Books")
    lower = _path("books/a.epub")
    assert not is_strict_descendant_path(ancestor=directory, candidate=lower)
    nfc = SourceNodeRelativePath(unicodedata.normalize("NFC", "café"))
    nfd_child = SourceNodeRelativePath(unicodedata.normalize("NFD", "café") + "/a.epub")
    assert not is_strict_descendant_path(ancestor=nfc, candidate=nfd_child)


def test_literal_backslash_is_not_a_path_separator() -> None:
    directory = _path("dir")
    escaped = _path(r"dir\file.epub")
    assert not is_strict_descendant_path(ancestor=directory, candidate=escaped)


def test_file_resource_asset_must_be_self() -> None:
    resource = _path("novel.epub")
    assert is_asset_path_within_resource_scope(
        resource_anchor=resource,
        resource_anchor_kind=SourceNodePhysicalKind.REGULAR_FILE,
        asset_path=resource,
    )
    assert not is_asset_path_within_resource_scope(
        resource_anchor=resource,
        resource_anchor_kind=SourceNodePhysicalKind.REGULAR_FILE,
        asset_path=_path("other.epub"),
    )


def test_directory_resource_assets_must_be_descendants() -> None:
    resource = _path("album")
    track = _path("album/a.mp3")
    assert is_asset_path_within_resource_scope(
        resource_anchor=resource,
        resource_anchor_kind=SourceNodePhysicalKind.DIRECTORY,
        asset_path=track,
    )
    assert not is_asset_path_within_resource_scope(
        resource_anchor=resource,
        resource_anchor_kind=SourceNodePhysicalKind.DIRECTORY,
        asset_path=resource,
    )


def test_symlink_or_other_resource_kind_rejects_assets() -> None:
    resource = _path("odd")
    assert not is_asset_path_within_resource_scope(
        resource_anchor=resource,
        resource_anchor_kind=SourceNodePhysicalKind.SYMLINK,
        asset_path=_path("odd/a.epub"),
    )
