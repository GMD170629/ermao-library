"""Resolve the authenticated account's display image through one server owner."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AccountAvatar:
    uploaded_path: str | None


@dataclass(frozen=True)
class AvatarImageFile:
    path: str


class AvatarUnavailable(Exception):
    """The account or its required display asset is unavailable."""


class AccountAvatarRepository(Protocol):
    def find_for_actor(self, actor_id: str) -> AccountAvatar | None: ...


class AvatarImageStore(Protocol):
    def uploaded_image(self, relative_path: str) -> AvatarImageFile | None: ...

    def default_image(self) -> AvatarImageFile: ...


class GetAccountAvatar:
    def __init__(
        self, accounts: AccountAvatarRepository, images: AvatarImageStore
    ) -> None:
        self._accounts = accounts
        self._images = images

    def execute(self, *, actor_id: str) -> AvatarImageFile:
        account = self._accounts.find_for_actor(actor_id)
        if account is None:
            raise AvatarUnavailable
        if account.uploaded_path is not None:
            uploaded = self._images.uploaded_image(account.uploaded_path)
            if uploaded is not None:
                return uploaded
        return self._images.default_image()
