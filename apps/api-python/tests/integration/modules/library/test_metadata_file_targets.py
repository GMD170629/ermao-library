from app.models import LibraryReadableResource
from app.modules.library.infrastructure.metadata_file_targets import (
    SqlAlchemyMetadataFileTargets,
)
from tests.integration.modules.automation.test_file_reads import add_file, file_access


def test_file_target_keeps_canonical_resource_identity_and_library_scope(
    db_session, tmp_path
):
    _, root = file_access(db_session, tmp_path)
    add_file(db_session, "comic-node", "allowed/comic.cbz")
    db_session.add(
        LibraryReadableResource(
            id="comic-resource",
            library_id="test-library",
            book_id="allowed",
            source_node_id="comic-node",
            adapter_id="comic-archive",
            adapter_version="1",
            format="COMIC",
            enablement_state="ENABLED",
            import_state="READY",
        )
    )
    db_session.commit()
    query = SqlAlchemyMetadataFileTargets(db_session)
    result = query.get("comic-node", frozenset({"test-library"}))
    assert result is not None
    assert (result.book_id, result.resource_id, result.format, result.directory) == (
        "allowed",
        "comic-resource",
        "COMIC",
        False,
    )
    assert result.root == root
    assert query.get("comic-node", frozenset({"private-library"})) is None
    directory = query.get("allowed-node", frozenset({"test-library"}))
    assert (
        directory is not None and directory.directory and directory.resource_id is None
    )
