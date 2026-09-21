from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.bootstrap.automation import (
    build_automation_catalog,
    build_automation_writes,
    build_grant_manager,
)
from app.models import (
    Library,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibrarySourceNodeMetadata,
)
from app.models.library import LibraryOperation
from app.models.organize import MetadataWritebackPreparation, OrganizePolicy
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.automation.infrastructure.models import AutomationReceiptRow
from app.modules.library.public import MetadataChange, MetadataPatchError
from tests.integration.modules.automation.test_mcp_catalog import seed


def setup_metadata(db):
    original = seed(db)
    permissions = replace(
        original.grant.permissions,
        scopes=frozenset(
            {
                Scope.LIBRARY_READ,
                Scope.METADATA_WRITE,
                Scope.METADATA_OVERRIDE,
                Scope.TAGS_WRITE,
            }
        ),
    )
    grant = build_grant_manager(db).create(
        user_id="mcp-owner", name="metadata", permissions=permissions
    )
    return EffectiveAccess(grant.grant.id, "mcp-owner", permissions)


def change(db, access, target="allowed", kind="book", fields=None, **kwargs):
    schema = build_automation_catalog(db).get_metadata_schema(access, kind, target)
    return MetadataChange(
        kind, target, schema["expected_revision"], "patch", fields or {}, **kwargs
    )


def test_patch_version_protection_clear_fill_and_receipt(db_session):
    access = setup_metadata(db_session)
    commands = build_automation_writes(db_session)
    first = change(
        db_session,
        access,
        fields={"title": "Updated", "description": "User description"},
    )
    outcome = commands.update_metadata(access, "patch-1", (first,))
    assert outcome["updated"] == 1
    assert commands.update_metadata(access, "patch-1", (first,)) == outcome
    row = db_session.get(LibraryBookMetadata, "allowed")
    assert row.title == "Updated" and row.normalized_title == "updated"
    assert row.description == "User description"
    with pytest.raises(MetadataPatchError, match="CONFLICT"):
        commands.update_metadata(
            access, "stale", (replace(first, fields={"title": "Stale"}),)
        )
    protected = change(db_session, access, fields={"title": "Protected overwrite"})
    with pytest.raises(MetadataPatchError, match="PROTECTED_FIELD"):
        commands.update_metadata(access, "protected", (protected,))
    override = replace(protected, override_fields=frozenset({"title"}))
    low = replace(
        access,
        permissions=replace(
            access.permissions,
            scopes=access.permissions.scopes - {Scope.METADATA_OVERRIDE},
        ),
    )
    with pytest.raises(AutomationAccessError, match="SCOPE_REQUIRED"):
        commands.update_metadata(low, "no-override-scope", (override,))
    commands.update_metadata(access, "override", (override,))
    assert (
        db_session.get(LibraryBookMetadata, "allowed").description == "User description"
    )
    assert "title" in db_session.get(LibraryBookMetadata, "allowed").protected_fields
    clear = change(
        db_session,
        access,
        clear_fields=frozenset({"description"}),
        override_fields=frozenset({"description"}),
    )
    commands.update_metadata(access, "clear", (clear,))
    empty = change(
        db_session,
        access,
        fields={"description": "Do not refill", "author": "New author"},
    )
    commands.update_metadata(access, "fill", (replace(empty, mode="fill_missing"),))
    row = db_session.get(LibraryBookMetadata, "allowed")
    assert row.description is None and row.author == "New author"
    assert "description" in row.protected_fields
    operation = db_session.get(LibraryOperation, outcome["operation_id"])
    assert access.grant_id in operation.payload_json
    assert '"before"' in operation.payload_json and '"after"' in operation.payload_json


def test_atomic_batch_rejects_unknown_and_out_of_scope_targets(db_session):
    access = setup_metadata(db_session)
    commands = build_automation_writes(db_session)
    valid = change(db_session, access, fields={"title": "Not committed"})
    with pytest.raises(MetadataPatchError, match="RESOURCE_NOT_FOUND"):
        commands.update_metadata(
            access, "mixed", (valid, replace(valid, target_id="secret"))
        )
    assert db_session.get(LibraryBookMetadata, "allowed").title == "二毛"
    for fields, clear in (
        ({"library_id": "private-library"}, frozenset()),
        ({"title": None}, frozenset()),
        ({}, frozenset({"title"})),
    ):
        with pytest.raises(MetadataPatchError):
            commands.update_metadata(
                access, "invalid", (replace(valid, fields=fields, clear_fields=clear),)
            )
    assert list(db_session.scalars(select(AutomationReceiptRow))) == []


def test_root_node_protection_and_unchanged_fields_are_precise(db_session, tmp_path):
    access = setup_metadata(db_session)
    root = tmp_path / "library"
    source = root / "allowed"
    source.mkdir(parents=True)
    original = source / "metadata.opf"
    original.write_bytes(b"unchanged")
    db_session.get(Library, "test-library").root_path = str(root)
    db_session.add(OrganizePolicy(id="default", write_metadata_to_files=True))
    book = db_session.get(LibraryBookMetadata, "allowed")
    book.description = "Preserve book description"
    book.protected_fields = '["title"]'
    db_session.add(
        LibrarySourceNodeMetadata(
            source_node_id="allowed-node",
            title="Directory",
            description="Preserve node description",
        )
    )
    db_session.commit()
    commands = build_automation_writes(db_session)
    patch = change(
        db_session,
        access,
        target="allowed-node",
        kind="source_node",
        fields={"title": "Synced title"},
    )
    with pytest.raises(MetadataPatchError, match="PROTECTED_FIELD"):
        commands.update_metadata(access, "root-protection", (patch,))
    commands.update_metadata(
        access, "root-explicit", (replace(patch, override_fields=frozenset({"title"})),)
    )
    book = db_session.get(LibraryBookMetadata, "allowed")
    node = db_session.get(LibrarySourceNodeMetadata, "allowed-node")
    assert book.title == node.title == "Synced title"
    assert book.description == "Preserve book description"
    assert node.description == "Preserve node description"
    assert (
        "description" not in book.protected_fields
        and "description" not in node.protected_fields
    )
    assert original.read_bytes() == b"unchanged"
    assert list(source.iterdir()) == [original]
    assert list(db_session.scalars(select(MetadataWritebackPreparation))) == []
    schema = build_automation_catalog(db_session).get_metadata_schema(
        access, "source_node", "allowed-node"
    )
    assert schema["linked_book_id"] == "allowed"


def test_resource_fields_use_own_metadata_and_version(db_session):
    access = setup_metadata(db_session)
    db_session.add(
        LibraryReadableResource(
            id="resource",
            library_id="test-library",
            book_id="allowed",
            source_node_id="allowed-node",
            adapter_id="fixture",
            adapter_version="1",
            format="EPUB",
            import_state="READY",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResourceMetadata(
            resource_id="resource", title="Volume", language="en"
        )
    )
    db_session.commit()
    commands = build_automation_writes(db_session)
    patch = change(
        db_session,
        access,
        target="resource",
        kind="resource",
        fields={
            "title": "卷一",
            "language": "zh",
            "published_at": "2026-01-01T00:00:00+00:00",
            "abridged": False,
        },
    )
    commands.update_metadata(access, "resource", (patch,))
    row = db_session.get(LibraryReadableResourceMetadata, "resource")
    assert row.title == "卷一" and row.language == "zh" and row.abridged is False
    assert row.published_at.year == 2026
    assert db_session.get(LibraryBookMetadata, "allowed").title == "二毛"
    with pytest.raises(MetadataPatchError, match="CONFLICT"):
        commands.update_metadata(access, "old-resource", (patch,))


def test_metadata_changed_in_another_session_rejects_old_revision(db_session):
    access = setup_metadata(db_session)
    original = change(db_session, access, fields={"title": "Too late"})
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    with factory() as db:
        winner = change(db, access, fields={"title": "Winner"})
        build_automation_writes(db).update_metadata(access, "winner", (winner,))
    with factory() as db:
        with pytest.raises(MetadataPatchError, match="CONFLICT"):
            build_automation_writes(db).update_metadata(access, "loser", (original,))
        assert db.get(LibraryBookMetadata, "allowed").title == "Winner"


def test_root_fill_does_not_overwrite_nonempty_linked_book(db_session):
    access = setup_metadata(db_session)
    row = db_session.get(LibraryBookMetadata, "allowed")
    row.description = "Existing book description"
    db_session.commit()
    candidate = change(
        db_session,
        access,
        target="allowed-node",
        kind="source_node",
        fields={"description": "Wrong replacement"},
    )
    result = build_automation_writes(db_session).update_metadata(
        access, "root-fill", (replace(candidate, mode="fill_missing"),)
    )
    assert result["updated"] == 0
    assert (
        db_session.get(LibraryBookMetadata, "allowed").description
        == "Existing book description"
    )
    assert db_session.get(LibrarySourceNodeMetadata, "allowed-node") is None


def test_tag_only_override_requires_exact_fields_and_revision(db_session):
    access = setup_metadata(db_session)
    # This token has no general metadata write permission.
    access = replace(
        access,
        permissions=replace(
            access.permissions,
            scopes=access.permissions.scopes - {Scope.METADATA_WRITE},
        ),
    )
    commands = build_automation_writes(db_session)
    commands.book_tags(access, "tag-first", ["allowed"], ["One"], add=True)
    with pytest.raises(AutomationAccessError, match="EXPECTED_REVISION_REQUIRED"):
        commands.book_tags(
            access,
            "missing-version",
            ["allowed"],
            ["One"],
            add=False,
            override_fields=frozenset({"tags"}),
        )
    revision = build_automation_catalog(db_session).get_metadata_schema(
        access, "book", "allowed"
    )["expected_revision"]
    result = commands.book_tags(
        access,
        "tag-override",
        ["allowed"],
        ["One"],
        add=False,
        override_fields=frozenset({"tags"}),
        expected_revisions={"allowed": revision},
    )
    assert result["updated"] == 1
    assert (
        commands.book_tags(
            access,
            "tag-override",
            ["allowed"],
            ["One"],
            add=False,
            override_fields=frozenset({"tags"}),
            expected_revisions={"allowed": revision},
        )
        == result
    )
    with pytest.raises(AutomationAccessError, match="CONFLICT"):
        commands.book_tags(
            access,
            "tag-stale",
            ["allowed"],
            ["Other"],
            add=True,
            override_fields=frozenset({"tags"}),
            expected_revisions={"allowed": revision},
        )
    assert "tags" in db_session.get(LibraryBookMetadata, "allowed").protected_fields
