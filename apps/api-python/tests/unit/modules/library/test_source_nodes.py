from __future__ import annotations

import hashlib
import unicodedata

import pytest

from app.modules.library.domain.source_nodes import (
    InvalidSourceNodeRelativePathError,
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    SourceNodeTreeNode,
    SourceNodeViolationCode,
    evaluate_path_key_occupancy,
    parse_source_node_relative_path,
    validate_source_node_direct_parent,
)

ILLEGAL_RELATIVE_PATHS = (
    "",
    "/abs.epub",
    "/rooted/book.epub",
    "a//b.epub",
    "a/./b.epub",
    "a/../b.epub",
    "./book.epub",
    "../book.epub",
    "book.epub/",
    "a/\x00b.epub",
    "C:/books/a.epub",
    "c:books",
    "D:\\shelf\\a.epub",
    "//server/share/a.epub",
    r"\\server\share\a.epub",
)


def _path(raw: str) -> SourceNodeRelativePath:
    parsed = parse_source_node_relative_path(raw)
    assert isinstance(parsed, SourceNodeRelativePath)
    return parsed


def _node(
    library_id: str,
    relative_path: str,
    physical_kind: SourceNodePhysicalKind,
) -> SourceNodeTreeNode:
    return SourceNodeTreeNode(
        library_id=library_id,
        relative_path=_path(relative_path),
        physical_kind=physical_kind,
    )


def test_path_key_fixed_test_vector() -> None:
    expected = "v1:" + hashlib.sha256(b"book.epub").hexdigest()
    assert expected == (
        "v1:a783c0b522105865a40936732a5ffbab7d1f5fbeddba4d6a57d83dea9be5f055"
    )
    assert SourceNodeRelativePath("book.epub").path_key == expected
    assert _path("book.epub").path_key == expected


def test_case_differences_produce_distinct_identities() -> None:
    lower = _path("Books/Novel.epub")
    upper = _path("Books/novel.epub")
    assert lower.value != upper.value
    assert lower.path_key != upper.path_key
    assert lower.name == "Novel.epub"
    assert upper.name == "novel.epub"


def test_nfc_and_nfd_spellings_are_preserved_as_distinct_identities() -> None:
    nfc = unicodedata.normalize("NFC", "café/book.epub")
    nfd = unicodedata.normalize("NFD", "café/book.epub")
    assert nfc != nfd
    nfc_path = _path(nfc)
    nfd_path = _path(nfd)
    assert nfc_path.value == nfc
    assert nfd_path.value == nfd
    assert nfc_path.path_key != nfd_path.path_key


def test_literal_backslash_is_preserved_and_not_equivalent_to_slash() -> None:
    with_backslash = _path(r"dir\file.epub")
    with_slash = _path("dir/file.epub")
    assert with_backslash.value == r"dir\file.epub"
    assert with_backslash.name == r"dir\file.epub"
    assert with_backslash.parent_relative_path is None
    assert with_backslash.is_root_child
    assert with_slash.name == "file.epub"
    assert with_slash.parent_relative_path == "dir"
    assert with_backslash.path_key != with_slash.path_key


@pytest.mark.parametrize("relative_path", ILLEGAL_RELATIVE_PATHS)
def test_illegal_relative_paths_are_rejected_by_parser(
    relative_path: str,
) -> None:
    result = parse_source_node_relative_path(relative_path)
    assert not isinstance(result, SourceNodeRelativePath)
    assert result.code is SourceNodeViolationCode.INVALID_RELATIVE_PATH
    assert result.relative_path == relative_path


@pytest.mark.parametrize("relative_path", ILLEGAL_RELATIVE_PATHS)
def test_direct_construction_rejects_illegal_paths(
    relative_path: str,
) -> None:
    with pytest.raises(InvalidSourceNodeRelativePathError) as caught:
        SourceNodeRelativePath(relative_path)
    error = caught.value
    assert error.code is SourceNodeViolationCode.INVALID_RELATIVE_PATH
    assert error.relative_path == relative_path


def test_legal_direct_construction_matches_parser() -> None:
    raw = "Series/中文版/01.epub"
    constructed = SourceNodeRelativePath(raw)
    parsed = parse_source_node_relative_path(raw)
    assert isinstance(parsed, SourceNodeRelativePath)
    assert constructed == parsed
    assert constructed.value == raw
    assert constructed.path_key == parsed.path_key


def test_name_and_parent_path_come_from_validated_original_path() -> None:
    path = _path("Series/中文版/01.epub")
    assert path.value == "Series/中文版/01.epub"
    assert path.name == "01.epub"
    assert path.parent_relative_path == "Series/中文版"
    assert _path("Series/中文版").parent_relative_path == "Series"
    assert _path("root-only.epub").parent_relative_path is None


def test_root_child_requires_absent_parent() -> None:
    node = _node("lib-a", "book.epub", SourceNodePhysicalKind.REGULAR_FILE)
    assert validate_source_node_direct_parent(node=node, parent=None) == ()

    stray_parent = _node("lib-a", "other", SourceNodePhysicalKind.DIRECTORY)
    violations = validate_source_node_direct_parent(
        node=node,
        parent=stray_parent,
    )
    assert len(violations) == 1
    assert violations[0].code is SourceNodeViolationCode.PARENT_PATH_MISMATCH


def test_valid_direct_parent_relationship() -> None:
    parent = _node("lib-a", "Series", SourceNodePhysicalKind.DIRECTORY)
    child = _node(
        "lib-a",
        "Series/01.epub",
        SourceNodePhysicalKind.REGULAR_FILE,
    )
    assert validate_source_node_direct_parent(node=child, parent=parent) == ()


def test_missing_parent_for_nested_node_is_path_mismatch() -> None:
    child = _node(
        "lib-a",
        "Series/01.epub",
        SourceNodePhysicalKind.REGULAR_FILE,
    )
    violations = validate_source_node_direct_parent(node=child, parent=None)
    assert len(violations) == 1
    assert violations[0].code is SourceNodeViolationCode.PARENT_PATH_MISMATCH


def test_cross_library_parent_is_rejected() -> None:
    parent = _node("lib-b", "Series", SourceNodePhysicalKind.DIRECTORY)
    child = _node(
        "lib-a",
        "Series/01.epub",
        SourceNodePhysicalKind.REGULAR_FILE,
    )
    violations = validate_source_node_direct_parent(node=child, parent=parent)
    assert len(violations) == 1
    assert violations[0].code is SourceNodeViolationCode.CROSS_LIBRARY_PARENT


def test_non_directory_parent_is_rejected() -> None:
    parent = _node("lib-a", "Series", SourceNodePhysicalKind.REGULAR_FILE)
    child = _node(
        "lib-a",
        "Series/01.epub",
        SourceNodePhysicalKind.REGULAR_FILE,
    )
    violations = validate_source_node_direct_parent(node=child, parent=parent)
    assert len(violations) == 1
    assert violations[0].code is SourceNodeViolationCode.PARENT_NOT_DIRECTORY


def test_wrong_parent_path_is_rejected() -> None:
    parent = _node("lib-a", "Other", SourceNodePhysicalKind.DIRECTORY)
    child = _node(
        "lib-a",
        "Series/01.epub",
        SourceNodePhysicalKind.REGULAR_FILE,
    )
    violations = validate_source_node_direct_parent(node=child, parent=parent)
    assert len(violations) == 1
    assert violations[0].code is SourceNodeViolationCode.PARENT_PATH_MISMATCH


def test_ancestor_that_is_not_direct_parent_is_rejected() -> None:
    parent = _node("lib-a", "Series", SourceNodePhysicalKind.DIRECTORY)
    child = _node(
        "lib-a",
        "Series/Vol/01.epub",
        SourceNodePhysicalKind.REGULAR_FILE,
    )
    violations = validate_source_node_direct_parent(node=child, parent=parent)
    assert len(violations) == 1
    assert violations[0].code is SourceNodeViolationCode.PARENT_PATH_MISMATCH


def test_self_parent_is_rejected() -> None:
    node = _node("lib-a", "Series", SourceNodePhysicalKind.DIRECTORY)
    violations = validate_source_node_direct_parent(node=node, parent=node)
    assert len(violations) == 1
    assert violations[0].code is SourceNodeViolationCode.SELF_PARENT


def test_same_path_key_same_relative_path_is_idempotent() -> None:
    path = SourceNodeRelativePath("Books/A.epub")
    assert (
        evaluate_path_key_occupancy(
            occupied_relative_path=path,
            candidate_relative_path=SourceNodeRelativePath("Books/A.epub"),
        )
        is None
    )


def test_same_path_key_different_relative_path_is_collision() -> None:
    # Occupancy rule is evaluated after the caller already matched pathKey.
    # Distinct originals with the same digest must collide without hashing tricks.
    occupied = SourceNodeRelativePath("Books/A.epub")
    candidate = SourceNodeRelativePath("Books/B.epub")
    violation = evaluate_path_key_occupancy(
        occupied_relative_path=occupied,
        candidate_relative_path=candidate,
    )
    assert violation is not None
    assert violation.code is SourceNodeViolationCode.PATH_KEY_COLLISION
    assert violation.relative_path == "Books/B.epub"


def test_physical_kind_values_match_adr() -> None:
    assert SourceNodePhysicalKind.REGULAR_FILE.value == "REGULAR_FILE"
    assert SourceNodePhysicalKind.DIRECTORY.value == "DIRECTORY"
    assert SourceNodePhysicalKind.SYMLINK.value == "SYMLINK"
    assert SourceNodePhysicalKind.OTHER.value == "OTHER"
