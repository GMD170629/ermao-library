"""Pure domain values and errors for first-administrator bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

FIRST_ADMINISTRATOR_ALREADY_INITIALIZED = "FIRST_ADMINISTRATOR_ALREADY_INITIALIZED"
INVALID_FIRST_ADMINISTRATOR_REQUEST = "INVALID_FIRST_ADMINISTRATOR_REQUEST"
FIRST_ADMINISTRATOR_PASSWORD_MIN_LENGTH = 10
FIRST_ADMINISTRATOR_PASSWORD_MAX_LENGTH = 128


class FirstAdministratorError(RuntimeError):
    """Base error with a stable, locale-neutral application code."""

    code: str


class FirstAdministratorAlreadyInitialized(FirstAdministratorError):
    code = FIRST_ADMINISTRATOR_ALREADY_INITIALIZED

    def __init__(self) -> None:
        super().__init__(self.code)


class InvalidFirstAdministratorRequest(FirstAdministratorError):
    code = INVALID_FIRST_ADMINISTRATOR_REQUEST

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"{self.code}:{field}")


@dataclass(frozen=True, slots=True)
class FirstAdministratorCommand:
    email: str
    display_name: str
    password: str


@dataclass(frozen=True, slots=True)
class FirstAdministratorRecord:
    user_id: str
    identity_id: str
    normalized_email: str
    display_name: str
    created_at: datetime
