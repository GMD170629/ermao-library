"""Bounded retry support for transient SQLite write contention."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Generic, Protocol, Self, TypeVar

from sqlalchemy.exc import OperationalError

from app.core.database_errors import is_database_busy_error

ResultT = TypeVar("ResultT")
SessionT = TypeVar("SessionT", bound="RetrySession")

class RetrySession(Protocol):
    """Minimum session lifecycle required by the retry boundary."""

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

    def rollback(self) -> None: ...


@dataclass(frozen=True)
class SqliteRetryResult(Generic[ResultT]):
    """Result of a retryable operation, including shutdown cancellation."""

    completed: bool
    value: ResultT | None = None


def execute_with_sqlite_busy_retry(
    session_factory: Callable[[], SessionT],
    operation: Callable[[SessionT], ResultT],
    *,
    retry_delays_seconds: tuple[float, ...],
    stop_wait: Callable[[float], bool],
) -> SqliteRetryResult[ResultT]:
    """Run an operation in fresh sessions and retry transient SQLite locks.

    A failed session is rolled back and closed before waiting. Returning
    ``completed=False`` means shutdown interrupted the retry delay.
    """

    for attempt in range(len(retry_delays_seconds) + 1):
        if attempt and stop_wait(retry_delays_seconds[attempt - 1]):
            return SqliteRetryResult(completed=False)
        with session_factory() as db:
            try:
                return SqliteRetryResult(completed=True, value=operation(db))
            except OperationalError as error:
                db.rollback()
                if not is_database_busy_error(error) or attempt == len(
                    retry_delays_seconds
                ):
                    raise
            except Exception:
                db.rollback()
                raise
    raise AssertionError("SQLite retry loop exhausted without returning or raising")
