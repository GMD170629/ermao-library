"""ORM persistence for metadata provider Source and pipeline rows."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, inspect, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import Source
from app.models.organize import MetadataProviderPipeline
from app.modules.metadata.infrastructure.sources import METADATA_SOURCE_KIND


def source_to_dict(source: Source) -> dict[str, Any]:
    """Map ORM Source attrs to camelCase keys matching legacy raw-SQL row dicts."""

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


def pipeline_to_dict(row: MetadataProviderPipeline) -> dict[str, Any]:
    return {
        "mediaKind": row.media_kind,
        "providerId": row.provider_id,
        "included": row.included,
        "enabled": row.enabled,
        "position": row.position,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
    }


def list_metadata_sources(db: Session) -> list[dict[str, Any]]:
    if not inspect(db.connection()).has_table("Source"):
        return []
    rows = db.scalars(
        select(Source)
        .where(Source.kind == METADATA_SOURCE_KIND)
        .order_by(Source.priority, Source.created_at)
    ).all()
    return [source_to_dict(row) for row in rows]


def get_provider_source(db: Session, provider_id: str) -> dict[str, Any] | None:
    if not inspect(db.connection()).has_table("Source"):
        return None
    row = db.scalars(
        select(Source)
        .where(Source.kind == METADATA_SOURCE_KIND, Source.provider_type == provider_id)
        .order_by(Source.created_at)
        .limit(1)
    ).first()
    return source_to_dict(row) if row else None


def ensure_pipeline_row(
    db: Session,
    *,
    media_kind: str,
    provider_id: str,
    enabled: bool,
    position: int,
    now: datetime | None = None,
) -> None:
    stamp = now or db_timestamp()
    statement = (
        sqlite_insert(MetadataProviderPipeline)
        .values(
            media_kind=media_kind,
            provider_id=provider_id,
            included=True,
            enabled=enabled,
            position=position,
            created_at=stamp,
            updated_at=stamp,
        )
        .on_conflict_do_nothing(
            index_elements=[
                MetadataProviderPipeline.media_kind,
                MetadataProviderPipeline.provider_id,
            ]
        )
    )
    db.execute(statement)


def list_included_pipelines(db: Session) -> list[dict[str, Any]]:
    if not inspect(db.connection()).has_table("MetadataProviderPipeline"):
        return []
    rows = db.scalars(
        select(MetadataProviderPipeline)
        .where(MetadataProviderPipeline.included.is_(True))
        .order_by(
            MetadataProviderPipeline.media_kind,
            MetadataProviderPipeline.position,
            MetadataProviderPipeline.created_at,
        )
    ).all()
    return [pipeline_to_dict(row) for row in rows]


def list_pipelines_for_provider(db: Session, provider_id: str) -> list[dict[str, Any]]:
    if not inspect(db.connection()).has_table("MetadataProviderPipeline"):
        return []
    rows = db.scalars(
        select(MetadataProviderPipeline).where(
            MetadataProviderPipeline.provider_id == provider_id,
            MetadataProviderPipeline.included.is_(True),
        )
    ).all()
    return [pipeline_to_dict(row) for row in rows]


def clear_media_kind_pipelines(db: Session, media_kind: str, now: datetime) -> None:
    db.execute(
        update(MetadataProviderPipeline)
        .where(MetadataProviderPipeline.media_kind == media_kind)
        .values(included=False, enabled=False, updated_at=now)
    )


def update_pipeline_row(
    db: Session,
    *,
    media_kind: str,
    provider_id: str,
    included: bool,
    enabled: bool,
    position: int,
    now: datetime,
) -> None:
    db.execute(
        update(MetadataProviderPipeline)
        .where(
            MetadataProviderPipeline.media_kind == media_kind,
            MetadataProviderPipeline.provider_id == provider_id,
        )
        .values(included=included, enabled=enabled, position=position, updated_at=now)
    )


def set_provider_pipelines_enabled(
    db: Session, provider_id: str, enabled: bool, now: datetime
) -> None:
    db.execute(
        update(MetadataProviderPipeline)
        .where(MetadataProviderPipeline.provider_id == provider_id)
        .values(included=True, enabled=enabled, updated_at=now)
    )


def update_source_enabled_priority(
    db: Session,
    provider_id: str,
    *,
    enabled: bool,
    priority: int,
    now: datetime,
) -> None:
    db.execute(
        update(Source)
        .where(Source.kind == METADATA_SOURCE_KIND, Source.provider_type == provider_id)
        .values(enabled=enabled, priority=priority, updated_at=now)
    )


def update_source_config(
    db: Session,
    source_id: str,
    *,
    enabled: bool,
    priority: int,
    config: str,
    now: datetime,
) -> None:
    db.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(enabled=enabled, priority=priority, config=config, updated_at=now)
    )


def update_source_test_result(
    db: Session,
    source_id: str,
    *,
    status: str,
    error: str | None,
    now: datetime,
) -> None:
    db.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(
            last_test_at=now,
            last_test_status=status,
            last_error=error,
            updated_at=now,
        )
    )


def list_enabled_provider_ids(db: Session, media_kind: str | None = None) -> list[str]:
    if not inspect(db.connection()).has_table("MetadataProviderPipeline"):
        return []
    if media_kind is None:
        position_col = func.min(MetadataProviderPipeline.position).label("position")
        rows = db.execute(
            select(MetadataProviderPipeline.provider_id, position_col)
            .where(
                MetadataProviderPipeline.included.is_(True),
                MetadataProviderPipeline.enabled.is_(True),
            )
            .group_by(MetadataProviderPipeline.provider_id)
            .order_by(position_col, MetadataProviderPipeline.provider_id)
        ).all()
        return [str(provider_id) for provider_id, _position in rows]

    rows = db.scalars(
        select(MetadataProviderPipeline.provider_id)
        .where(
            MetadataProviderPipeline.media_kind == media_kind,
            MetadataProviderPipeline.included.is_(True),
            MetadataProviderPipeline.enabled.is_(True),
        )
        .order_by(
            MetadataProviderPipeline.position, MetadataProviderPipeline.created_at
        )
    ).all()
    return [str(provider_id) for provider_id in rows]
