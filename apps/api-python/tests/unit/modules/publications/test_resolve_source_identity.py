from __future__ import annotations

from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSource,
)
from app.modules.publications.application.resolve_source_identity import (
    ResolvePublicationSourceIdentity,
)


class _SourceRepository:
    def __init__(self, source: PublicationSource | None) -> None:
        self.source = source

    def find_source(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSource | None:
        del volume_id, access_scope
        return self.source


class _Hasher:
    def sha256(self, source: PublicationSource) -> str:
        assert source.volume_id == "volume-1"
        return "sha256:" + "a" * 64


def test_resolves_actual_source_hash_when_legacy_database_hash_is_missing() -> None:
    source = PublicationSource(
        volume_id="volume-1",
        file_id="file-1",
        source_format="mobi",
        path="book.mobi",
        full_hash=None,
        title="Book",
        author="Author",
    )
    resolver = ResolvePublicationSourceIdentity(
        repository=_SourceRepository(source),
        hasher=_Hasher(),
    )

    identity = resolver.execute(
        volume_id="volume-1",
        access_scope=PublicationAccessScope(
            is_admin=True,
            can_view_manual_imports=True,
            monitor_folder_ids=(),
        ),
    )

    assert identity.original_file_hash == "sha256:" + "a" * 64
    assert identity.source_format == "mobi"
