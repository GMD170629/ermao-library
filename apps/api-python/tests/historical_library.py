"""Seed migration fixtures against the schema that actually exists at that revision."""

from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session


def insert_historical_library(
    db: Session, *, root_path: Path, library_id: str = "library",
    name: str = "Library", min_file_size_bytes: int = 10240,
) -> sa.Table:
    table = sa.Table("Library", sa.MetaData(), autoload_with=db.connection())
    now = int(datetime.now(UTC).timestamp() * 1000)
    db.execute(table.insert().values(
        id=library_id, name=name, rootPath=str(root_path), organizationMode="FLAT",
        minFileSizeBytes=min_file_size_bytes,
        createdAt=now, updatedAt=now,
    ))
    return table
