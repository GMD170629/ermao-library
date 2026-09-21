"""A claim and its completed result commit with the business mutation."""

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.modules.automation.domain.access import AutomationAccessError
from app.modules.automation.infrastructure.models import AutomationReceiptRow


class SqlAlchemyReceiptStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def claim(
        self,
        grant_id: str,
        request_id: str,
        tool: str,
        fingerprint: str,
        created_at_ms: int,
    ) -> dict[str, object] | None:
        inserted = self._db.scalar(
            insert(AutomationReceiptRow)
            .values(
                grant_id=grant_id,
                request_id=request_id,
                tool=tool,
                fingerprint=fingerprint,
                created_at_ms=created_at_ms,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    AutomationReceiptRow.grant_id,
                    AutomationReceiptRow.request_id,
                ]
            )
            .returning(AutomationReceiptRow.request_id)
        )
        if inserted is not None:
            return None
        row = self._db.scalar(
            select(AutomationReceiptRow).where(
                AutomationReceiptRow.grant_id == grant_id,
                AutomationReceiptRow.request_id == request_id,
            )
        )
        if row is None or row.fingerprint != fingerprint or row.tool != tool:
            raise AutomationAccessError("REQUEST_ID_CONFLICT")
        if row.result is None:
            raise AutomationAccessError("REQUEST_INCOMPLETE")
        return row.result

    def complete(
        self, grant_id: str, request_id: str, result: dict[str, object]
    ) -> None:
        self._db.execute(
            update(AutomationReceiptRow)
            .where(
                AutomationReceiptRow.grant_id == grant_id,
                AutomationReceiptRow.request_id == request_id,
            )
            .values(result=result)
        )
