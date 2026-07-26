from __future__ import annotations

from pathlib import Path

from appv2.platform.config import get_settings
from appv2.platform.database.migrations import migrate as migrate_database


def migrate() -> None:
    settings = get_settings()
    backend_root = Path(__file__).resolve().parents[2]
    migrate_database(settings.database_dsn, backend_root)


def main() -> None:
    migrate()


if __name__ == "__main__":
    main()
