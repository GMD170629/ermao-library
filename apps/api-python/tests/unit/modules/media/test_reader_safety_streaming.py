from __future__ import annotations

import json
from pathlib import Path
from typing import Self, cast

import pytest
from fastapi import Request

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
)
from app.core.config import Settings
from app.infrastructure.comic_archives import ComicArchiveInvalidError
from app.modules.media.infrastructure import http_streaming
from app.modules.media.infrastructure.http_streaming import (
    send_comic_page_file,
    send_file,
    send_pse_page_zip_entry,
)


def _request(
    method: str = "HEAD",
    headers: tuple[tuple[bytes, bytes], ...] = (),
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/assets/asset-pdf",
            "headers": list(headers),
            "query_string": b"",
        }
    )


def _error_payload(response) -> dict[str, object]:
    return cast(dict[str, object], json.loads(response.body))


def _error_details(response) -> dict[str, object]:
    return cast(dict[str, object], _error_payload(response)["error"])


def _error_params(response) -> dict[str, object]:
    return cast(dict[str, object], _error_details(response)["params"])


def test_pdf_probe_publishes_strong_revision(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.7\nfixture")

    response = send_file(
        source,
        _request(),
        "user-1",
        media_type="application/pdf",
        asset_id="asset-pdf",
    )

    assert response.status_code == 200
    assert response.headers["etag"].startswith('"')
    assert not response.headers["etag"].startswith("W/")
    assert response.headers["accept-ranges"] == "bytes"


def test_pdf_range_requires_matching_strong_revision(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.7\nfixture")
    probe = send_file(
        source,
        _request(),
        "user-1",
        media_type="application/pdf",
        asset_id="asset-pdf",
    )

    response = send_file(
        source,
        _request(
            headers=(
                (b"range", b"bytes=0-3"),
                (b"if-range", probe.headers["etag"].encode()),
            )
        ),
        "user-1",
        media_type="application/pdf",
        asset_id="asset-pdf",
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-3/{source.stat().st_size}"


def test_pdf_range_rejects_missing_revision_and_oversized_request(
    tmp_path: Path,
) -> None:
    maximum = reader_safety_budget(ReaderSafetyBudgetName.PDF_RANGE_REQUEST_MAX_BYTES)
    source = tmp_path / "book.pdf"
    with source.open("wb") as handle:
        handle.truncate(maximum + 2)

    missing_revision = send_file(
        source,
        _request(headers=((b"range", b"bytes=0-3"),)),
        "user-1",
        media_type="application/pdf",
        asset_id="asset-pdf",
    )
    probe = send_file(
        source,
        _request(),
        "user-1",
        media_type="application/pdf",
        asset_id="asset-pdf",
    )
    oversized = send_file(
        source,
        _request(
            headers=(
                (b"range", f"bytes=0-{maximum}".encode()),
                (b"if-range", probe.headers["etag"].encode()),
            )
        ),
        "user-1",
        media_type="application/pdf",
        asset_id="asset-pdf",
    )

    for response, status_code in ((missing_revision, 412), (oversized, 416)):
        assert response.status_code == status_code
        assert _error_details(response)["code"] == "PDF_RANGE_INVALID"
        assert _error_params(response)["ruleId"] == (
            ReaderSafetyRuleId.PDF_RANGE_PROTOCOL.value
        )


def test_comic_page_size_limit_is_enforced_without_mime_admission(
    tmp_path: Path,
    test_settings: Settings,
) -> None:
    unsupported = tmp_path / "page.avif"
    unsupported.write_bytes(b"not-an-allowed-page")
    wrong_mime = send_comic_page_file(
        unsupported,
        _request(),
        "user-1",
        test_settings,
        media_type="image/avif",
    )

    oversized = tmp_path / "page.png"
    with oversized.open("wb") as handle:
        handle.truncate(
            reader_safety_budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES) + 1
        )
    too_large = send_comic_page_file(
        oversized,
        _request(),
        "user-1",
        test_settings,
        media_type="image/png",
    )

    assert wrong_mime.status_code == 200
    assert wrong_mime.headers["content-type"] == "image/avif"
    assert too_large.status_code == 413
    assert _error_params(too_large)["ruleId"] == (
        ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES.value
    )


class _FakeArchiveEntry:
    file_size = reader_safety_budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_BYTES) + 1
    checksum = 0


class _UnreadableArchive:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getinfo(self, _entry_name: str) -> _FakeArchiveEntry:
        return _FakeArchiveEntry()

    def read(self, _entry_name: str) -> bytes:
        raise AssertionError("the page body must not be read after the budget check")


def test_pse_comic_page_budget_is_checked_before_archive_read(
    tmp_path: Path,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "oversized.cbz"
    archive_path.write_bytes(b"archive")
    monkeypatch.setattr(
        http_streaming,
        "open_comic_archive",
        lambda _path: _UnreadableArchive(),
    )

    response = send_pse_page_zip_entry(
        archive_path,
        "page.future",
        _request(),
        "user-1",
        test_settings,
        max_width=None,
        asset_id="asset-1",
        output_media_type="image/future",
    )

    assert response.status_code == 413
    assert _error_params(response)["ruleId"] == (
        ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES.value
    )


class _CorruptArchive:
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getinfo(self, _entry_name: str) -> _FakeArchiveEntry:
        entry = _FakeArchiveEntry()
        entry.file_size = 1
        return entry

    def read(self, _entry_name: str) -> bytes:
        raise ComicArchiveInvalidError(
            "corrupt optional page",
            code="COMIC_RESOURCE_CORRUPT",
            rule_id="COMIC.RESOURCE_INTEGRITY",
        )


def test_pse_comic_page_preserves_generated_integrity_error(
    tmp_path: Path,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive_path = tmp_path / "corrupt.cbz"
    archive_path.write_bytes(b"archive")
    monkeypatch.setattr(
        http_streaming,
        "open_comic_archive",
        lambda _path: _CorruptArchive(),
    )

    response = send_pse_page_zip_entry(
        archive_path,
        "page.future",
        _request(),
        "user-1",
        test_settings,
        max_width=None,
        asset_id="asset-1",
    )

    assert response.status_code == 422
    assert _error_details(response)["code"] == "COMIC_RESOURCE_CORRUPT"
    assert _error_params(response)["ruleId"] == (
        ReaderSafetyRuleId.COMIC_RESOURCE_INTEGRITY.value
    )
