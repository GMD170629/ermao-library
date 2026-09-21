"""Read current account state through the existing authorization owner."""

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, authorization_context
from app.models.auth import User
from app.modules.automation.public import AutomationActor


class SqlAlchemyAutomationIdentity:
    def __init__(
        self,
        db: Session,
        visible_library_ids: Callable[[AuthorizationContext], frozenset[str]],
    ) -> None:
        self._db = db
        self._visible_library_ids = visible_library_ids

    def current_actor(self, user_id: str) -> AutomationActor | None:
        user = self._db.scalar(
            select(User)
            .where(User.id == user_id)
            .execution_options(populate_existing=True)
        )
        if user is None:
            return None
        context = authorization_context(self._db, user)
        return AutomationActor(
            user_id=user.id,
            active=user.status == "active",
            can_manage_system=context.can_manage_system,
            library_ids=self._visible_library_ids(context),
            is_admin=context.is_admin,
        )
