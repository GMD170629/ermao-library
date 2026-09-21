"""SQLAlchemy grant storage without transaction ownership or identity caches."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.automation.application.grants import AutomationGrant
from app.modules.automation.domain.access import (
    GrantPermissions,
    Scope,
    WritebackTarget,
)
from app.modules.automation.infrastructure.models import AutomationGrantRow


def _grant(row: AutomationGrantRow) -> AutomationGrant:
    return AutomationGrant(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        permissions=GrantPermissions(
            scopes=frozenset(Scope(value) for value in row.scopes),
            library_ids=frozenset(row.library_ids),
            writeback_targets=frozenset(
                WritebackTarget(v) for v in row.writeback_targets
            ),
            allow_cross_library=row.allow_cross_library,
        ),
        created_at_ms=row.created_at_ms,
        expires_at_ms=row.expires_at_ms,
        revoked_at_ms=row.revoked_at_ms,
        last_used_at_ms=row.last_used_at_ms,
    )


class SqlAlchemyGrantStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, grant: AutomationGrant, digest: str) -> None:
        self._db.add(
            AutomationGrantRow(
                id=grant.id,
                user_id=grant.user_id,
                name=grant.name,
                token_digest=digest,
                scopes=sorted(grant.permissions.scopes),
                library_ids=sorted(grant.permissions.library_ids),
                writeback_targets=sorted(grant.permissions.writeback_targets),
                allow_cross_library=grant.permissions.allow_cross_library,
                created_at_ms=grant.created_at_ms,
                expires_at_ms=grant.expires_at_ms,
            )
        )

    def by_digest(self, digest: str) -> AutomationGrant | None:
        row = self._db.scalar(
            select(AutomationGrantRow)
            .where(AutomationGrantRow.token_digest == digest)
            .execution_options(populate_existing=True)
        )
        return _grant(row) if row is not None else None

    def by_id(self, grant_id: str) -> AutomationGrant | None:
        row = self._db.scalar(
            select(AutomationGrantRow)
            .where(AutomationGrantRow.id == grant_id)
            .execution_options(populate_existing=True)
        )
        return _grant(row) if row is not None else None

    def list_owned(self, user_id: str) -> tuple[AutomationGrant, ...]:
        rows = self._db.scalars(
            select(AutomationGrantRow)
            .where(AutomationGrantRow.user_id == user_id)
            .order_by(AutomationGrantRow.created_at_ms.desc(), AutomationGrantRow.id)
        )
        return tuple(_grant(row) for row in rows)

    def revoke(self, grant_id: str, user_id: str, now_ms: int) -> bool:
        # Repeated revocation succeeds without changing its first timestamp.
        row = self._db.scalar(
            select(AutomationGrantRow)
            .where(
                AutomationGrantRow.id == grant_id, AutomationGrantRow.user_id == user_id
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            return False
        self._db.execute(
            update(AutomationGrantRow)
            .where(
                AutomationGrantRow.id == grant_id,
                AutomationGrantRow.user_id == user_id,
                AutomationGrantRow.revoked_at_ms.is_(None),
            )
            .values(revoked_at_ms=now_ms)
        )
        return True
