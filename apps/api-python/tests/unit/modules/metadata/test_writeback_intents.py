from __future__ import annotations

from app.modules.metadata.application.writeback import (
    MetadataWritebackProjection,
    prepare_metadata_writeback_intents,
)


def test_null_legacy_source_revision_uses_stable_epoch_sentinel() -> None:
    projection = MetadataWritebackProjection(
        work_id="legacy-work",
        title="Legacy",
        author=None,
        description=None,
        tags_json="[]",
        series_name=None,
        series_index=None,
        cover_path=None,
        source_revision=None,
        version_ids=("version-1",),
        volumes=(),
        files=(),
        imports=(),
    )

    first = prepare_metadata_writeback_intents(projection, source="TEST")
    second = prepare_metadata_writeback_intents(projection, source="TEST")

    assert first == second
    assert first[0].source_revision == "1970-01-01T00:00:00+00:00"
    assert first[0].idempotency_key
