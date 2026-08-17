from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Literal, Self

import pytest

from app.modules.auth.application.first_admin import (
    BootstrapFirstAdministrator,
    FirstAdministratorRepository,
    FirstAdministratorUnitOfWork,
    NewAdministrator,
)
from app.modules.auth.domain.first_admin import (
    FIRST_ADMINISTRATOR_PASSWORD_MAX_LENGTH,
    FIRST_ADMINISTRATOR_PASSWORD_MIN_LENGTH,
    FirstAdministratorAlreadyInitialized,
    FirstAdministratorCommand,
    InvalidFirstAdministratorRequest,
)


@dataclass
class FakeRepository(FirstAdministratorRepository):
    users: bool = False
    marker: bool = False
    saved: NewAdministrator | None = None
    fail_on_save: bool = False

    def has_users(self) -> bool:
        return self.users

    def identity_bootstrap_completed(self) -> bool:
        return self.marker

    def add_first_administrator(self, administrator: NewAdministrator) -> None:
        if self.fail_on_save:
            raise RuntimeError("injected persistence failure")
        self.saved = administrator


class FakeUnitOfWork(FirstAdministratorUnitOfWork):
    def __init__(self, repository: FakeRepository) -> None:
        self.repository: FakeRepository = repository
        self.committed = False
        self.rolled_back = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if exception_type is None:
            self.committed = True
        else:
            self.rolled_back = True
        return False


class FixedHasher:
    def hash(self, password: str) -> str:
        return f"hash:{password}"


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


class FixedIds:
    def __init__(self) -> None:
        self._values = iter(("user-1", "identity-1"))

    def new_id(self) -> str:
        return next(self._values)


def build_use_case(
    repository: FakeRepository,
) -> tuple[BootstrapFirstAdministrator, FakeUnitOfWork]:
    unit_of_work = FakeUnitOfWork(repository)
    return (
        BootstrapFirstAdministrator(
            unit_of_work_factory=lambda: unit_of_work,
            password_hasher=FixedHasher(),
            clock=FixedClock(),
            id_generator=FixedIds(),
        ),
        unit_of_work,
    )


def test_first_admin_normalizes_email_and_writes_password_identity() -> None:
    repository = FakeRepository()
    use_case, unit_of_work = build_use_case(repository)

    result = use_case.execute(
        FirstAdministratorCommand(
            email="  Admin@Example.COM ",
            display_name="  Administrator ",
            password="secret-pass",
        )
    )

    assert result.user_id == "user-1"
    assert result.identity_id == "identity-1"
    assert result.normalized_email == "admin@example.com"
    assert repository.saved is not None
    assert repository.saved.password_hash == "hash:secret-pass"
    assert unit_of_work.committed is True
    assert unit_of_work.rolled_back is False


@pytest.mark.parametrize(
    "password_length",
    [FIRST_ADMINISTRATOR_PASSWORD_MIN_LENGTH, FIRST_ADMINISTRATOR_PASSWORD_MAX_LENGTH],
)
def test_password_length_boundaries_are_accepted(password_length: int) -> None:
    repository = FakeRepository()
    use_case, unit_of_work = build_use_case(repository)

    use_case.execute(
        FirstAdministratorCommand(
            email="admin@example.com",
            display_name="Admin",
            password="x" * password_length,
        )
    )

    assert repository.saved is not None
    assert unit_of_work.committed is True


@pytest.mark.parametrize(
    ("repository", "expected_code"),
    [
        (
            FakeRepository(users=True),
            "FIRST_ADMINISTRATOR_ALREADY_INITIALIZED",
        ),
        (
            FakeRepository(marker=True),
            "FIRST_ADMINISTRATOR_ALREADY_INITIALIZED",
        ),
    ],
)
def test_existing_user_or_marker_is_a_stable_conflict(
    repository: FakeRepository, expected_code: str
) -> None:
    use_case, unit_of_work = build_use_case(repository)

    with pytest.raises(FirstAdministratorAlreadyInitialized) as raised:
        use_case.execute(
            FirstAdministratorCommand("admin@example.com", "Admin", "secret-pass")
        )

    assert raised.value.code == expected_code
    assert repository.saved is None
    assert unit_of_work.committed is False
    assert unit_of_work.rolled_back is True


def test_injected_write_failure_rolls_back_and_does_not_publish_result() -> None:
    repository = FakeRepository(fail_on_save=True)
    use_case, unit_of_work = build_use_case(repository)

    with pytest.raises(RuntimeError, match="injected persistence failure"):
        use_case.execute(
            FirstAdministratorCommand("admin@example.com", "Admin", "secret-pass")
        )

    assert repository.saved is None
    assert unit_of_work.committed is False
    assert unit_of_work.rolled_back is True


@pytest.mark.parametrize(
    ("command", "field"),
    [
        (FirstAdministratorCommand("not-an-email", "Admin", "secret-pass"), "email"),
        (
            FirstAdministratorCommand("admin@example.com", "", "secret-pass"),
            "display_name",
        ),
        (FirstAdministratorCommand("admin@example.com", "Admin", ""), "password"),
        (
            FirstAdministratorCommand(
                "admin@example.com",
                "Admin",
                "x" * (FIRST_ADMINISTRATOR_PASSWORD_MIN_LENGTH - 1),
            ),
            "password",
        ),
        (
            FirstAdministratorCommand(
                "admin@example.com",
                "Admin",
                "x" * (FIRST_ADMINISTRATOR_PASSWORD_MAX_LENGTH + 1),
            ),
            "password",
        ),
    ],
)
def test_first_admin_validates_request_before_opening_transaction(
    command: FirstAdministratorCommand, field: str
) -> None:
    repository = FakeRepository()
    use_case, unit_of_work = build_use_case(repository)

    with pytest.raises(InvalidFirstAdministratorRequest) as raised:
        use_case.execute(command)

    assert raised.value.field == field
    assert unit_of_work.committed is False
    assert unit_of_work.rolled_back is False
