"""ORM persistence for ExternalMetadataCache."""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import Float, String, cast, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.time import now_timestamp_ms, timestamp_ms_to_datetime
from app.models.library import ExternalMetadataCache
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.infrastructure.short_writes import (
    metadata_short_write_session,
)


@dataclass(frozen=True, slots=True)
class PreparedExternalMetadataCacheWrite:
    statement: Executable


def external_metadata_cache_ready(db: Session) -> bool:
    del db
    return True


def get_cached_raw_json(db: Session, *, provider: str, query_key: str) -> str | None:
    if not query_key:
        return None
    now = timestamp_ms_to_datetime(now_timestamp_ms())
    entity = db.scalar(
        select(ExternalMetadataCache).where(
            ExternalMetadataCache.provider == provider,
            ExternalMetadataCache.query_key == query_key,
            (ExternalMetadataCache.expires_at.is_(None))
            | (ExternalMetadataCache.expires_at > now),
        )
    )
    return entity.raw_json if entity is not None else None


def upsert_cache_entry(
    db: Session,
    *,
    entry_id: str,
    provider: str,
    query_key: str,
    raw_json: str,
    expires_at_ms: int,
    now_ms: int,
) -> None:
    if not query_key:
        return
    prepared = prepare_cache_entry_write(
        entry_id=entry_id,
        provider=provider,
        query_key=query_key,
        raw_json=raw_json,
        expires_at_ms=expires_at_ms,
        now_ms=now_ms,
    )
    write_prepared_cache_entry(db, prepared)


def prepare_cache_entry_write(
    *,
    entry_id: str,
    provider: str,
    query_key: str,
    raw_json: str,
    expires_at_ms: int,
    now_ms: int,
) -> PreparedExternalMetadataCacheWrite:
    now = timestamp_ms_to_datetime(now_ms)
    expires_at = timestamp_ms_to_datetime(expires_at_ms)
    statement = (
        sqlite_insert(ExternalMetadataCache)
        .values(
            id=entry_id,
            provider=provider,
            query_key=query_key,
            raw_json=raw_json,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[
                ExternalMetadataCache.provider,
                ExternalMetadataCache.query_key,
            ],
            set_={
                ExternalMetadataCache.raw_json: raw_json,
                ExternalMetadataCache.expires_at: expires_at,
                ExternalMetadataCache.updated_at: now,
            },
        )
    )
    return PreparedExternalMetadataCacheWrite(statement=statement)


def write_prepared_cache_entry(
    db: Session,
    prepared: PreparedExternalMetadataCacheWrite,
) -> None:
    db.execute(prepared.statement)


def reserve_request_slot(db: Session, provider: str, interval: float) -> float:
    now = time.time()
    stamp = timestamp_ms_to_datetime(int(now * 1000))
    statement = sqlite_insert(ExternalMetadataCache).values(
        id=f"rate_{uuid4().hex}", provider="recognition-rate-v1", query_key=provider,
        raw_json=str(now + interval), created_at=stamp, updated_at=stamp,
        expires_at=None,
    ).on_conflict_do_update(
        index_elements=[ExternalMetadataCache.provider, ExternalMetadataCache.query_key],
        set_={"rawJson": cast(func.max(cast(ExternalMetadataCache.raw_json, Float), now) + interval, String),
              "updatedAt": stamp},
    ).returning(ExternalMetadataCache.raw_json)
    db.close()
    with metadata_short_write_session(db) as writer, MetadataWriteTransaction(writer):
        reserved_until = writer.scalar(statement)
        assert reserved_until is not None
    return float(reserved_until) - interval
