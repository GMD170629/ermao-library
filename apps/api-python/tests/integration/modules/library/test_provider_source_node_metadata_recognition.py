"""Integration coverage for provider-backed SourceNode recognition."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibrarySourceNode,
)
from app.modules.library.infrastructure import source_node_metadata_recognition
from app.modules.library.infrastructure.source_node_metadata_recognition import (
    ProviderSourceNodeMetadataRecognition,
)


def _path_key(relative_path: str) -> str:
    return "v1:" + hashlib.sha256(relative_path.encode()).hexdigest()


def _node(node_id: str, relative_path: str, physical_kind: str) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=relative_path,
        path_key=_path_key(relative_path),
        name=relative_path.rsplit("/", 1)[-1],
        physical_kind=physical_kind,
        observed_size_bytes=100 if physical_kind == "REGULAR_FILE" else None,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def test_provider_search_uses_book_context_accepts_owned_file_and_maps_all_fields(
    db_session: Session, monkeypatch
) -> None:
    root = _node("recognition-root", "recognition", "DIRECTORY")
    file_node = _node("recognition-file", "recognition/volume.epub", "REGULAR_FILE")
    db_session.add_all([root, file_node])
    db_session.flush()
    db_session.add(
        LibraryBook(
            id="recognition-book",
            library_id="test-library",
            source_node_id=root.id,
        )
    )
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id="recognition-book",
            title="图书标题",
            normalized_title="图书标题",
            author="作者",
            series_name="系列",
            series_index=1,
        )
    )
    db_session.add(
        LibraryReadableResource(
            id="recognition-resource",
            library_id="test-library",
            book_id="recognition-book",
            source_node_id=file_node.id,
            adapter_id="epub-file",
            adapter_version="1",
            format="EPUB",
            import_state="READY",
        )
    )
    db_session.commit()
    received_context: dict[str, object] = {}

    def fake_search(
        db: Session,
        context: dict[str, object],
        provider_id: str,
        query: str,
    ) -> dict[str, object]:
        del db, provider_id, query
        received_context.update(context)
        # Regression guard: provider implementations read this exact key.
        assert isinstance(context["book"], dict)
        return {
            "candidates": [
                {
                    "id": "subject-1",
                    "source": "douban",
                    "title": "候选标题",
                    "author": "候选作者",
                    "description": "候选简介",
                    "tags": ["漫画"],
                    "seriesName": "候选系列",
                    "seriesIndex": 2,
                    "publisher": "出版社",
                    "publishedAt": "2026-08-26T00:00:00Z",
                    "language": "zh-CN",
                    "isbn": "9780000000001",
                    "identifier": "subject:1",
                    "narrator": "朗读者",
                    "abridged": False,
                    "resourceIndex": 3,
                    "coverUrl": "https://example.test/cover.jpg",
                    "confidence": 0.91,
                }
            ]
        }

    monkeypatch.setattr(
        source_node_metadata_recognition,
        "search_with_metadata_provider",
        fake_search,
    )

    result = ProviderSourceNodeMetadataRecognition(db_session).search(
        book_id="recognition-book",
        source_node_id=file_node.id,
        provider_id="douban",
        query="候选标题",
    )

    assert result is not None
    assert "work" not in received_context
    assert result.candidates[0].publisher == "出版社"
    assert result.candidates[0].published_at == "2026-08-26T00:00:00Z"
    assert result.candidates[0].abridged is False
    assert result.candidates[0].cover_url == "https://example.test/cover.jpg"


def test_candidate_mapping_tolerates_missing_optional_provider_keys() -> None:
    candidate = ProviderSourceNodeMetadataRecognition._candidate(
        {"id": "minimal", "title": "只有标题"},
        "douban",
    )

    assert candidate is not None
    assert candidate.title == "只有标题"
    assert candidate.author is None
    assert candidate.tags == ()
    assert candidate.cover_url is None
