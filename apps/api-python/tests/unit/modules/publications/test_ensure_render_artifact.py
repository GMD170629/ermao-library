from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Self

import pytest

from app.modules.publications.application.ensure_render_artifact import (
    EnsurePublicationRenderArtifact,
    PublicationRenderSourceChangedError,
)
from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSource,
)
from app.modules.publications.domain.rendering import (
    PreparedPublicationRenderArtifact,
    PublicationRenderArtifact,
)

SOURCE = PublicationSource(
    volume_id="volume",
    file_id="file",
    source_format="epub",
    path="source.epub",
    full_hash="a" * 64,
    title="Source",
    author=None,
)
PREPARED = PreparedPublicationRenderArtifact(
    content=b"artifact",
    content_hash="sha256:" + "b" * 64,
    size_bytes=8,
    original_file_hash="sha256:" + "a" * 64,
    source_parser="epub-package:1",
    normalization="shuku-render-html5-v1",
    unreadable_hrefs=(),
    recovered_resource_count=0,
)
SCOPE = PublicationAccessScope(
    is_admin=True,
    can_view_manual_imports=True,
    monitor_folder_ids=(),
)


class SourceRepository:
    def find_source(
        self, *, volume_id: str, access_scope: PublicationAccessScope
    ) -> PublicationSource | None:
        del volume_id, access_scope
        return SOURCE


class CacheReader:
    def __init__(self, cached: PublicationRenderArtifact | None = None) -> None:
        self.cached = cached

    def find(self, *, volume_id: str) -> PublicationRenderArtifact | None:
        del volume_id
        return self.cached


class LookupUnitOfWork:
    def __init__(self, cache: CacheReader) -> None:
        self.sources = SourceRepository()
        self.cache = cache

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback


class Builder:
    def __init__(self) -> None:
        self.calls = 0

    def build(self, source: PublicationSource) -> PreparedPublicationRenderArtifact:
        assert source == SOURCE
        self.calls += 1
        return PREPARED


class FileStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.published = False

    def publish(self, prepared: PreparedPublicationRenderArtifact) -> tuple[str, Path]:
        assert prepared == PREPARED
        self.published = True
        return "render.epub", self.path

    def resolve(self, relative_path: str) -> Path | None:
        return self.path if relative_path == "render.epub" else None


class RenderWriter:
    def __init__(self, source_is_current: bool) -> None:
        self.source_is_current = source_is_current

    def replace_if_source_current(
        self,
        *,
        source: PublicationSource,
        artifact: PublicationRenderArtifact,
    ) -> bool:
        assert source == SOURCE
        assert artifact.original_file_hash == "sha256:" + "a" * 64
        return self.source_is_current


class WriteUnitOfWork:
    def __init__(self, source_is_current: bool) -> None:
        self.render = RenderWriter(source_is_current)
        self.committed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback

    def commit(self) -> None:
        self.committed = True


def test_source_change_after_publication_cannot_replace_the_cache(
    tmp_path: Path,
) -> None:
    lookup = LookupUnitOfWork(CacheReader())
    write = WriteUnitOfWork(source_is_current=False)
    store = FileStore(tmp_path / "render.epub")
    builder = Builder()
    use_case = EnsurePublicationRenderArtifact(
        lookup_unit_of_work_factory=lambda: lookup,
        unit_of_work_factory=lambda: write,
        artifact_builder=builder,
        file_store=store,
    )

    with pytest.raises(PublicationRenderSourceChangedError):
        use_case.execute(volume_id="volume", access_scope=SCOPE)

    assert builder.calls == 1
    assert store.published is True
    assert write.committed is False


def test_valid_cached_artifact_skips_regeneration(tmp_path: Path) -> None:
    path = tmp_path / "render.epub"
    cached = PublicationRenderArtifact(
        volume_id="volume",
        file_id="file",
        original_file_hash="sha256:" + "a" * 64,
        parser="epub-package:1",
        normalization="shuku-render-html5-v1",
        relative_path="render.epub",
        content_hash="sha256:" + "b" * 64,
        size_bytes=8,
        unreadable_resource_count=0,
    )
    lookup = LookupUnitOfWork(CacheReader(cached))
    write = WriteUnitOfWork(source_is_current=True)
    store = FileStore(path)
    builder = Builder()
    use_case = EnsurePublicationRenderArtifact(
        lookup_unit_of_work_factory=lambda: lookup,
        unit_of_work_factory=lambda: write,
        artifact_builder=builder,
        file_store=store,
    )

    artifact, resolved = use_case.execute(volume_id="volume", access_scope=SCOPE)

    assert artifact == cached
    assert resolved == path
    assert builder.calls == 0
    assert store.published is False
    assert write.committed is False
