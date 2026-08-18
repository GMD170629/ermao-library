from __future__ import annotations

import unicodedata

from app.modules.library.domain.layout import (
    LayoutEntry,
    LayoutEntryType,
    LayoutResult,
    LayoutSourceType,
    LayoutViolationCode,
    LibraryOrganizationMode,
    interpret_library_layout,
)
from app.modules.library.domain.layout_ordering import natural_sort_key


def _file(
    path: str,
    source_type: LayoutSourceType = LayoutSourceType.PUBLICATION,
) -> LayoutEntry:
    return LayoutEntry(
        relative_path=path,
        entry_type=LayoutEntryType.FILE,
        source_type=source_type,
    )


def _directory(path: str) -> LayoutEntry:
    return LayoutEntry(
        relative_path=path,
        entry_type=LayoutEntryType.DIRECTORY,
        source_type=LayoutSourceType.UNSUPPORTED,
    )


def _audio(path: str) -> LayoutEntry:
    return _file(path, LayoutSourceType.AUDIO)


def _sidecar(path: str) -> LayoutEntry:
    return _file(path, LayoutSourceType.SIDECAR)


def _unsupported(path: str) -> LayoutEntry:
    return _file(path, LayoutSourceType.UNSUPPORTED)


def _interpret(
    mode: LibraryOrganizationMode,
    *entries: LayoutEntry,
) -> LayoutResult:
    return interpret_library_layout(entries, mode)


def _work_keys(result: LayoutResult) -> list[str]:
    return [work.source_key for work in result.works]


def _work_names(result: LayoutResult) -> list[str]:
    return [work.source_name for work in result.works]


def _volume_names(result: LayoutResult) -> list[str]:
    return [
        volume.source_name
        for work in result.works
        for version in work.versions
        for volume in version.volumes
    ]


def _asset_paths(result: LayoutResult) -> list[str]:
    return [
        asset.relative_path
        for work in result.works
        for version in work.versions
        for volume in version.volumes
        for asset in volume.assets
    ]


def _violation_codes(result: LayoutResult) -> list[LayoutViolationCode]:
    return [violation.code for violation in result.violations]


def test_flat_single_publication() -> None:
    result = _interpret(LibraryOrganizationMode.FLAT, _file("活着.epub"))

    assert _work_keys(result) == ["work:活着.epub"]
    work = result.works[0]
    assert work.source_name == "活着"
    assert work.versions[0].source_name is None
    assert work.versions[0].source_key == "version:活着.epub"
    assert _volume_names(result) == ["活着"]
    assert work.versions[0].volumes[0].source_key == "volume:活着.epub"
    assert _asset_paths(result) == ["活着.epub"]
    assert result.violations == ()


def test_flat_multiple_publications() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("怪兽8号.cbz"),
        _file("活着.epub"),
        _file("三体.epub"),
    )

    assert _work_names(result) == ["三体", "怪兽8号", "活着"]
    assert _work_keys(result) == [
        "work:三体.epub",
        "work:怪兽8号.cbz",
        "work:活着.epub",
    ]


def test_flat_same_stem_different_format_remain_separate() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("三体.epub"),
        _file("三体.pdf"),
    )

    assert _work_names(result) == ["三体", "三体"]
    assert _work_keys(result) == ["work:三体.epub", "work:三体.pdf"]
    assert result.works[0].versions[0].volumes[0].source_key == "volume:三体.epub"
    assert result.works[1].versions[0].volumes[0].source_key == "volume:三体.pdf"


def test_flat_natural_ordering() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("第10卷.epub"),
        _file("第1卷.epub"),
        _file("第2卷.epub"),
    )

    assert _work_names(result) == ["第1卷", "第2卷", "第10卷"]


def test_flat_sidecar_ignored() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("活着.epub"),
        _sidecar("cover.jpg"),
    )

    assert _work_keys(result) == ["work:活着.epub"]
    assert result.violations == ()


def test_flat_unsupported_ignored() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("活着.epub"),
        _unsupported("notes.txt"),
    )

    assert _work_keys(result) == ["work:活着.epub"]
    assert result.violations == ()


def test_flat_nested_directory_violation() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("活着.epub"),
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/01.epub"),
    )

    assert _work_keys(result) == ["work:活着.epub"]
    assert _asset_paths(result) == ["活着.epub"]
    assert len(result.violations) == 1
    assert result.violations[0].code is LayoutViolationCode.FLAT_NESTING_NOT_ALLOWED
    assert result.violations[0].relative_path == "三体"


def test_volumes_single_work_version() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/01 地球往事.epub"),
    )

    work = result.works[0]
    assert work.source_key == "work:三体"
    assert work.source_name == "三体"
    assert work.versions[0].source_key == "version:三体/中文版"
    assert work.versions[0].source_name == "中文版"
    assert _volume_names(result) == ["01 地球往事"]
    assert work.versions[0].volumes[0].source_key == (
        "volume:三体/中文版/01 地球往事.epub"
    )


def test_volumes_multiple_works() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/01.epub"),
        _directory("活着"),
        _directory("活着/默认"),
        _file("活着/默认/活着.epub"),
    )

    assert _work_keys(result) == ["work:三体", "work:活着"]
    assert _work_names(result) == ["三体", "活着"]


def test_volumes_multiple_versions() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/01.epub"),
        _directory("三体/英文版"),
        _file("三体/英文版/01.epub"),
    )

    work = result.works[0]
    assert [version.source_name for version in work.versions] == ["中文版", "英文版"]
    assert [version.source_key for version in work.versions] == [
        "version:三体/中文版",
        "version:三体/英文版",
    ]


def test_volumes_multiple_volumes() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/03 死神永生.epub"),
        _file("三体/中文版/01 地球往事.epub"),
        _file("三体/中文版/02 黑暗森林.epub"),
    )

    assert _volume_names(result) == ["01 地球往事", "02 黑暗森林", "03 死神永生"]


def test_volumes_natural_ordering() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("丛书"),
        _directory("丛书/默认"),
        _file("丛书/默认/第10卷.epub"),
        _file("丛书/默认/第2卷.epub"),
        _file("丛书/默认/第1卷.epub"),
    )

    assert _volume_names(result) == ["第1卷", "第2卷", "第10卷"]


def test_volumes_chinese_filenames() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/01 地球往事.epub"),
        _directory("三体/英文版"),
        _file("三体/英文版/01.epub"),
        _file("三体/英文版/02.epub"),
        _file("三体/英文版/03.epub"),
    )

    work = result.works[0]
    chinese, english = work.versions
    assert chinese.source_name == "中文版"
    assert [volume.source_name for volume in chinese.volumes] == ["01 地球往事"]
    assert english.source_name == "英文版"
    assert [volume.source_name for volume in english.volumes] == ["01", "02", "03"]


def test_volumes_sidecar_ignored() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/01.epub"),
        _sidecar("三体/中文版/cover.jpg"),
        _unsupported("三体/中文版/notes.txt"),
    )

    assert _asset_paths(result) == ["三体/中文版/01.epub"]
    assert result.violations == ()


def test_volumes_direct_file_under_work_rejected() -> None:
    result = _interpret(
        LibraryOrganizationMode.VOLUMES,
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体/中文版/01.epub"),
        _file("三体/三体.pdf"),
    )

    assert _work_keys(result) == ["work:三体"]
    assert _asset_paths(result) == ["三体/中文版/01.epub"]
    assert result.violations[0].code is (LayoutViolationCode.VERSION_DIRECTORY_REQUIRED)
    assert result.violations[0].relative_path == "三体/三体.pdf"


def test_audiobook_root_single_m4b() -> None:
    result = _interpret(LibraryOrganizationMode.AUDIOBOOK, _audio("魔戒.m4b"))

    work = result.works[0]
    assert work.source_key == "work:魔戒.m4b"
    assert work.source_name == "魔戒"
    assert work.versions[0].source_name is None
    assert work.versions[0].volumes[0].source_name == "魔戒"
    assert _asset_paths(result) == ["魔戒.m4b"]
    assert work.versions[0].volumes[0].assets[0].order == 0


def test_audiobook_work_with_multiple_tracks() -> None:
    result = _interpret(
        LibraryOrganizationMode.AUDIOBOOK,
        _directory("哈利波特与魔法石"),
        _audio("哈利波特与魔法石/003.mp3"),
        _audio("哈利波特与魔法石/001.mp3"),
        _audio("哈利波特与魔法石/002.mp3"),
        _sidecar("哈利波特与魔法石/cover.jpg"),
    )

    work = result.works[0]
    assert work.source_key == "work:哈利波特与魔法石"
    assert work.source_name == "哈利波特与魔法石"
    assert work.versions[0].source_name is None
    assert len(work.versions[0].volumes) == 1
    assert work.versions[0].volumes[0].source_name == "哈利波特与魔法石"
    assets = work.versions[0].volumes[0].assets
    assert [asset.relative_path for asset in assets] == [
        "哈利波特与魔法石/001.mp3",
        "哈利波特与魔法石/002.mp3",
        "哈利波特与魔法石/003.mp3",
    ]
    assert [asset.order for asset in work.versions[0].volumes[0].assets] == [0, 1, 2]


def test_audiobook_work_with_multiple_volume_directories() -> None:
    result = _interpret(
        LibraryOrganizationMode.AUDIOBOOK,
        _directory("某有声书"),
        _directory("某有声书/第一卷"),
        _audio("某有声书/第一卷/002.mp3"),
        _audio("某有声书/第一卷/001.mp3"),
        _directory("某有声书/第二卷"),
        _audio("某有声书/第二卷/001.mp3"),
        _audio("某有声书/第二卷/002.mp3"),
    )

    work = result.works[0]
    assert work.source_name == "某有声书"
    volumes = work.versions[0].volumes
    assert [volume.source_name for volume in volumes] == ["第一卷", "第二卷"]
    assert [volume.source_key for volume in volumes] == [
        "volume:某有声书/第一卷",
        "volume:某有声书/第二卷",
    ]
    assert [asset.relative_path for asset in volumes[0].assets] == [
        "某有声书/第一卷/001.mp3",
        "某有声书/第一卷/002.mp3",
    ]


def test_audiobook_track_natural_ordering() -> None:
    result = _interpret(
        LibraryOrganizationMode.AUDIOBOOK,
        _directory("有声书"),
        _audio("有声书/第10集.mp3"),
        _audio("有声书/第1集.mp3"),
        _audio("有声书/第2集.mp3"),
    )

    assets = result.works[0].versions[0].volumes[0].assets
    assert [asset.relative_path for asset in assets] == [
        "有声书/第1集.mp3",
        "有声书/第2集.mp3",
        "有声书/第10集.mp3",
    ]


def test_audiobook_sidecar_excluded() -> None:
    result = _interpret(
        LibraryOrganizationMode.AUDIOBOOK,
        _directory("有声书"),
        _audio("有声书/001.mp3"),
        _sidecar("有声书/cover.jpg"),
        _unsupported("有声书/readme.txt"),
        _file("有声书/book.epub"),
    )

    assert _asset_paths(result) == ["有声书/001.mp3"]
    assert result.violations == ()


def test_audiobook_mixed_direct_track_and_volume_directory_rejected() -> None:
    result = _interpret(
        LibraryOrganizationMode.AUDIOBOOK,
        _directory("某有声书"),
        _audio("某有声书/001.mp3"),
        _directory("某有声书/第一卷"),
        _audio("某有声书/第一卷/001.mp3"),
        _audio("魔戒.m4b"),
    )

    assert _work_keys(result) == ["work:魔戒.m4b"]
    assert result.violations[0].code is LayoutViolationCode.AUDIO_MIXED_LAYOUT
    assert result.violations[0].relative_path == "某有声书"


def test_audiobook_invalid_nesting_rejected() -> None:
    result = _interpret(
        LibraryOrganizationMode.AUDIOBOOK,
        _directory("有声书"),
        _directory("有声书/第一卷"),
        _audio("有声书/第一卷/001.mp3"),
        _directory("有声书/第一卷/disc"),
        _audio("有声书/第一卷/disc/002.mp3"),
    )

    assert _asset_paths(result) == ["有声书/第一卷/001.mp3"]
    assert result.violations[0].code is LayoutViolationCode.AUDIO_INVALID_NESTING
    assert result.violations[0].relative_path == "有声书/第一卷/disc"


def test_absolute_path_rejected() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("/tmp/活着.epub"),
        _file("C:/library/活着.epub"),
        _file("活着.epub"),
    )

    assert _work_keys(result) == ["work:活着.epub"]
    assert _violation_codes(result) == [
        LayoutViolationCode.INVALID_RELATIVE_PATH,
        LayoutViolationCode.INVALID_RELATIVE_PATH,
    ]


def test_dotdot_rejected() -> None:
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file("../活着.epub"),
        _file("foo/../活着.epub"),
        _file("foo/./活着.epub"),
        _file("活着.epub"),
    )

    assert _work_keys(result) == ["work:活着.epub"]
    assert _violation_codes(result) == [
        LayoutViolationCode.INVALID_RELATIVE_PATH,
        LayoutViolationCode.INVALID_RELATIVE_PATH,
        LayoutViolationCode.INVALID_RELATIVE_PATH,
    ]


def test_nfc_deterministic() -> None:
    nfd_name = unicodedata.normalize("NFD", "café.epub")
    nfc_name = unicodedata.normalize("NFC", "café.epub")
    assert nfd_name != nfc_name

    nfd_result = _interpret(LibraryOrganizationMode.FLAT, _file(nfd_name))
    nfc_result = _interpret(LibraryOrganizationMode.FLAT, _file(nfc_name))

    assert nfd_result.works[0].source_key == nfc_result.works[0].source_key
    assert nfd_result.works[0].source_key == f"work:{nfc_name}"
    assert nfd_result.works[0].source_name == nfc_result.works[0].source_name


def test_normalized_collision_detected() -> None:
    nfd_name = unicodedata.normalize("NFD", "café.epub")
    nfc_name = unicodedata.normalize("NFC", "café.epub")
    result = _interpret(
        LibraryOrganizationMode.FLAT,
        _file(nfd_name),
        _file(nfc_name),
    )

    assert len(result.works) == 1
    assert result.works[0].source_key == f"work:{nfc_name}"
    assert result.violations[0].code is LayoutViolationCode.NORMALIZED_PATH_COLLISION


def test_backslash_normalized_and_same_input_is_stable() -> None:
    entries = (
        _directory("三体"),
        _directory("三体/中文版"),
        _file("三体\\中文版\\01.epub"),
        _file("三体/中文版/02.epub"),
    )
    first = interpret_library_layout(entries, LibraryOrganizationMode.VOLUMES)
    second = interpret_library_layout(entries, LibraryOrganizationMode.VOLUMES)

    assert first == second
    assert _asset_paths(first) == [
        "三体/中文版/01.epub",
        "三体/中文版/02.epub",
    ]


def test_natural_sort_orders_embedded_integers() -> None:
    names = ["第10卷", "第1卷", "第2卷", "11", "2", "1"]
    assert sorted(names, key=natural_sort_key) == [
        "1",
        "2",
        "11",
        "第1卷",
        "第2卷",
        "第10卷",
    ]
