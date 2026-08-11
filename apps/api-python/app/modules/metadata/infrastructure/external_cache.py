"""ORM persistence for ExternalMetadataCache."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.core.time import now_timestamp_ms, timestamp_ms_to_datetime
from app.models.library import ExternalMetadataCache


def _has_table(db: Session, table: str) -> bool:
    return inspect(db.connection()).has_table(table)


@dataclass(frozen=True, slots=True)
class PreparedExternalMetadataCacheWrite:
    statement: Executable


def external_metadata_cache_ready(db: Session) -> bool:
    return _has_table(db, "ExternalMetadataCache")


def get_cached_raw_json(db: Session, *, provider: str, query_key: str) -> str | None:
    if not query_key or not _has_table(db, "ExternalMetadataCache"):
        return None
    now = timestamp_ms_to_datetime(now_timestamp_ms())
    entity = db.scalar(
        select(ExternalMetadataCache).where(
            ExternalMetadataCache.provider == provider,
            ExternalMetadataCache.query_key == query_key,
            (ExternalMetadataCache.expires_at.is_(None)) | (ExternalMetadataCache.expires_at > now),
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
    if not query_key or not _has_table(db, "ExternalMetadataCache"):
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
            index_elements=[ExternalMetadataCache.provider, ExternalMetadataCache.query_key],
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
