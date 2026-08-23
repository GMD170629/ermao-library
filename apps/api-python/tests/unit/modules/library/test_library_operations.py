from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.library.infrastructure.operations import operation_summary


def test_expired_completed_operation_is_not_advertised_as_undoable() -> None:
    summary = operation_summary(
        {
            "id": "op-expired",
            "action": "BULK_UPDATE_METADATA",
            "status": "COMPLETED",
            "summary": "expired",
            "expiresAt": datetime.now(UTC) - timedelta(seconds=1),
        }
    )

    assert summary.undo_available is False
