from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest
from app.modules.reader.presentation.v5_schemas import ReaderV5ProgressSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api-python"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from python_reader_position_acceptance_smoke import (
    CheckRecord,
    RequestBudget,
    _build_pos_coverage,
    _require_snapshot,
    position_payload,
)


def test_position_payload_keeps_locator_and_presentation_complete() -> None:
    payload = position_payload(
        "00000000-0000-4000-8000-000000000001",
        client_id="test-client",
        display_percent=42,
        captured_at_epoch_millis=1234,
        href="chapter.xhtml#anchor",
    )

    assert payload.schema_version == 5
    position = payload.position
    assert position.locator == {
        "href": "chapter.xhtml#anchor",
        "locations": {"totalProgression": 0.42},
    }
    assert position.presentation.display_percent == 42
    assert position.presentation.current_href == "chapter.xhtml#anchor"


def test_require_snapshot_rejects_wrong_revision_or_mutation() -> None:
    payload = position_payload(
        "00000000-0000-4000-8000-000000000001",
        client_id="test-client",
        display_percent=42,
        captured_at_epoch_millis=1234,
        href="chapter.xhtml#anchor",
    )
    snapshot = ReaderV5ProgressSnapshot(
        schemaVersion=5,
        revision=2,
        clientId="test-client",
        mutationId="00000000-0000-4000-8000-000000000001",
        capturedAtEpochMillis=1234,
        receivedAtEpochMillis=1235,
        position=payload.position,
    )

    assert (
        _require_snapshot(
            snapshot,
            mutation_id="00000000-0000-4000-8000-000000000001",
            revision=2,
        )
        is snapshot
    )
    with pytest.raises(AssertionError) as mutation_error:
        _require_snapshot(snapshot, mutation_id="other", revision=2)
    assert "chapter.xhtml#anchor" not in str(mutation_error.value)
    assert "mutationId" in str(mutation_error.value)
    with pytest.raises(AssertionError):
        _require_snapshot(
            snapshot,
            mutation_id="00000000-0000-4000-8000-000000000001",
            revision=3,
        )


def test_native_httpx_client_enforces_request_budget_with_event_hook() -> None:
    budget = RequestBudget(max_requests=1)
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"ok": True, "data": {}})
    )
    with httpx.Client(
        base_url="http://position.test",
        event_hooks={"request": [budget.on_request]},
        transport=transport,
    ) as client:
        assert client.get("/health").status_code == 200
        with pytest.raises(RuntimeError, match="exceeded 1 requests"):
            client.get("/health")
    assert budget.request_count == 2


def test_pos_coverage_always_reports_all_release_position_cases() -> None:
    checks: list[CheckRecord] = [
        {
            "id": "check-05",
            "pos": ["POS-05"],
            "status": "PASS",
            "details": {},
        }
    ]
    coverage = _build_pos_coverage(checks)

    assert list(coverage) == [f"POS-{index:02d}" for index in range(1, 12)]
    assert coverage["POS-05"]["evidenceChecks"] == ["check-05"]
    assert coverage["POS-09"]["status"] == "NOT_COVERED"
