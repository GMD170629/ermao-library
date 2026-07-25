from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


def migrate() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    config = Config(backend_root / "alembic-v2.ini")
    command.upgrade(config, "head")


def main() -> None:
    migrate()


if __name__ == "__main__":
    main()
