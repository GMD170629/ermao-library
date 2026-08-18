"""Bounded library-level outbox notifications for dormant content workers."""

from enum import StrEnum

from app.modules.catalog.application.ports import OutboxEvent, OutboxPort


class ContentWakeReason(StrEnum):
    SOURCE_OBSERVED = "SOURCE_OBSERVED"
    TOPOLOGY_ACTIVATED = "TOPOLOGY_ACTIVATED"
    SOURCE_DIGEST_READY = "SOURCE_DIGEST_READY"
    SOURCE_DIGEST_RETRY = "SOURCE_DIGEST_RETRY"
    REQUIRED_MANIFEST_READY = "REQUIRED_MANIFEST_READY"


def append_content_available(
    outbox: OutboxPort,
    *,
    library_id: str,
    reason: ContentWakeReason,
) -> None:
    outbox.append(
        OutboxEvent(
            "CATALOG_CONTENT_AVAILABLE",
            library_id,
            "SYSTEM",
            (("reason", reason.value),),
        )
    )


__all__ = ["ContentWakeReason", "append_content_available"]
