"""SQLAlchemy grant storage without transaction ownership or identity caches."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.automation.application.grants import AutomationGrant
from app.modules.automation.domain.access import (
    AutomationAccessError,
    GrantPermissions,
    Scope,
)
from app.modules.automation.infrastructure.models import AutomationGrantRow


# Storage reserves epoch 0 for explicitly non-expiring grants; public/domain values use None.
def _grant(row: AutomationGrantRow) -> AutomationGrant:
    if row.library_scope not in {"all", "selected"}:
        raise AutomationAccessError("INVALID_LIBRARY_SCOPE")
    return AutomationGrant(
        id=row.id,
        user_id=row.user_id,
        name=row.name,
        permissions=GrantPermissions(
            scopes=frozenset(Scope(value) for value in row.scopes),
            library_ids=frozenset(row.library_ids),
            library_scope="all" if row.library_scope == "all" else "selected",
        ),
        created_at_ms=row.created_at_ms,
        expires_at_ms=None if row.expires_at_ms == 0 else row.expires_at_ms,
        revoked_at_ms=row.revoked_at_ms,
        last_used_at_ms=row.last_used_at_ms,
        token_ciphertext=row.token_ciphertext,
    )


class SqlAlchemyGrantStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def has_secrets(self) -> bool:
        return (
            self._db.scalar(
                select(AutomationGrantRow.id)
                .where(AutomationGrantRow.token_ciphertext.is_not(None))
                .limit(1)
            )
            is not None
        )

    def add(self, grant: AutomationGrant, digest: str) -> None:
        self._db.add(
            AutomationGrantRow(
                id=grant.id,
                user_id=grant.user_id,
                name=grant.name,
                token_digest=digest,
                scopes=sorted(grant.permissions.scopes),
                library_ids=sorted(grant.permissions.library_ids),
                library_scope=grant.permissions.library_scope,
                token_ciphertext=grant.token_ciphertext,
                created_at_ms=grant.created_at_ms,
                expires_at_ms=0 if grant.expires_at_ms is None else grant.expires_at_ms,
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
            .values(revoked_at_ms=now_ms, token_ciphertext=None)
        )
        return True

    def update(self, grant: AutomationGrant, now_ms: int) -> bool:
        changed = self._db.execute(
            update(AutomationGrantRow)
            .where(
                AutomationGrantRow.id == grant.id,
                AutomationGrantRow.user_id == grant.user_id,
                AutomationGrantRow.revoked_at_ms.is_(None),
                (AutomationGrantRow.expires_at_ms == 0)
                | (AutomationGrantRow.expires_at_ms > now_ms),
            )
            .values(
                name=grant.name,
                scopes=sorted(grant.permissions.scopes),
                library_ids=sorted(grant.permissions.library_ids),
                library_scope=grant.permissions.library_scope,
                expires_at_ms=0 if grant.expires_at_ms is None else grant.expires_at_ms,
            )
            .returning(AutomationGrantRow.id)
        ).scalar_one_or_none()
        return changed is not None

    def record_use(self, grant_id: str, now_ms: int) -> None:
        self._db.execute(
            update(AutomationGrantRow)
            .where(
                AutomationGrantRow.id == grant_id,
                (AutomationGrantRow.last_used_at_ms.is_(None))
                | (AutomationGrantRow.last_used_at_ms < now_ms),
            )
            .values(last_used_at_ms=now_ms)
        )
