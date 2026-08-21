"""Storage, metadata and organize projections over Book/Resource/Asset rows."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.library.infrastructure.storage import first_asset_for_resource
from app.modules.metadata.infrastructure.writeback_queue import (
    load_metadata_writeback_projection,
)
from app.modules.organize.infrastructure.eligibility import (
    first_resource_selection_for_book,
)
from app.modules.organize.infrastructure.review import earliest_resource_id

API_ROOT = Path(__file__).resolve().parents[4]
READ_PATH_SOURCES = (
    API_ROOT / "app/modules/library/infrastructure/storage.py",
    API_ROOT / "app/modules/metadata/infrastructure/writeback_queue.py",
    API_ROOT / "app/modules/organize/infrastructure/eligibility.py",
    API_ROOT / "app/modules/organize/infrastructure/review.py",
)


def _node(node_id: str, path: str, *, directory: bool = False) -> LibrarySourceNode:
    return LibrarySourceNode(
        id=node_id,
        library_id="test-library",
        relative_path=path,
        path_key="v1:" + hashlib.sha256(path.encode()).hexdigest(),
        name=path.rsplit("/", 1)[-1],
        physical_kind="DIRECTORY" if directory else "REGULAR_FILE",
        observed_size_bytes=None if directory else 12,
        observed_mtime_ns=0,
        observed_at=datetime.now(UTC),
    )


def _seed_book_resources(
    db_session, *, book_id: str = "book-1"
) -> list[LibraryReadableResource]:
    book_node = _node(f"{book_id}-node", f"{book_id}/", directory=True)
    book = LibraryBook(
        id=book_id, library_id="test-library", source_node_id=book_node.id
    )
    db_session.add(book_node)
    db_session.flush()
    db_session.add(book)
    db_session.flush()
    db_session.add(
        LibraryBookMetadata(
            book_id=book_id,
            title="Binding book",
            normalized_title="binding book",
            author="Author",
            description="Description",
        )
    )
    db_session.flush()
    resources: list[LibraryReadableResource] = []
    for index in range(2):
        resource_id = f"resource-{index + 1}"
        source = _node(f"{resource_id}-node", f"{book_id}/{resource_id}.epub")
        resource = LibraryReadableResource(
            id=resource_id,
            library_id="test-library",
            book_id=book_id,
            source_node_id=source.id,
            adapter_id="epub-file",
            adapter_version="1",
            media_kind="EBOOK",
            format="EPUB",
            import_state="READY",
        )
        resources.append(resource)
        db_session.add(source)
        db_session.flush()
        db_session.add(resource)
        db_session.flush()
        db_session.add(
            LibraryReadableResourceMetadata(
                resource_id=resource_id,
                title=f"Resource {index + 1}",
                resource_index=index + 1,
            )
        )
        db_session.add(
            LibraryResourceAsset(
                id=f"asset-{index + 1}",
                library_id="test-library",
                resource_id=resource_id,
                source_node_id=source.id,
                source_node_physical_kind="REGULAR_FILE",
                role="PRIMARY",
                import_state="READY",
            )
        )
        db_session.flush()
    db_session.commit()
    return resources


def test_storage_selects_the_first_asset_for_a_resource(db_session) -> None:
    resources = _seed_book_resources(db_session)

    asset = first_asset_for_resource(db_session, resource_id=resources[0].id)

    assert asset is not None
    assert asset["id"] == "asset-1"
    assert asset["resourceId"] == resources[0].id


def test_metadata_writeback_projection_is_scoped_to_one_book_resource(
    db_session,
) -> None:
    resources = _seed_book_resources(db_session)

    projection = load_metadata_writeback_projection(
        db_session,
        book_id="book-1",
        resource_id=resources[1].id,
    )

    assert projection.book_id == "book-1"
    assert projection.resource_ids == (resources[1].id,)
    assert len(projection.resources) == 1
    assert projection.resources[0].id == resources[1].id


def test_organize_selection_and_review_order_resources_by_book(db_session) -> None:
    resources = _seed_book_resources(db_session)

    selection = first_resource_selection_for_book(db_session, "book-1")

    assert selection is not None
    assert selection[0] in {resource.id for resource in resources}
    assert earliest_resource_id(db_session, "book-1") == resources[0].id


def test_touched_read_paths_use_canonical_model_bindings() -> None:
    required_models = {
        READ_PATH_SOURCES[0]: (
            "LibraryBook",
            "LibraryReadableResource",
            "LibraryResourceAsset",
        ),
        READ_PATH_SOURCES[1]: (
            "LibraryBook",
            "LibraryReadableResource",
            "LibraryResourceAsset",
        ),
        READ_PATH_SOURCES[2]: ("LibraryBook", "LibraryReadableResource"),
        READ_PATH_SOURCES[3]: (
            "LibraryBook",
            "LibraryReadableResource",
            "LibraryResourceAsset",
        ),
    }
    for source_path, models in required_models.items():
        source = source_path.read_text(encoding="utf-8")
        assert all(model in source for model in models), source_path
