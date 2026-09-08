"""ORM lookup and bounded-root file resolution for account image delivery."""

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.auth import User
from app.modules.auth.application.avatar_delivery import (
    AccountAvatar,
    AvatarImageFile,
    AvatarUnavailable,
)


class SqlAlchemyAccountAvatarRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_for_actor(self, actor_id: str) -> AccountAvatar | None:
        user = self._session.scalars(
            select(User).where(User.id == actor_id)
        ).one_or_none()
        return AccountAvatar(user.avatar_path) if user is not None else None


class LocalAvatarImageStore:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()

    def uploaded_image(self, relative_path: str) -> AvatarImageFile | None:
        path = (self._storage_root / relative_path).resolve()
        if not path.is_relative_to(self._storage_root) or not path.is_file():
            return None
        return AvatarImageFile(str(path))

    def default_image(self) -> AvatarImageFile:
        path = Path(__file__).with_name("assets") / "default-account-avatar.webp"
        if not path.is_file():
            raise AvatarUnavailable
        return AvatarImageFile(str(path))
