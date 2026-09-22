"""Session release failures never replace the observed automation failure."""

import errno
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.settings import SystemEvent
from app.modules.automation.infrastructure.runtime import DatabaseAutomationRuntime


def test_runtime_close_failure_is_related_and_original_is_preserved(db_session, caplog):
    class BrokenBusinessClose(Session):
        def close(self):
            super().close()
            if not self.info.get("diagnostics_storage"):
                raise RuntimeError("injected business session close failure")

    factory = sessionmaker(bind=db_session.get_bind(), class_=BrokenBusinessClose)
    runtime = DatabaseAutomationRuntime(
        factory,
        settings=Mock(),
        authorize=Mock(),
        catalog=Mock(),
        maintenance=Mock(),
        usage=Mock(),
        writes=Mock(),
        files=Mock(),
        writebacks=Mock(),
        uploads=Mock(),
        system=Mock(),
        deletions=Mock(),
    )
    with pytest.raises(OSError, match="Input/output error"), runtime._session():
        raise OSError(errno.EIO, "Input/output error", "/private/library/book.epub")
    with Session(db_session.get_bind()) as db:
        events = db.scalars(
            select(SystemEvent).where(SystemEvent.source == "automation")
        ).all()
    assert len(events) == 2
    primary = next(
        event for event in events if event.action == "automation.invocation_failed"
    )
    secondary = next(
        event for event in events if event.action == "automation.session_close_failed"
    )
    assert primary.metadata_json["diagnostics"]["directException"]["errno"] == errno.EIO
    assert secondary.metadata_json["parentDiagnosticId"] == primary.id
    assert (
        secondary.metadata_json["diagnostics"]["directException"]["message"]
        == "injected business session close failure"
    )
    assert "Input/output error" in caplog.text
    assert "injected business session close failure" in caplog.text
    assert "/private/library" not in caplog.text
