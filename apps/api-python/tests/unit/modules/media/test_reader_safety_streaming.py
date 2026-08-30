from __future__ import annotations

import json
from pathlib import Path

from fastapi import Request

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
)
from app.core.config import Settings
from app.modules.media.infrastructure.http_streaming import (
    send_comic_page_file,
    send_file,
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
    return json.loads(response.body)


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
        payload = _error_payload(response)
        assert response.status_code == status_code
        assert payload["error"]["code"] == "PDF_RANGE_INVALID"
        assert payload["error"]["params"]["ruleId"] == (
            ReaderSafetyRuleId.PDF_RANGE_PROTOCOL.value
        )


def test_comic_page_mime_and_size_fail_closed_from_generated_policy(
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

    wrong_mime_payload = _error_payload(wrong_mime)
    too_large_payload = _error_payload(too_large)
    assert wrong_mime.status_code == 422
    assert wrong_mime_payload["error"]["params"]["ruleId"] == (
        ReaderSafetyRuleId.COMIC_PAGE_MIME.value
    )
    assert too_large.status_code == 413
    assert too_large_payload["error"]["params"]["ruleId"] == (
        ReaderSafetyRuleId.COMIC_PAGE_MAX_BYTES.value
    )
