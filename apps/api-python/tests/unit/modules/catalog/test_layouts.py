from __future__ import annotations

import pytest

from app.modules.catalog.public import (
    AdmissionKind,
    EntryType,
    OrganizationMode,
    PathComparison,
    ProbedEntry,
    SourceKind,
    ViolationCode,
    interpret_layout,
)


def _parts(path: str) -> tuple[str, ...]:
    return tuple(path.split("/"))


def _file(
    path: str,
    *,
    admission: AdmissionKind = AdmissionKind.PRIMARY,
    source_format: str | None = None,
) -> ProbedEntry:
    if source_format is None:
        source_format = path.rsplit(".", 1)[-1].lower()
    return ProbedEntry(
        relative_path=_parts(path),
        entry_type=EntryType.FILE,
        admission=admission,
        source_format=source_format,
    )


def _audio(path: str) -> ProbedEntry:
    return _file(path, admission=AdmissionKind.AUDIO_TRACK)


def _sidecar(path: str) -> ProbedEntry:
    role = "OPF" if path.lower().endswith(".opf") else "COVER"
    return ProbedEntry(
        relative_path=_parts(path),
        entry_type=EntryType.FILE,
        admission=AdmissionKind.SIDECAR,
        sidecar_role=role,
    )


def _unsupported(path: str) -> ProbedEntry:
    return _file(path, admission=AdmissionKind.UNSUPPORTED, source_format=None)


def _directory(path: str) -> ProbedEntry:
    return ProbedEntry(
        relative_path=_parts(path),
        entry_type=EntryType.DIRECTORY,
        admission=AdmissionKind.IGNORED,
    )


def _symlink(path: str) -> ProbedEntry:
    return ProbedEntry(
        relative_path=_parts(path),
        entry_type=EntryType.SYMLINK,
        admission=AdmissionKind.IGNORED,
    )


def _interpret(mode: OrganizationMode, entries: list[ProbedEntry]):
    return interpret_layout(
        mode,
        entries,
        path_comparison=PathComparison.SENSITIVE,
    )


def _codes(result) -> set[str]:
    return {violation.code.value for violation in result.violations}


def _paths(result) -> set[str]:
    return {
        "/".join(asset.path)
        for candidate in result.candidates
        for asset in candidate.assets
    }


def test_flat_accepts_root_files_and_keeps_same_stem_formats_separate() -> None:
    result = _interpret(
        OrganizationMode.FLAT,
        [_file("book.epub"), _file("book.pdf"), _audio("recording.m4b")],
    )

    assert not result.violations
    assert len(result.candidates) == 3
    assert _paths(result) == {"book.epub", "book.pdf", "recording.m4b"}
    candidate = result.candidates[0]
    assert candidate.work_path == ("book.epub",)
    assert candidate.version_path is None
    assert candidate.volume_path == ("book.epub",)
    assert candidate.source_kind is SourceKind.SINGLE_FILE
    assert candidate.assets[0].path == ("book.epub",)
    assert candidate.assets[0].order == 0


def test_flat_rejects_directories_but_ignores_sidecars_and_unsupported_files() -> None:
    result = _interpret(
        OrganizationMode.FLAT,
        [
            _file("book.epub"),
            _directory("nested"),
            _sidecar("book.opf"),
            _sidecar("cover.png"),
            _unsupported("notes.docx"),
        ],
    )

    assert ViolationCode.FLAT_NESTING_NOT_ALLOWED.value in _codes(result)
    assert len(result.candidates) == 1
    assert _paths(result) == {"book.epub"}


def test_flat_rejects_symlink_as_a_diagnostic_without_creating_a_node() -> None:
    result = _interpret(
        OrganizationMode.FLAT,
        [_file("book.epub"), _symlink("linked.epub")],
    )

    assert "SYMLINK_NOT_ALLOWED" in _codes(result)
    assert _paths(result) == {"book.epub"}


def test_insensitive_normalized_path_collision_isolated_to_the_smallest_unit() -> None:
    result = interpret_layout(
        OrganizationMode.FLAT,
        [_file("Book.epub"), _file("book.epub")],
        path_comparison=PathComparison.INSENSITIVE,
    )

    assert "PATH_NORMALIZATION_COLLISION" in _codes(result)
    assert not result.candidates


def test_flat_invalid_root_directory_hides_descendant_collisions() -> None:
    result = interpret_layout(
        OrganizationMode.FLAT,
        [
            _directory("nested"),
            _file("nested/Book.epub"),
            _file("nested/book.epub"),
        ],
        path_comparison=PathComparison.INSENSITIVE,
    )

    assert _codes(result) == {ViolationCode.FLAT_NESTING_NOT_ALLOWED.value}
    assert result.violations[0].unit_path == ("nested",)


def test_insensitive_symlink_and_file_collision_is_not_hidden_by_symlink_filter() -> (
    None
):
    result = interpret_layout(
        OrganizationMode.FLAT,
        [_file("Book.epub"), _symlink("book.epub")],
        path_comparison=PathComparison.INSENSITIVE,
    )

    assert "PATH_NORMALIZATION_COLLISION" in _codes(result)
    assert not result.candidates


def test_audiobook_track_collision_invalidates_work_not_sibling_work() -> None:
    result = interpret_layout(
        OrganizationMode.AUDIOBOOK,
        [
            _directory("bad-book"),
            _audio("bad-book/Track-01.mp3"),
            _audio("bad-book/track-01.mp3"),
            _audio("bad-book/track-02.mp3"),
            _directory("good-book"),
            _audio("good-book/track-01.mp3"),
        ],
        path_comparison=PathComparison.INSENSITIVE,
    )

    assert "PATH_NORMALIZATION_COLLISION" in _codes(result)
    assert _paths(result) == {"good-book/track-01.mp3"}
    violation = next(
        item
        for item in result.violations
        if item.code.value == "PATH_NORMALIZATION_COLLISION"
    )
    assert violation.unit_path == ("bad-book",)


def test_nfc_normalized_paths_cannot_create_two_primary_slots() -> None:
    result = interpret_layout(
        OrganizationMode.FLAT,
        [_file("cafe\u0301.epub"), _file("caf\u00e9.epub")],
        path_comparison=PathComparison.SENSITIVE,
    )

    assert "PATH_NORMALIZATION_COLLISION" in _codes(result)
    assert not result.candidates


def test_flat_invalid_root_directory_hides_descendant_symlink_diagnostic() -> None:
    result = interpret_layout(
        OrganizationMode.FLAT,
        [_directory("nested"), _symlink("nested/linked.epub")],
        path_comparison=PathComparison.INSENSITIVE,
    )

    assert _codes(result) == {ViolationCode.FLAT_NESTING_NOT_ALLOWED.value}
    assert result.violations[0].unit_path == ("nested",)


def test_empty_and_sidecar_only_layouts_create_no_nodes() -> None:
    assert not _interpret(OrganizationMode.FLAT, []).candidates
    assert not _interpret(
        OrganizationMode.FLAT,
        [_sidecar("metadata.opf"), _sidecar("cover.jpg")],
    ).candidates


def test_volumes_accepts_work_version_single_files() -> None:
    result = _interpret(
        OrganizationMode.VOLUMES,
        [
            _directory("work-a"),
            _directory("work-a/version-1"),
            _file("work-a/version-1/volume-01.epub"),
        ],
    )

    assert not result.violations
    assert len(result.candidates) == 1
    assert _paths(result) == {"work-a/version-1/volume-01.epub"}
    candidate = result.candidates[0]
    assert candidate.work_path == ("work-a",)
    assert candidate.version_path == ("work-a", "version-1")
    assert candidate.volume_path == ("work-a", "version-1", "volume-01.epub")
    assert candidate.source_kind is SourceKind.SINGLE_FILE
    assert candidate.assets[0].path == candidate.volume_path
    assert candidate.assets[0].order == 0


def test_volumes_work_level_file_does_not_invalidate_valid_sibling_version() -> None:
    result = _interpret(
        OrganizationMode.VOLUMES,
        [
            _directory("work-a"),
            _file("work-a/loose.epub"),
            _directory("work-a/version-1"),
            _file("work-a/version-1/volume-01.epub"),
        ],
    )

    assert ViolationCode.VERSION_DIRECTORY_REQUIRED.value in _codes(result)
    assert _paths(result) == {"work-a/version-1/volume-01.epub"}
    assert len(result.candidates) == 1


def test_volumes_accepts_valid_audio_bundle_and_orders_it_as_one_volume() -> None:
    result = _interpret(
        OrganizationMode.VOLUMES,
        [
            _directory("work-a"),
            _directory("work-a/version-1"),
            _directory("work-a/version-1/audio"),
            _audio("work-a/version-1/audio/track-02.mp3"),
            _audio("work-a/version-1/audio/track-01.mp3"),
        ],
    )

    assert not result.violations
    assert len(result.candidates) == 1
    assert _paths(result) == {
        "work-a/version-1/audio/track-01.mp3",
        "work-a/version-1/audio/track-02.mp3",
    }


def test_volumes_bad_bundle_isolated_from_valid_sibling_volume() -> None:
    result = _interpret(
        OrganizationMode.VOLUMES,
        [
            _directory("work-a"),
            _directory("work-a/version-1"),
            _directory("work-a/version-1/bad"),
            _directory("work-a/version-1/bad/nested"),
            _audio("work-a/version-1/bad/nested/track.mp3"),
            _directory("work-a/version-1/good"),
            _audio("work-a/version-1/good/track-01.mp3"),
        ],
    )

    assert ViolationCode.BUNDLE_LAYOUT_AMBIGUOUS.value in _codes(result)
    assert _paths(result) == {"work-a/version-1/good/track-01.mp3"}
    violation = next(
        item
        for item in result.violations
        if item.code is ViolationCode.BUNDLE_LAYOUT_AMBIGUOUS
    )
    assert violation.unit_path == ("work-a", "version-1", "bad")


def test_volumes_symlink_invalidates_only_its_bundle() -> None:
    result = _interpret(
        OrganizationMode.VOLUMES,
        [
            _directory("work-a"),
            _directory("work-a/version-1"),
            _directory("work-a/version-1/bad"),
            _symlink("work-a/version-1/bad/linked.mp3"),
            _directory("work-a/version-1/good"),
            _audio("work-a/version-1/good/track-01.mp3"),
        ],
    )

    assert "SYMLINK_NOT_ALLOWED" in _codes(result)
    assert _paths(result) == {"work-a/version-1/good/track-01.mp3"}
    violation = next(
        item for item in result.violations if item.code.value == "SYMLINK_NOT_ALLOWED"
    )
    assert violation.unit_path == ("work-a", "version-1", "bad")


def test_volumes_bundle_collision_invalidates_bundle_not_sibling_volumes() -> None:
    result = interpret_layout(
        OrganizationMode.VOLUMES,
        [
            _directory("work-a"),
            _directory("work-a/version-1"),
            _directory("work-a/version-1/bad"),
            _audio("work-a/version-1/bad/Track-01.mp3"),
            _audio("work-a/version-1/bad/track-01.mp3"),
            _audio("work-a/version-1/bad/track-02.mp3"),
            _file("work-a/version-1/single.epub"),
            _directory("work-a/version-1/good"),
            _audio("work-a/version-1/good/track-01.mp3"),
        ],
        path_comparison=PathComparison.INSENSITIVE,
    )

    assert "PATH_NORMALIZATION_COLLISION" in _codes(result)
    assert _paths(result) == {
        "work-a/version-1/single.epub",
        "work-a/version-1/good/track-01.mp3",
    }
    violation = next(
        item
        for item in result.violations
        if item.code.value == "PATH_NORMALIZATION_COLLISION"
    )
    assert violation.unit_path == ("work-a", "version-1", "bad")


def test_volumes_version_collision_isolates_version_not_sibling_version() -> None:
    result = interpret_layout(
        OrganizationMode.VOLUMES,
        [
            _directory("work-a"),
            _directory("work-a/Version"),
            _file("work-a/Version/book.epub"),
            _directory("work-a/version"),
            _file("work-a/version/book.epub"),
            _directory("work-a/version-2"),
            _file("work-a/version-2/book.epub"),
        ],
        path_comparison=PathComparison.INSENSITIVE,
    )

    assert "PATH_NORMALIZATION_COLLISION" in _codes(result)
    assert _paths(result) == {"work-a/version-2/book.epub"}
    violation = next(
        item
        for item in result.violations
        if item.code.value == "PATH_NORMALIZATION_COLLISION"
    )
    assert violation.unit_path == ("work-a", "Version")


def test_audiobook_accepts_root_audio_file() -> None:
    result = _interpret(OrganizationMode.AUDIOBOOK, [_audio("single-book.m4b")])

    assert not result.violations
    assert len(result.candidates) == 1
    assert _paths(result) == {"single-book.m4b"}


def test_audiobook_rejects_supported_non_audio_root_file() -> None:
    result = _interpret(OrganizationMode.AUDIOBOOK, [_file("book.epub")])

    assert ViolationCode.AUDIO_NON_AUDIO_RESOURCE.value in _codes(result)
    assert not result.candidates


def test_audiobook_direct_tracks_sort_before_disc_tracks() -> None:
    result = _interpret(
        OrganizationMode.AUDIOBOOK,
        [
            _directory("book"),
            _directory("book/Disc 1"),
            _audio("book/Disc 1/track-01.mp3"),
            _audio("book/track-02.mp3"),
            _audio("book/track-01.mp3"),
        ],
    )

    assert not result.violations
    assert len(result.candidates) == 1
    assets = result.candidates[0].assets
    assert ["/".join(asset.path) for asset in assets] == [
        "book/track-01.mp3",
        "book/track-02.mp3",
        "book/Disc 1/track-01.mp3",
    ]
    assert [asset.disc_number for asset in assets] == [0, 0, 1]
    candidate = result.candidates[0]
    assert candidate.work_path == ("book",)
    assert candidate.version_path is None
    assert candidate.volume_path == ("book",)
    assert candidate.source_kind is SourceKind.MULTI_ASSET_AUDIO
    assert [asset.order for asset in assets] == [0, 1, 2]


def test_audiobook_accepts_named_volume_directories() -> None:
    result = _interpret(
        OrganizationMode.AUDIOBOOK,
        [
            _directory("book"),
            _directory("book/volume-02"),
            _audio("book/volume-02/track-01.mp3"),
            _directory("book/volume-01"),
            _audio("book/volume-01/track-01.mp3"),
        ],
    )

    assert not result.violations
    assert len(result.candidates) == 2


def test_audiobook_rejects_mixed_direct_tracks_and_named_volume_directories() -> None:
    result = _interpret(
        OrganizationMode.AUDIOBOOK,
        [
            _directory("book"),
            _audio("book/track-01.mp3"),
            _directory("book/volume-01"),
            _audio("book/volume-01/track-01.mp3"),
        ],
    )

    assert ViolationCode.AUDIO_LAYOUT_MIXED.value in _codes(result)
    assert not result.candidates


def test_audiobook_symlink_invalidates_only_its_work() -> None:
    result = _interpret(
        OrganizationMode.AUDIOBOOK,
        [
            _directory("bad-book"),
            _symlink("bad-book/linked.mp3"),
            _directory("good-book"),
            _audio("good-book/track-01.mp3"),
        ],
    )

    assert "SYMLINK_NOT_ALLOWED" in _codes(result)
    assert _paths(result) == {"good-book/track-01.mp3"}
    violation = next(
        item for item in result.violations if item.code.value == "SYMLINK_NOT_ALLOWED"
    )
    assert violation.unit_path == ("bad-book",)


def test_audiobook_rejects_non_audio_resources_and_deep_directories() -> None:
    non_audio_result = _interpret(
        OrganizationMode.AUDIOBOOK,
        [
            _directory("book"),
            _audio("book/track-01.mp3"),
            _file("book/cover.epub"),
        ],
    )
    assert ViolationCode.AUDIO_NON_AUDIO_RESOURCE.value in _codes(non_audio_result)

    deep_result = _interpret(
        OrganizationMode.AUDIOBOOK,
        [
            _directory("book"),
            _audio("book/track-01.mp3"),
            _directory("book/Disc 1"),
            _directory("book/Disc 1/subdir"),
            _audio("book/Disc 1/subdir/track-02.mp3"),
        ],
    )

    assert ViolationCode.AUDIO_DEPTH_EXCEEDED.value in _codes(deep_result)
    assert not deep_result.candidates


def test_audiobook_rejects_more_than_ten_thousand_tracks_as_one_bad_work() -> None:
    entries = [_directory("book")]
    entries.extend(_audio(f"book/track-{index:05d}.mp3") for index in range(1, 10_002))
    entries.extend([_directory("sibling"), _audio("sibling/track-01.mp3")])

    result = _interpret(OrganizationMode.AUDIOBOOK, entries)

    assert ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED.value in _codes(result)
    assert {"sibling/track-01.mp3"} == _paths(result)
    violation = next(
        item
        for item in result.violations
        if item.code is ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED
    )
    assert violation.unit_path == ("book",)


def test_volumes_audio_bundle_limit_invalidates_only_that_volume() -> None:
    entries = [
        _directory("work-a"),
        _directory("work-a/version-1"),
        _directory("work-a/version-1/too-large"),
        _directory("work-a/version-1/good"),
        _audio("work-a/version-1/good/track-01.mp3"),
    ]
    entries.extend(
        _audio(f"work-a/version-1/too-large/track-{index:05d}.mp3")
        for index in range(1, 10_002)
    )

    result = _interpret(OrganizationMode.VOLUMES, entries)

    assert ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED.value in _codes(result)
    assert _paths(result) == {"work-a/version-1/good/track-01.mp3"}
    violation = next(
        item
        for item in result.violations
        if item.code is ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED
    )
    assert violation.unit_path == ("work-a", "version-1", "too-large")


def test_audiobook_named_volumes_allow_exactly_ten_thousand_tracks() -> None:
    entries = [_directory("book"), _directory("book/volume-01")]
    entries.extend(
        _audio(f"book/volume-01/track-{index:05d}.mp3") for index in range(1, 5_001)
    )
    entries.append(_directory("book/volume-02"))
    entries.extend(
        _audio(f"book/volume-02/track-{index:05d}.mp3")
        for index in range(5_001, 10_001)
    )

    result = _interpret(OrganizationMode.AUDIOBOOK, entries)

    assert not result.violations
    assert len(result.candidates) == 2
    assert len(_paths(result)) == 10_000


def test_audiobook_named_volume_track_limit_invalidates_work_not_sibling() -> None:
    entries = [_directory("book"), _directory("book/volume-01")]
    entries.extend(
        _audio(f"book/volume-01/track-{index:05d}.mp3") for index in range(1, 5_001)
    )
    entries.extend([_directory("book/volume-02")])
    entries.extend(
        _audio(f"book/volume-02/track-{index:05d}.mp3")
        for index in range(5_001, 10_002)
    )
    entries.extend([_directory("sibling"), _audio("sibling/track-01.mp3")])

    result = _interpret(OrganizationMode.AUDIOBOOK, entries)

    assert ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED.value in _codes(result)
    assert _paths(result) == {"sibling/track-01.mp3"}
    violation = next(
        item
        for item in result.violations
        if item.code is ViolationCode.AUDIO_TRACK_LIMIT_EXCEEDED
    )
    assert violation.unit_path == ("book",)


@pytest.mark.parametrize(
    ("mode", "path"),
    [
        (OrganizationMode.FLAT, "book.epub"),
        (OrganizationMode.VOLUMES, "work/version/book.epub"),
        (OrganizationMode.AUDIOBOOK, "book/track-01.mp3"),
    ],
)
def test_symlink_never_becomes_a_primary_asset(
    mode: OrganizationMode,
    path: str,
) -> None:
    result = _interpret(mode, [_symlink(path)])

    assert not result.candidates
