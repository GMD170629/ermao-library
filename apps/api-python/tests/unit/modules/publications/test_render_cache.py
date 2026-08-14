from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.modules.publications.domain.rendering import (
    PreparedPublicationRenderArtifact,
)
from app.modules.publications.infrastructure.render_cache import (
    LocalPublicationRenderFileStore,
)


def _prepared(
    content: bytes = b"deterministic render artifact",
) -> PreparedPublicationRenderArtifact:
    return PreparedPublicationRenderArtifact(
        content=content,
        content_hash=f"sha256:{hashlib.sha256(content).hexdigest()}",
        size_bytes=len(content),
        original_file_hash="sha256:" + "a" * 64,
        source_parser="fixture-parser:1",
        normalization="shuku-render-html5-v1",
        unreadable_hrefs=(),
        recovered_resource_count=0,
    )


def test_concurrent_publication_is_atomic_and_leaves_no_partial_files(
    tmp_path: Path,
) -> None:
    store = LocalPublicationRenderFileStore(tmp_path)
    prepared = _prepared()

    with ThreadPoolExecutor(max_workers=8) as executor:
        published = list(
            executor.map(lambda _index: store.publish(prepared), range(16))
        )

    relative_paths = {relative for relative, _path in published}
    absolute_paths = {path for _relative, path in published}
    assert len(relative_paths) == 1
    assert len(absolute_paths) == 1
    destination = absolute_paths.pop()
    assert destination.read_bytes() == prepared.content
    assert list(tmp_path.rglob("*.partial")) == []


def test_invalid_existing_cache_entry_is_replaced_and_traversal_is_not_resolved(
    tmp_path: Path,
) -> None:
    store = LocalPublicationRenderFileStore(tmp_path)
    prepared = _prepared()
    relative, destination = store.publish(prepared)
    destination.write_bytes(b"truncated")

    repeated_relative, repeated_destination = store.publish(prepared)

    assert repeated_relative == relative
    assert repeated_destination == destination
    assert destination.read_bytes() == prepared.content
    assert store.resolve(relative) == destination
    assert store.resolve("../outside.epub") is None
    assert list(tmp_path.rglob("*.partial")) == []
