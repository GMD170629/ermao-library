"""Typed persistence for metadata provider Source seed rows."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.sqlite.dml import Insert
from sqlalchemy.orm import Session

from app.core.sql_batches import sqlite_parameter_chunks
from app.models.common import db_timestamp
from app.models.import_pipeline import Source
from app.modules.metadata.domain.providers import ProviderManifest

METADATA_SOURCE_KIND = "metadata"


@dataclass(frozen=True, slots=True)
class BuiltinProviderSeedRow:
    provider_id: str
    name: str
    enabled: bool
    priority: int
    config_json: str
    capabilities_json: str


@dataclass(frozen=True, slots=True)
class PreparedMetadataSourceSeedWrite:
    source_statements: tuple[Insert, ...]


def prepare_builtin_provider_seed_rows(
    manifests: Iterable[ProviderManifest],
) -> tuple[BuiltinProviderSeedRow, ...]:
    """Purely serialize built-in manifests before bootstrap enters a transaction."""

    return tuple(
        BuiltinProviderSeedRow(
            provider_id=manifest.id,
            name=manifest.name,
            enabled=manifest.enabled_by_default,
            priority=manifest.default_priority,
            config_json=_json_text(
                {
                    field.key: field.default
                    for field in manifest.config_fields
                    if field.default is not None
                }
            ),
            capabilities_json=_json_text(list(manifest.capabilities)),
        )
        for manifest in manifests
    )


def write_builtin_provider_seed_rows(
    db: Session,
    rows: tuple[BuiltinProviderSeedRow, ...],
    *,
    now: datetime | None = None,
) -> None:
    prepared = prepare_metadata_source_seed_write(rows, now=now or db_timestamp())
    execute_metadata_source_seed_write(db, prepared)


def prepare_metadata_source_seed_write(
    rows: tuple[BuiltinProviderSeedRow, ...],
    *,
    now: datetime,
) -> PreparedMetadataSourceSeedWrite:
    """Build every SQL expression and bind chunk before the writer transaction."""

    source_rows = tuple(
        {
            "id": f"metadata-provider-{row.provider_id}",
            "name": row.name,
            "kind": METADATA_SOURCE_KIND,
            "provider_type": row.provider_id,
            "enabled": row.enabled,
            "priority": row.priority,
            "config": row.config_json,
            "capabilities": row.capabilities_json,
            "rate_limit": "{}",
            "created_at": now,
            "updated_at": now,
        }
        for row in rows
    )
    source_statements = tuple(
        (
            sqlite_insert(Source)
            .values(list(chunk))
            .on_conflict_do_nothing(index_elements=[Source.id])
        )
        for chunk in sqlite_parameter_chunks(source_rows, parameters_per_row=11)
    )
    return PreparedMetadataSourceSeedWrite(
        source_statements=source_statements,
    )


def execute_metadata_source_seed_write(
    db: Session, prepared: PreparedMetadataSourceSeedWrite
) -> None:
    """Execute only prebuilt expressions inside the bootstrap transaction."""

    for statement in prepared.source_statements:
        db.execute(statement)


prepare_metadata_source_seed_rows = prepare_builtin_provider_seed_rows
write_metadata_source_seed_rows = write_builtin_provider_seed_rows


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
