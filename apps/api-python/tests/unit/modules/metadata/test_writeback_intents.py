from __future__ import annotations

from app.modules.metadata.application.writeback import (
    MetadataWritebackProjection,
    MetadataWritebackResourceProjection,
    prepare_metadata_writeback_intents,
)


def test_null_source_revision_uses_stable_epoch_sentinel() -> None:
    projection = MetadataWritebackProjection(
        book_id="book-1",
        title="Book",
        author=None,
        description=None,
        tags_json="[]",
        series_name=None,
        series_index=None,
        cover_path=None,
        source_revision=None,
        resource_ids=("resource-1",),
        resources=(
            MetadataWritebackResourceProjection(
                id="resource-1",
                resource_id="resource-1",
                source_node_id="source-node-1",
                title="Volume",
                description=None,
                resource_index=None,
                narrator=None,
                abridged=None,
                language=None,
                publisher=None,
                published_at=None,
                identifier=None,
                isbn=None,
                cover_path=None,
            ),
        ),
        assets=(),
        imports=(),
    )

    first = prepare_metadata_writeback_intents(projection, source="TEST")
    second = prepare_metadata_writeback_intents(projection, source="TEST")

    assert first == second
    assert first[0].source_node_id == "source-node-1"
    assert first[0].resource_id == "resource-1"
    assert first[0].source_revision == "1970-01-01T00:00:00+00:00"
    assert first[0].idempotency_key
