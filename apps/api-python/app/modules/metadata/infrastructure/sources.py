"""Typed persistence for metadata provider Source seed rows."""

from __future__ import annotations

import json
from collections.abc import Iterable

from sqlalchemy import inspect, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import Source
from app.modules.metadata.domain.providers import ProviderManifest

METADATA_SOURCE_KIND = "metadata"


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _source_table_ready(db: Session) -> bool:
    bind = db.get_bind()
    return bind is not None and inspect(bind).has_table("Source")


def ensure_metadata_sources(db: Session, manifests: Iterable[ProviderManifest]) -> None:
    """Insert missing provider sources without changing existing configuration."""

    if not _source_table_ready(db):
        return

    existing_provider_ids = set(
        db.execute(
            select(Source.provider_type).where(Source.kind == METADATA_SOURCE_KIND)
        ).scalars()
    )
    now = db_timestamp()
    for manifest in manifests:
        if manifest.id in existing_provider_ids:
            continue
        config = {
            field.key: field.default
            for field in manifest.config_fields
            if field.default is not None
        }
        statement = (
            sqlite_insert(Source)
            .values(
                id=f"metadata-provider-{manifest.id}",
                name=manifest.name,
                kind=METADATA_SOURCE_KIND,
                provider_type=manifest.id,
                enabled=False,
                priority=manifest.default_priority,
                config=_json_text(config),
                capabilities=_json_text(list(manifest.capabilities)),
                rate_limit=_json_text({}),
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[Source.id])
        )
        db.execute(statement)
        existing_provider_ids.add(manifest.id)
