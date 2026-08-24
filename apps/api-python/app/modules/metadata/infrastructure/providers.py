"""ORM persistence for the global metadata provider order."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.models.import_pipeline import Source
from app.modules.metadata.infrastructure.sources import METADATA_SOURCE_KIND


@dataclass(frozen=True, slots=True)
class PreparedMetadataProviderWrite:
    statements: tuple[Executable, ...]


def prepare_provider_order_write(
    *,
    rows: tuple[dict[str, object], ...],
    now: datetime,
) -> PreparedMetadataProviderWrite:
    """Prepare a complete global provider order update."""

    statements = tuple(
        update(Source)
        .where(
            Source.kind == METADATA_SOURCE_KIND,
            Source.provider_type == str(row["provider_id"]),
        )
        .values(
            enabled=bool(row["enabled"]),
            priority=int(str(row["priority"])),
            updated_at=now,
        )
        for row in rows
    )
    return PreparedMetadataProviderWrite(statements)


def prepare_provider_update_write(
    *,
    source_id: str,
    config_json: str,
    now: datetime,
) -> PreparedMetadataProviderWrite:
    return PreparedMetadataProviderWrite(
        (
            update(Source)
            .where(Source.id == source_id)
            .values(config=config_json, updated_at=now),
        )
    )


def execute_prepared_provider_write(
    db: Session,
    prepared: PreparedMetadataProviderWrite,
) -> None:
    for statement in prepared.statements:
        db.execute(statement)


def source_to_dict(source: Source) -> dict[str, Any]:
    """Map ORM Source attrs to the metadata provider public projection."""

    return {
        "id": source.id,
        "name": source.name,
        "kind": source.kind,
        "providerType": source.provider_type,
        "enabled": source.enabled,
        "priority": source.priority,
        "config": source.config,
        "credentialsKey": source.credentials_key,
        "capabilities": source.capabilities,
        "rateLimit": source.rate_limit,
        "lastTestAt": source.last_test_at,
        "lastTestStatus": source.last_test_status,
        "lastError": source.last_error,
        "createdAt": source.created_at,
        "updatedAt": source.updated_at,
    }


def list_metadata_sources(db: Session) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(Source)
        .where(Source.kind == METADATA_SOURCE_KIND)
        .order_by(Source.priority, Source.created_at, Source.provider_type)
    ).all()
    return [source_to_dict(row) for row in rows]


def get_provider_source(db: Session, provider_id: str) -> dict[str, Any] | None:
    row = db.scalars(
        select(Source)
        .where(
            Source.kind == METADATA_SOURCE_KIND,
            Source.provider_type == provider_id,
        )
        .order_by(Source.created_at)
        .limit(1)
    ).first()
    return source_to_dict(row) if row else None


def update_source_test_result(
    db: Session,
    source_id: str,
    *,
    expected_updated_at: datetime,
    status: str,
    error: str | None,
    now: datetime,
) -> bool:
    result = cast(
        CursorResult[Any],
        db.execute(
            update(Source)
            .where(Source.id == source_id, Source.updated_at == expected_updated_at)
            .values(
                last_test_at=now,
                last_test_status=status,
                last_error=error,
                updated_at=now,
            )
        ),
    )
    return bool(result.rowcount)


def list_enabled_provider_ids(db: Session) -> list[str]:
    return [
        str(provider_id)
        for provider_id in db.scalars(
            select(Source.provider_type)
            .where(
                Source.kind == METADATA_SOURCE_KIND,
                Source.enabled.is_(True),
            )
            .order_by(Source.priority, Source.created_at, Source.provider_type)
        ).all()
    ]
