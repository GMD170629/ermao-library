"""Metadata capability composition root."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.time import now_timestamp_ms, timestamp_ms_to_datetime
from app.modules.metadata.application.cache_maintenance import (
    prune_expired_metadata_cache,
)
from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS
from app.modules.metadata.infrastructure.automatic_rate_limiter import (
    AutomaticMetadataRequestRateLimiter,
)
from app.modules.metadata.infrastructure.external_cache import (
    SqlAlchemyExpiredMetadataCacheStore,
)
from app.modules.metadata.infrastructure.providers import (
    get_provider_source,
    list_enabled_provider_ids,
    list_metadata_sources,
    source_to_dict,
)
from app.modules.metadata.infrastructure.sources import (
    METADATA_SOURCE_KIND,
    execute_metadata_source_seed_write,
    prepare_metadata_source_seed_rows,
    prepare_metadata_source_seed_write,
    write_metadata_source_seed_rows,
)
from app.services.metadata_file_writeback import (
    load_metadata_writeback_projection,
    persist_metadata_writeback_intents,
)


def build_automatic_metadata_request_gate() -> AutomaticMetadataRequestRateLimiter:
    return AutomaticMetadataRequestRateLimiter(BUILTIN_MANIFESTS)


def maintain_external_metadata_cache(
    db: Session, *, cancelled: Callable[[], bool]
) -> int:
    return prune_expired_metadata_cache(
        SqlAlchemyExpiredMetadataCacheStore(db),
        unit_of_work=db,
        now=timestamp_ms_to_datetime(now_timestamp_ms()),
        cancelled=cancelled,
    )


__all__ = [
    "METADATA_SOURCE_KIND",
    "build_automatic_metadata_request_gate",
    "execute_metadata_source_seed_write",
    "get_provider_source",
    "list_enabled_provider_ids",
    "list_metadata_sources",
    "load_metadata_writeback_projection",
    "maintain_external_metadata_cache",
    "persist_metadata_writeback_intents",
    "prepare_metadata_source_seed_rows",
    "prepare_metadata_source_seed_write",
    "source_to_dict",
    "write_metadata_source_seed_rows",
]
