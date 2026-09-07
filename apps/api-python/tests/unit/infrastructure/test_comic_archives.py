"""Comic archive adapter coverage with real RAR4 and RAR5 containers."""

from __future__ import annotations

import base64
import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
import rarfile
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
)
from app.core.config import Settings
from app.infrastructure import comic_archives as comic_archives_module
from app.infrastructure.comic_archives import (
    ComicArchiveBackendUnavailableError,
    ComicArchiveEncryptedError,
    ComicArchiveInvalidError,
    ComicArchiveMultiVolumeError,
    extract_comic_cover,
    inspect_comic_archive,
    open_comic_archive,
)
from app.modules.media.infrastructure import http_streaming

_RAR4_COMIC = """UmFyIRoHAM+QcwAADQAAAAAAAACl6HQgkDYA/wQAAP8EAAADIpdnVhV79lwUMBEApIEAAGZhdmljb24tMTZ4MTYucG5nAPAUYFSJUE5HDQoaCgAAAA1JSERSAAAAEAAAABAIAgAAAJCRaDYAAAAEZ0FNQQAAsY8L/GEFAAAAIGNIUk0AAHomAACAhAAA+gAAAIDoAAB1MAAA6mAAADqYAAAXcJy6UTwAAABEZVhJZk1NACoAAAAIAAGHaQAEAAAAAQAAABoAAAAAAAOgAQADAAAAAQABAACgAgAEAAAAAQAAABCgAwAEAAAAAQAAABAAAAAANFVx8gAAAc1pVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IlhNUCBDb3JlIDYuMC4wIj4KICAgPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4KICAgICAgPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIKICAgICAgICAgICAgeG1sbnM6ZXhpZj0iaHR0cDovL25zLmFkb2JlLmNvbS9leGlmLzEuMC8iPgogICAgICAgICA8ZXhpZjpDb2xvclNwYWNlPjE8L2V4aWY6Q29sb3JTcGFjZT4KICAgICAgICAgPGV4aWY6UGl4ZWxYRGltZW5zaW9uPjEwMjQ8L2V4aWY6UGl4ZWxYRGltZW5zaW9uPgogICAgICAgICA8ZXhpZjpQaXhlbFlEaW1lbnNpb24+MTAyNDwvZXhpZjpQaXhlbFlEaW1lbnNpb24+CiAgICAgIDwvcmRmOkRlc2NyaXB0aW9uPgogICA8L3JkZjpSREY+CjwveDp4bXBtZXRhPgrB7TupAAACYUlEQVQoFU1STWsTQRjedz72O2vSJmm0trZ+VEEtrWhFhFIUD1rw0lt/gHfvHv0B/gsvgqgVD9WeCkItKMWqUBSEmiZp0mw3u9vd7OyMs0kKncPA+8zzvF/PAPPrCignDyAMCElEcC54evJJEYJksRiAQEgqlKixlzQbEqLFsl4+jUERjA0YitIT9CJQVW/nV7jyEv/+gY4CWTXUrc7Fq+bjZefClOh2+xpZOssPVG193dj7+F7Uq9Q7oILLB9xxRW13b+XVwbdNoLQvAObXABN/v+49f4oWFrUbd92f27u1Wqoa586ODk1O+quv8dZG7tkLq1gUKZctgcDYX31rt6r7zWY+Z8e35vNtd7hQkCMaJtkPj8rNf51P78zlJ0oaEQCIfR+2NxOiwcQVrTRWEXBmpJKtTigcwH6wFGx9xt+/dINlTaVIQYh1DnG7GY5PVRYeyqzr6x+q1b9xHK+tvXFb9ZHrN7tz90WrwXxPkvtDQ8p5MjVj5hyF8+npOdu0RdKdnb3jOHkkUn3+UUR16G2fCC6ocyrOl+jEpajjRr6nGRbwNDpsG8Ml/7BNdSOJAj5Uplk6gWQPqmWhmdvSV2ks52kcBVE3Froeeq5cpWrawZ8devkatSwxcJqx/L3FVqNl6CYBRFVNClnKCKE8TQnC+vj5wtiokvktpA/1zDiMPM9PmCgMFTEhmZnZlkSSJO5BU1Wx49jSBGnBQJBpAMIw9MMIE6ppBqFqGHhJHOVylmkactSe0ycEfY3sUi40YQwAEYw0TZOJJNhjyysT1AbB8ScH2Q3IL5qR+tcxQYL8P9IGMhxRwRgrAAAAAElFTkSuQmCCQ1l0IJA2AL8JAAC/CQAAA1FSu+QVe/ZcFDARAKSBAABmYXZpY29uLTMyeDMyLnBuZwDw4WlUiVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAABGdBTUEAALGPC/xhBQAAACBjSFJNAAB6JgAAgIQAAPoAAACA6AAAdTAAAOpgAAA6mAAAF3CculE8AAAARGVYSWZNTQAqAAAACAABh2kABAAAAAEAAAAaAAAAAAADoAEAAwAAAAEAAQAAoAIABAAAAAEAAAAgoAMABAAAAAEAAAAgAAAAAKyGYvMAAAHNaVRYdFhNTDpjb20uYWRvYmUueG1wAAAAAAA8eDp4bXBtZXRhIHhtbG5zOng9ImFkb2JlOm5zOm1ldGEvIiB4OnhtcHRrPSJYTVAgQ29yZSA2LjAuMCI+CiAgIDxyZGY6UkRGIHhtbG5zOnJkZj0iaHR0cDovL3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyI+CiAgICAgIDxyZGY6RGVzY3JpcHRpb24gcmRmOmFib3V0PSIiCiAgICAgICAgICAgIHhtbG5zOmV4aWY9Imh0dHA6Ly9ucy5hZG9iZS5jb20vZXhpZi8xLjAvIj4KICAgICAgICAgPGV4aWY6Q29sb3JTcGFjZT4xPC9leGlmOkNvbG9yU3BhY2U+CiAgICAgICAgIDxleGlmOlBpeGVsWERpbWVuc2lvbj4xMDI0PC9leGlmOlBpeGVsWERpbWVuc2lvbj4KICAgICAgICAgPGV4aWY6UGl4ZWxZRGltZW5zaW9uPjEwMjQ8L2V4aWY6UGl4ZWxZRGltZW5zaW9uPgogICAgICA8L3JkZjpEZXNjcmlwdGlvbj4KICAgPC9yZGY6UkRGPgo8L3g6eG1wbWV0YT4Kwe07qQAAByFJREFUSA2NVltvG8cV3pnZO2+WKFE3kpKsWgYpyVFqpw1guJc4Qd30pbmgCNIXA7299bFA/0B/RVvDDwEKuEHrFFWbGnELtE0DFI0rJHZ8k2hJlinKEi2Su+Tuzs5Mz+ySlGTLQAfE7uzMme+c853LEIVOTUHKkQOWxVEbz1uPZePdrowQ6j4CgB0++hQ6QqhrCmyI3iYcgdH76k5RfwH1FMQSB+Sic/KBCVFUNeSC+n5IKUCruq4ZhoqREoacsb7k/mQfJ/Zg/3tfJoJWQ4x3Hm40P/s0XLmFHm/hjiuNNxN8eJR8qZxZOJ3NFwhnR6uJwJCMwTMD/Ea6UVtf2126Yi3/K9Vu6hghjBVgCYYQgvOAi6ad9hbPDn3n7Vy+yAP/GRgpeoQC4JqrauUvf0Tv/2rYd0ATj3CBdgkfkx6BYakn2DHTyvd+NPXKBRwG/dD0lAncm3XfAMUIuf2by7v/uB7MvtjUbYV3WZZaInT5jlnl3FUNOnmy/uHVe++/x4gWe3gAUwYZZA9YpRn3r15JfHBZ+/5PR+fntypn3T+8N7KzHjmBCMGBQAEAcK5zVh+ZQq+/k5ueFNeW0r/75YqdnH39u8ohrg6mqaIQXVtb/tT84PKArj5qPCEsLMye2P3Jz29/9CfVsolhbqw94JnBydIcg4za2Trxyrcs2uo4LbH9KKNrwe8vbU4eL5TnGSRbjxHwoGs+UO+4HefKrwuCCkLQxmrw0ldNpKYTePbdH+qJ5PLysmMO2Ka5GYjFxa8U8uPe1jp44lGub29yVcuG3sZvL7k/+4WlEsiDWMV+DLCuVz/5e3b9jlA1SBhvZztMZLnXUhnlbady9+5GpVKambnw2quT+fyNG/+p16oSgtE2Np1OB4oQDg6u3tz698dY07oOKP0gI6XjB8E/r9lExg+ccgLq01AEnpoeGBovUErPnT17amHe0o35cnnx1CnNSugDOZJIW4kkNyxFcDhoE8X/+CM/ZD1elK4HUK7N6qb9cEVRNRl1xsJ01hrIasWSdiwnFPHCqYWxsVGMMeccrCsWCkk7oWBVG5qYmC3xN36wyTCBrCeauX63uVXF8BWNrgKEibtWsTwXTkN239PSw29dzA5mdSsJsQEc1TAwwr0WJPlFqiq7iBCIsdK587vllwPwGCGr3XIfPoCEixV0e5FAmNYeRcYjHgadk+Xpk2VZAUhxXffO3WVKycJc2U6kIHoQoQeVB6uV29nBgfmFM0BOwjJTZ861b3+SUYQmWKtWBU1SAepRBCSIdgvaFxJ818rk3744kElBnYIMUdVa9YsP/3zp+vWrIWOI4Hq9vrR0+fPPrhkGIUSaKFhYOv/ttRdfDQJKAMNtSR/lRr+bwkekEyhrKCQhkCJjBhLCNI1vfPOd02fO+x40NQqdVdfUN9+4aBh6+thI3ObAFE1FqZfObf/3b+PU7bYseV7pUgT+4GQaMDuMuXNfLh2fAaOAfcaYCEPTtO3EcVDGqC/CwLasVBrIUEIaKBhCg2HCGB2fLVUzWbHdAigAjJ3oBVkIbWQCIEOiDZQWWACKwsD3Wo06/JzmExZSoLW+tvrwr0tuowGHvY7bbNTdVgPQwQ+oZ8DkY1O+ULSRcdQrtF6QGUtMHm9bqSAIHKJqmuY090LqK2AewmEY+n7HQCg1UXR8P5UdpiAX9RxK/eBJxzBtoGXn3hfkzo1OZihVnAYCIoZ6QQYTMqNjnelSQuHjxSnITCAEnJSeyu4fNp/s1DahMfBscdpt7T2ubgReGzZAxjAtHX52cuPW54O07c/MpYdzcAkdUgAfhkqsr19oCbR66yYmMsdNOwmKOQ/BJYmiqe3WHvPb8LRtWzdMiK2ENixNN6DENOrvMcX+2gW4nWJ0eHYpghmjwejpl29Ol4cVCpVlJzNe24HzUJNWIgUCYD4NPM7gGiUAatiJttOU+RP1CdCXpe1g7szo4ukD3fSAAnDWVPHIuz+uVmtQzAJgVOg3KYh2VPfxgqxFYEaSoyimlZCJJNlUhN8OTryQny5qGEX1A/swnrkyoazW1jcgOSenZkBDDBTLPvcJuUf9tdX7hmUV8mMcOl1/9Cu5v8LCsJifgNKsVFaCwIvW9wnti8EEvKDSfLjBOpWV+6pKCuOjh9BhD/rKkf8qMMG17cfb2zu53MjIWD5mSXah3p0LaRaG0NA7jtuuVTdzueFcbqifOQfseI4CkAAdnudvPqpSyizLTKczMpF0ExIGyttp7TX26q1m07TMifFRA/55HCD+/1IAQrJRY9zxvL29huM4stNB/pg2h6pmNJlMHjuWsUwToME5oCPCfZrPoyk6YELUcqGcFcgN4AAqC9IJikTeupCjMWpP/lkdh/9V9OQOvwXcC72yhBhEYQCWDgvFX0+bD6uqTOL+OkzACPkZL0UWdc2KViQVsVD87s2P0iZNEeJ/vtGhNdx2DQYAAAAASUVORK5CYILEPXsAQAcA"""
_RAR5_COMIC = """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"""


def _write_archive(tmp_path: Path, name: str, encoded: str) -> Path:
    archive = tmp_path / name
    archive.write_bytes(base64.b64decode(encoded))
    return archive


def _tiny_png() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def test_unknown_page_extension_is_left_for_the_decoder(tmp_path: Path) -> None:
    archive = tmp_path / "unknown-extension.cbz"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        output.writestr("001.page", _tiny_png())

    parsed = inspect_comic_archive(archive)

    assert parsed["pageCount"] == 1
    assert parsed["pages"][0]["entryPath"] == "001.page"
    assert parsed["pages"][0]["mediaType"] == "application/octet-stream"


@pytest.mark.parametrize("extension", ["zip", "cbz"])
def test_comic_text_attachments_are_not_pages(tmp_path: Path, extension: str) -> None:
    archive = tmp_path / f"attachments.{extension}"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("001.png", _tiny_png())
        output.writestr("002.page", _tiny_png())
        output.writestr("README.txt", "This is a comic attachment, not a page.")
        output.writestr("extras/NOTES.TXT", "Nested text attachment.")
    original = archive.read_bytes()

    parsed = inspect_comic_archive(archive)

    assert parsed["pageCount"] == 2
    assert [page["entryPath"] for page in parsed["pages"]] == ["001.png", "002.page"]
    assert parsed["pages"][1]["mediaType"] == "application/octet-stream"
    assert archive.read_bytes() == original


def test_corrupt_optional_page_is_quarantined_when_another_page_is_readable(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "partial-corruption.cbz"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        output.writestr("001.png", _tiny_png())
        output.writestr("002.png", _tiny_png())

    with zipfile.ZipFile(archive) as source:
        bad_entry = source.getinfo("002.png")
    raw = bytearray(archive.read_bytes())
    header_offset = bad_entry.header_offset
    name_length, extra_length = struct.unpack(
        "<HH", raw[header_offset + 26 : header_offset + 30]
    )
    payload_offset = header_offset + 30 + name_length + extra_length
    raw[payload_offset] ^= 0x01
    archive.write_bytes(raw)

    parsed = inspect_comic_archive(archive)

    assert parsed["pageCount"] == 1
    assert [page["entryPath"] for page in parsed["pages"]] == ["001.png"]


class _FakeRarInfo:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.file_size = len(content)
        self.CRC = 0
        self.flag_bits = 0
        self.external_attr = 0
        self.compress_size = len(content)
        self._content = content

    def is_dir(self) -> bool:
        return False


class _FakeRarFile:
    def __init__(self, _path: Path) -> None:
        self._entries = {
            name: _FakeRarInfo(name, content)
            for name, content in {
                "favicon-16x16.png": b"png-16",
                "favicon-32x32.png": b"png-32",
            }.items()
        }

    def needs_password(self) -> bool:
        return False

    def volumelist(self) -> list[str]:
        return ["sample.rar"]

    def infolist(self) -> list[_FakeRarInfo]:
        return list(self._entries.values())

    def getinfo(self, name: str) -> _FakeRarInfo:
        return self._entries[name]

    def open(self, name: str, _mode: str = "r") -> BytesIO:
        return BytesIO(self._entries[name]._content)

    def testrar(self) -> None:
        return None

    def close(self) -> None:
        return None


def _patch_rar_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rarfile, "RarFile", _FakeRarFile)
    monkeypatch.setattr(rarfile, "tool_setup", lambda: None)


@pytest.mark.parametrize(
    ("name", "encoded", "expected_format"),
    [
        ("sample.cbr", _RAR4_COMIC, "cbr"),
        ("sample.rar", _RAR5_COMIC, "rar"),
    ],
)
def test_parse_comic_archive_reuses_existing_pipeline_for_rar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    encoded: str,
    expected_format: str,
) -> None:
    archive = _write_archive(tmp_path, name, encoded)
    _patch_rar_backend(monkeypatch)

    parsed = inspect_comic_archive(archive)

    assert parsed["format"] == expected_format
    assert parsed["pageCount"] == 2
    assert [page["entryPath"] for page in parsed["pages"]] == [
        "favicon-16x16.png",
        "favicon-32x32.png",
    ]
    assert parsed["coverEntryPath"] == "favicon-16x16.png"


@pytest.mark.parametrize(
    ("volume_tag", "number_tag", "expected"),
    [
        ("<Volume>1 of 23</Volume>", "", 1),
        ("<Volume>第 2 卷</Volume>", "", 2),
        ("<Volume>无效</Volume>", "<Number>Vol. 3</Number>", 3),
    ],
)
def test_comic_info_accepts_decorated_current_volume_numbers(
    tmp_path: Path,
    volume_tag: str,
    number_tag: str,
    expected: float,
) -> None:
    archive = tmp_path / "comic.cbz"
    image = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("001.png", image)
        output.writestr(
            "ComicInfo.xml",
            f"<ComicInfo><Series>作品</Series>{volume_tag}{number_tag}</ComicInfo>",
        )

    parsed = inspect_comic_archive(archive)

    assert parsed["comicInfo"] is not None
    assert parsed["comicInfo"]["volume"] == expected


def test_rar_page_stream_reuses_existing_original_range_and_data_saver_paths(
    tmp_path: Path,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = _write_archive(tmp_path, "sample.cbr", _RAR4_COMIC)
    _patch_rar_backend(monkeypatch)
    with open_comic_archive(archive_path) as archive:
        expected = archive.read("favicon-32x32.png")
    app = FastAPI()

    @app.get("/page")
    def page(request: Request):
        return http_streaming.send_comic_page_zip_entry(
            archive_path,
            "favicon-32x32.png",
            request,
            "reader-1",
            test_settings,
            "image/png",
        )

    with TestClient(app) as client:
        original = client.get("/page?imageVariant=original")
        ranged = client.get(
            "/page?imageVariant=original", headers={"Range": "bytes=1-4"}
        )
        data_saver = client.get("/page?imageVariant=data-saver")

    assert original.status_code == 200
    assert original.content == expected
    assert original.headers["x-comic-image-variant"] == "original"
    assert ranged.status_code == 206
    assert ranged.content == expected[1:5]
    assert ranged.headers["content-range"] == f"bytes 1-4/{len(expected)}"
    assert data_saver.status_code == 200
    assert data_saver.headers["x-comic-image-variant"] in {"original", "data-saver"}


def test_open_comic_archive_reports_missing_rar_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = _write_archive(tmp_path, "sample.rar", _RAR5_COMIC)

    def missing_backend(*_args: object, **_kwargs: object) -> object:
        raise rarfile.RarCannotExec("missing")

    monkeypatch.setattr(rarfile, "tool_setup", missing_backend)

    with pytest.raises(ComicArchiveBackendUnavailableError):
        open_comic_archive(archive)


def test_open_comic_archive_rejects_invalid_rar(tmp_path: Path) -> None:
    archive = tmp_path / "broken.cbr"
    archive.write_bytes(b"not a rar archive")

    with pytest.raises(ComicArchiveInvalidError):
        open_comic_archive(archive)


@pytest.mark.parametrize(
    "entries",
    [
        [("../escape.png", b"image")],
        [("folder/../page.png", b"image"), ("page.png", b"image")],
    ],
)
def test_cbz_inspection_reports_missing_or_conflicting_required_pages_as_integrity(
    tmp_path: Path,
    entries: list[tuple[str, bytes]],
) -> None:
    archive = tmp_path / "unsafe.cbz"
    with zipfile.ZipFile(archive, "w") as output:
        for name, content in entries:
            output.writestr(name, content)

    with pytest.raises(ComicArchiveInvalidError) as raised:
        inspect_comic_archive(archive)
    assert raised.value.rule_id == ReaderSafetyRuleId.COMIC_RESOURCE_INTEGRITY.value
    assert raised.value.code == "COMIC_RESOURCE_CORRUPT"


def test_cbz_keeps_mixed_unknown_extensions_and_case_distinct_pages(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "mixed.cbz"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("Page.PNG", b"first-page")
        output.writestr("page.png", b"second-page")
        output.writestr("third.future-image", b"third-page")
    original = archive.read_bytes()

    parsed = inspect_comic_archive(archive)

    assert {page["entryPath"] for page in parsed["pages"]} == {
        "Page.PNG",
        "page.png",
        "third.future-image",
    }
    assert archive.read_bytes() == original


def test_cbz_isolates_unused_escapes_and_links_and_normalizes_ordinary_paths(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "quarantined.cbz"
    linked = zipfile.ZipInfo("linked.png")
    linked.create_system = 3
    linked.external_attr = 0o120777 << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("pages/./part/../one.future", b"readable-one")
        output.writestr("pages\\two.future", b"readable-two")
        output.writestr("../outside.png", b"unaddressable")
        output.writestr(linked, b"/private/path")

    parsed = inspect_comic_archive(archive)

    assert {page["entryPath"].replace("\\", "/") for page in parsed["pages"]} == {
        "pages/./part/../one.future",
        "pages/two.future",
    }
    assert not (tmp_path / "outside.png").exists()


def test_cbz_page_budget_is_checked_before_resource_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "page-budget.cbz"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("readable.future", b"okay")
        output.writestr("oversized.future", b"too-large")
    original_budget = comic_archives_module.reader_safety_budget
    original_read = comic_archives_module.ComicArchive.read
    reads: list[str] = []

    def budget(name: ReaderSafetyBudgetName) -> int:
        return (
            4
            if name is ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES
            else original_budget(name)
        )

    def read(
        container: comic_archives_module.ComicArchive,
        entry: str | comic_archives_module.ComicArchiveEntry,
    ) -> bytes:
        reads.append(entry if isinstance(entry, str) else entry.filename)
        return original_read(container, entry)

    monkeypatch.setattr(comic_archives_module, "reader_safety_budget", budget)
    monkeypatch.setattr(comic_archives_module.ComicArchive, "read", read)
    parsed = inspect_comic_archive(archive)
    assert [page["entryPath"] for page in parsed["pages"]] == ["readable.future"]
    assert reads == ["readable.future"]


def test_comic_cover_page_budget_is_checked_before_archive_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = tmp_path / "cover-budget.cbz"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("cover.future", b"too-large")
    monkeypatch.setattr(comic_archives_module, "MAX_COMIC_PAGE_BYTES", 4)

    with pytest.raises(ComicArchiveInvalidError) as raised:
        extract_comic_cover(
            tmp_path / "storage",
            archive,
            "book-1",
            "resource-1",
            "asset-1",
            "cover.future",
        )

    assert raised.value.rule_id == ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES.value
    assert raised.value.code == "COMIC_PAGE_BLOCKED"
    assert not (
        tmp_path
        / "storage"
        / "books"
        / "book-1"
        / "resource-1"
        / "asset-1"
        / "cover.future"
    ).exists()


class _RejectedRarArchive:
    def __init__(self, *, password: bool, volumes: list[str]) -> None:
        self._password = password
        self._volumes = volumes

    def needs_password(self) -> bool:
        return self._password

    def volumelist(self) -> list[str]:
        return self._volumes

    def close(self) -> None:
        return None


@pytest.mark.parametrize(
    ("archive", "expected_error"),
    [
        (
            _RejectedRarArchive(password=True, volumes=["sample.rar"]),
            ComicArchiveEncryptedError,
        ),
        (
            _RejectedRarArchive(
                password=False,
                volumes=["sample.part1.rar", "sample.part2.rar"],
            ),
            ComicArchiveMultiVolumeError,
        ),
    ],
)
def test_open_comic_archive_rejects_unsupported_rar_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    archive: _RejectedRarArchive,
    expected_error: type[Exception],
) -> None:
    path = tmp_path / "sample.rar"
    path.touch()
    monkeypatch.setattr(rarfile, "RarFile", lambda _path: archive)

    with pytest.raises(expected_error):
        open_comic_archive(path)
