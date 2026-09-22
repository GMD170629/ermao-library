from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.bootstrap.automation import (
    build_automation_settings,
    build_automation_writes,
    build_grant_manager,
)
from app.models import Library, LibraryBookFacet, LibraryBookMetadata, LibraryFacet
from app.models.organize import MetadataWritebackPreparation, OrganizePolicy
from app.models.shelf import Shelf, ShelfBook
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import (
    AutomationAccessError,
    EffectiveAccess,
    Scope,
)
from app.modules.automation.infrastructure.models import AutomationReceiptRow
from tests.integration.modules.automation.test_mcp_catalog import seed


def setup_access(db):
    read_grant = seed(db)
    permissions = replace(
        read_grant.grant.permissions,
        scopes=frozenset({Scope.SYSTEM_READ, Scope.SHELVES_WRITE, Scope.BOOKS_WRITE}),
    )
    grant = build_grant_manager(db).create(
        user_id="mcp-owner", name="writer", permissions=permissions
    )
    build_automation_settings(db).update(
        "mcp-owner",
        AutomationServiceSettings(
            enabled=True,
            enabled_scopes=permissions.scopes,
            public_base_url="http://localhost",
        ),
    )
    return EffectiveAccess(grant.grant.id, "mcp-owner", permissions)


def test_create_receipt_replay_conflict_and_rollback(db_session):
    access = setup_access(db_session)
    commands = build_automation_writes(db_session)
    result = commands.create_shelf(access, "create-1", "小说", None)
    assert commands.create_shelf(access, "create-1", "小说", None) == result
    assert len(list(db_session.scalars(select(Shelf).where(Shelf.name == "小说")))) == 1
    with pytest.raises(AutomationAccessError, match="REQUEST_ID_CONFLICT"):
        commands.create_shelf(access, "create-1", "other", None)
    assert len(list(db_session.scalars(select(AutomationReceiptRow)))) == 1

    class BrokenReceipt:
        def claim(self, *args):
            return commands._receipts.claim(*args)

        def complete(self, *args):
            raise RuntimeError("injected persistence failure")

    broken = build_automation_writes(db_session)
    broken._receipts = BrokenReceipt()
    with pytest.raises(RuntimeError, match="injected"):
        broken.create_shelf(access, "broken", "Must roll back", None)
    assert (
        db_session.scalar(select(Shelf).where(Shelf.name == "Must roll back")) is None
    )
    assert (
        db_session.scalar(
            select(AutomationReceiptRow).where(
                AutomationReceiptRow.request_id == "broken"
            )
        )
        is None
    )


def test_duplicate_concurrent_creates_share_one_receipt(db_session):
    access = setup_access(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    barrier = Barrier(2)

    def create():
        with factory() as db:
            commands = build_automation_writes(db)
            barrier.wait(timeout=10)
            return commands.create_shelf(access, "concurrent", "Same shelf", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(create)
        second = executor.submit(create)
        assert first.result(timeout=10) == second.result(timeout=10)
    assert (
        len(list(db_session.scalars(select(Shelf).where(Shelf.name == "Same shelf"))))
        == 1
    )


def test_incremental_membership_preserves_out_of_scope_members(db_session):
    access = setup_access(db_session)
    commands = build_automation_writes(db_session)
    result = commands.shelf_membership(
        access, "remove-1", "static", ["allowed"], add=False
    )
    assert result["updated"] == 1
    assert (
        commands.shelf_membership(access, "remove-1", "static", ["allowed"], add=False)
        == result
    )
    assert list(
        db_session.scalars(
            select(ShelfBook.book_id).where(ShelfBook.shelf_id == "static")
        )
    ) == ["secret"]
    with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
        commands.shelf_membership(access, "bad", "static", ["secret"], add=False)
    with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
        commands.shelf_membership(access, "smart-write", "smart", ["allowed"], add=True)
    assert (
        commands.shelf_membership(access, "add-1", "static", ["allowed"], add=True)[
            "updated"
        ]
        == 1
    )
    assert set(
        db_session.scalars(
            select(ShelfBook.book_id).where(ShelfBook.shelf_id == "static")
        )
    ) == {"secret", "allowed"}


def test_tags_are_database_only_and_replay_does_not_override_protection(
    db_session, tmp_path
):
    access = setup_access(db_session)
    root = tmp_path / "library"
    source = root / "allowed"
    source.mkdir(parents=True)
    original = source / "metadata.opf"
    original.write_bytes(b"original sidecar")
    db_session.get(Library, "test-library").root_path = str(root)
    db_session.add(OrganizePolicy(id="default", write_metadata_to_files=True))
    db_session.commit()
    commands = build_automation_writes(db_session)
    first = commands.book_tags(access, "tag-1", ["allowed"], ["科幻"], add=True)
    assert first["updated"] == 1
    assert commands.book_tags(access, "tag-1", ["allowed"], ["科幻"], add=True) == first
    tags = set(
        db_session.scalars(
            select(LibraryFacet.name)
            .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
            .where(LibraryBookFacet.book_id == "allowed", LibraryFacet.kind == "TAG")
        )
    )
    assert tags == {"allowed", "科幻"}
    assert "tags" in db_session.get(LibraryBookMetadata, "allowed").protected_fields
    with pytest.raises(AutomationAccessError, match="PROTECTED_FIELD"):
        commands.book_tags(access, "tag-2", ["allowed"], ["科幻"], add=False)
    assert list(db_session.scalars(select(MetadataWritebackPreparation))) == []
    assert original.read_bytes() == b"original sidecar"
    assert list(source.iterdir()) == [original]


def test_revocation_between_preflight_and_claim_prevents_the_write(db_session):
    access = setup_access(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    commands = build_automation_writes(db_session)
    original = commands._receipts

    class RevokeBeforeClaim:
        def claim(self, *args):
            with factory() as other:
                build_grant_manager(other).revoke(
                    user_id=access.user_id, grant_id=access.grant_id
                )
            return original.claim(*args)

        def complete(self, *args):
            return original.complete(*args)

    commands._receipts = RevokeBeforeClaim()
    with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
        commands.create_shelf(access, "revoked-mid-call", "Must not exist", None)
    assert (
        db_session.scalar(select(Shelf).where(Shelf.name == "Must not exist")) is None
    )
    assert list(db_session.scalars(select(AutomationReceiptRow))) == []


def test_smart_shelf_update_delete_and_dynamic_result(db_session):
    from app.bootstrap.automation import build_automation_catalog

    access = setup_access(db_session)
    commands = build_automation_writes(db_session)
    created = commands.create_shelf(access, "smart-create", "Dynamic", None, "SMART", {"search": "二毛"})
    shelf_id = created["shelf_id"]
    catalog = build_automation_catalog(db_session)
    assert catalog.get_shelf(access, shelf_id, 1, 20)["total"] == 1
    updated = commands.update_shelf(access, "smart-update", shelf_id, "Empty", None, "SMART", {"search": "does-not-match"})
    assert updated["kind"] == "SMART"
    assert catalog.get_shelf(access, shelf_id, 1, 20)["total"] == 0
    deleted = commands.delete_shelf(access, "smart-delete", shelf_id)
    assert deleted["deleted"] is True
    assert commands.delete_shelf(access, "smart-delete", shelf_id) == deleted
    assert db_session.get(Shelf, shelf_id) is None
