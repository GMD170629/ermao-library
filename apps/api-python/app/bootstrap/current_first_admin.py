"""Explicit CLI for initializing the first current administrator.

This command is deliberately not wired into the production server process.
The current schema must already exist at the supplied database path.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.db.current.engine import canonical_database_path, create_current_engine
from app.db.current.lock import schema_lock
from app.modules.auth.application.first_admin import (
    BootstrapFirstAdministrator,
    Clock,
    IdGenerator,
)
from app.modules.auth.domain.first_admin import (
    FirstAdministratorAlreadyInitialized,
    FirstAdministratorCommand,
    FirstAdministratorRecord,
)
from app.modules.auth.infrastructure.passwords import ScryptPasswordHasher
from app.modules.auth.infrastructure.persistence import (
    SqlAlchemyFirstAdministratorUnitOfWork,
)


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidGenerator(IdGenerator):
    def new_id(self) -> str:
        return f"current_{uuid4().hex}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create the first administrator.")
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    return parser


def bootstrap_first_administrator(
    database_path: Path, command: FirstAdministratorCommand
) -> FirstAdministratorRecord:
    """Run first-admin setup under the canonical current-database lock."""

    path = canonical_database_path(database_path)
    with schema_lock(path, timeout_seconds=10):
        engine = create_current_engine(path, timeout_seconds=10)
        try:
            use_case = BootstrapFirstAdministrator(
                unit_of_work_factory=lambda: SqlAlchemyFirstAdministratorUnitOfWork(
                    Session(engine)
                ),
                password_hasher=ScryptPasswordHasher(),
                clock=SystemClock(),
                id_generator=UuidGenerator(),
            )
            return use_case.execute(command)
        finally:
            engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    password = getpass("Administrator password: ")
    try:
        bootstrap_first_administrator(
            arguments.database,
            FirstAdministratorCommand(
                email=arguments.email,
                display_name=arguments.name,
                password=password,
            ),
        )
    except FirstAdministratorAlreadyInitialized as error:
        print(error.code, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
