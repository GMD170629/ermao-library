"""Compose feedback diagnostics with the library's book title query."""

from sqlalchemy.orm import Session

from app.modules.feedback.infrastructure import DatabaseFeedbackDiagnostics
from app.modules.system.infrastructure.events import feedback_event_bundle


def build_feedback_diagnostics(db: Session) -> DatabaseFeedbackDiagnostics:
    return DatabaseFeedbackDiagnostics(db, feedback_event_bundle)
