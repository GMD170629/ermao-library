from io import BytesIO

import pytest
from PIL import Image

from app.bootstrap.automation import build_automation_catalog, build_automation_writes
from app.models import (
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNodeMetadata,
)
from app.modules.imports.infrastructure.local_cover_publication import (
    FilesystemLocalCoverPublication,
)
from app.modules.library.public import MetadataPatchError
from tests.integration.modules.automation.test_file_reads import add_file
from tests.integration.modules.automation.test_metadata_patches import (
    change,
    setup_metadata,
)


def cover_fixture(db, tmp_path):
    access = setup_metadata(db)
    add_file(db, "asset-node", "allowed/book.epub")
    db.add(
        LibraryReadableResource(
            id="resource",
            library_id="test-library",
            book_id="allowed",
            source_node_id="asset-node",
            adapter_id="fixture",
            adapter_version="1",
            format="EPUB",
            import_state="READY",
        )
    )
    db.flush()
    db.add(LibraryReadableResourceMetadata(resource_id="resource", title="Volume"))
    image = BytesIO()
    Image.new("RGB", (10, 10), "red").save(image, format="PNG")
    files = FilesystemLocalCoverPublication(tmp_path)
    prepared = files.prepare(resource_id="resource", content=image.getvalue())
    files.publish(prepared)
    db.add(
        LibraryResourceAsset(
            id="asset",
            library_id="test-library",
            resource_id="resource",
            source_node_id="asset-node",
            role="PRIMARY",
            import_state="READY",
            local_cover_path=prepared.stored_path,
        )
    )
    db.commit()
    return access, prepared.stored_path


@pytest.mark.parametrize(
    ("kind", "target", "model"),
    [
        ("book", "allowed", LibraryBookMetadata),
        ("resource", "resource", LibraryReadableResourceMetadata),
        ("source_node", "allowed-node", LibrarySourceNodeMetadata),
    ],
)
def test_safe_existing_reference_changes_only_database_and_protects_cover(
    db_session, tmp_path, kind, target, model
):
    access, stored_path = cover_fixture(db_session, tmp_path / "cover-storage")
    files_before = {
        p.relative_to(tmp_path): (p.stat().st_mtime_ns, p.read_bytes())
        for p in (tmp_path / "cover-storage").rglob("*")
        if p.is_file()
    }
    catalog = build_automation_catalog(db_session)
    schema = catalog.get_metadata_schema(access, kind, target)
    reference = schema["cover_references"][0]
    assert stored_path not in str(schema)
    assert reference.startswith("cover:")
    patch = change(
        db_session, access, target=target, kind=kind, fields={"cover_ref": reference}
    )
    commands = build_automation_writes(db_session)
    commands.update_metadata(access, "cover", (patch,))
    row = db_session.get(model, target)
    assert row.cover_path == stored_path
    assert row.cover_status == "READY"
    assert "cover_path" in row.protected_fields
    if kind == "source_node":
        assert db_session.get(LibraryBookMetadata, "allowed").cover_path == stored_path
    current = catalog.get_metadata_schema(access, kind, target)
    assert current["values"]["cover_ref"] == reference
    assert "cover_ref" in current["protected_fields"]
    clear = change(
        db_session,
        access,
        target=target,
        kind=kind,
        fields={"description": "unchanged file"},
        clear_fields=frozenset({"cover_ref"}),
    )
    with pytest.raises(MetadataPatchError, match="PROTECTED_FIELD"):
        commands.update_metadata(access, "without-override", (clear,))
    clear = change(
        db_session,
        access,
        target=target,
        kind=kind,
        fields={"description": "unchanged file"},
        clear_fields=frozenset({"cover_ref"}),
        override_fields=frozenset({"cover_ref"}),
    )
    commands.update_metadata(access, "clear-cover", (clear,))
    assert db_session.get(model, target).cover_path is None
    assert files_before == {
        p.relative_to(tmp_path): (p.stat().st_mtime_ns, p.read_bytes())
        for p in (tmp_path / "cover-storage").rglob("*")
        if p.is_file()
    }


def test_foreign_mutable_and_stale_references_are_rejected(db_session, tmp_path):
    access, _ = cover_fixture(db_session, tmp_path)
    catalog = build_automation_catalog(db_session)
    reference = catalog.get_metadata_schema(access, "book", "allowed")[
        "cover_references"
    ][0]
    commands = build_automation_writes(db_session)
    for index, bad in enumerate(
        ("https://example.invalid/cover.jpg", "../../private.jpg", "cover:" + "0" * 64)
    ):
        patch = change(db_session, access, fields={"cover_ref": bad})
        with pytest.raises(MetadataPatchError, match="INVALID_COVER_REFERENCE"):
            commands.update_metadata(access, f"bad-{index}", (patch,))
    asset = db_session.get(LibraryResourceAsset, "asset")
    asset.local_cover_path = "covers/resources/resource.jpg"
    db_session.commit()
    assert (
        catalog.get_metadata_schema(access, "book", "allowed")["cover_references"] == []
    )
    patch = change(db_session, access, fields={"cover_ref": reference})
    with pytest.raises(MetadataPatchError, match="INVALID_COVER_REFERENCE"):
        commands.update_metadata(access, "stale", (patch,))
    assert db_session.get(LibraryBookMetadata, "allowed").cover_path is None
