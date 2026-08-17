"""Application use case for creating the first administrator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Literal, Protocol, Self

from app.modules.auth.domain.first_admin import (
    FIRST_ADMINISTRATOR_PASSWORD_MAX_LENGTH,
    FIRST_ADMINISTRATOR_PASSWORD_MIN_LENGTH,
    FirstAdministratorAlreadyInitialized,
    FirstAdministratorCommand,
    FirstAdministratorRecord,
    InvalidFirstAdministratorRequest,
)


@dataclass(frozen=True, slots=True)
class NewAdministrator:
    user_id: str
    identity_id: str
    normalized_email: str
    display_name: str
    password_hash: str
    created_at: datetime


class FirstAdministratorRepository(Protocol):
    def has_users(self) -> bool: ...

    def identity_bootstrap_completed(self) -> bool: ...

    def add_first_administrator(self, administrator: NewAdministrator) -> None: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class FirstAdministratorUnitOfWork(Protocol):
    repository: FirstAdministratorRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]: ...


@dataclass(frozen=True, slots=True)
class BootstrapFirstAdministrator:
    """Create User, PASSWORD identity, and the system marker atomically."""

    unit_of_work_factory: Callable[[], FirstAdministratorUnitOfWork]
    password_hasher: PasswordHasher
    clock: Clock
    id_generator: IdGenerator

    def execute(self, command: FirstAdministratorCommand) -> FirstAdministratorRecord:
        normalized_email = self._normalize_email(command.email)
        display_name = command.display_name.strip()
        if not display_name or len(display_name) > 191:
            raise InvalidFirstAdministratorRequest("display_name")
        if not (
            FIRST_ADMINISTRATOR_PASSWORD_MIN_LENGTH
            <= len(command.password)
            <= FIRST_ADMINISTRATOR_PASSWORD_MAX_LENGTH
        ):
            raise InvalidFirstAdministratorRequest("password")

        created_at = self.clock.now()
        administrator = NewAdministrator(
            user_id=self.id_generator.new_id(),
            identity_id=self.id_generator.new_id(),
            normalized_email=normalized_email,
            display_name=display_name,
            password_hash=self.password_hasher.hash(command.password),
            created_at=created_at,
        )
        with self.unit_of_work_factory() as unit_of_work:
            if (
                unit_of_work.repository.has_users()
                or unit_of_work.repository.identity_bootstrap_completed()
            ):
                raise FirstAdministratorAlreadyInitialized()
            unit_of_work.repository.add_first_administrator(administrator)

        return FirstAdministratorRecord(
            user_id=administrator.user_id,
            identity_id=administrator.identity_id,
            normalized_email=administrator.normalized_email,
            display_name=administrator.display_name,
            created_at=administrator.created_at,
        )

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().casefold()
        if len(normalized) > 191 or normalized.count("@") != 1:
            raise InvalidFirstAdministratorRequest("email")
        local, domain = normalized.split("@")
        if not local or not domain or domain.startswith(".") or domain.endswith("."):
            raise InvalidFirstAdministratorRequest("email")
        return normalized


__all__ = [
    "BootstrapFirstAdministrator",
    "Clock",
    "FirstAdministratorRepository",
    "FirstAdministratorUnitOfWork",
    "IdGenerator",
    "NewAdministrator",
    "PasswordHasher",
]
