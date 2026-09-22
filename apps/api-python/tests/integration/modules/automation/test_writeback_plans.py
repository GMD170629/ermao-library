from dataclasses import replace

import pytest

from app.bootstrap.automation import build_automation_catalog
from app.models import LibraryBookMetadata
from app.modules.automation.application.writeback_plans import (
    BuildStandardWritePlan,
    StandardWriteSelection,
)
from app.modules.automation.domain.access import (
    AutomationAccessError,
    Scope,
)
from app.modules.library.infrastructure.metadata_file_targets import (
    SqlAlchemyMetadataFileTargets,
)
from app.modules.library.infrastructure.source_file_access import (
    open_library_directory,
    open_library_file,
)
from app.modules.metadata.infrastructure.standard_publication import (
    StandardMetadataPublication,
)
from tests.integration.modules.automation.test_file_reads import file_access, opf


def setup(db, tmp_path):
    access, root = file_access(db, tmp_path)
    access = replace(
        access,
        permissions=replace(
            access.permissions,
            scopes=(access.permissions.scopes | {Scope.FILES_MODIFY})
            - {Scope.BOOKS_WRITE},

        ),
    )
    catalog = build_automation_catalog(db)
    planner = BuildStandardWritePlan(
        catalog,
        SqlAlchemyMetadataFileTargets(db),
        StandardMetadataPublication(open_library_directory, open_library_file),
        lambda: 1000,
        lambda: "write-plan",
    )
    return access, root, catalog, planner


def test_sidecar_preview_uses_confirmed_system_fields_without_database_write_permission(
    db_session, tmp_path
):
    access, root, catalog, planner = setup(db_session, tmp_path)
    original = opf("Original file title")
    (root / "allowed/metadata.opf").write_bytes(original)
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    request = StandardWriteSelection(
        "book",
        "allowed",
        schema["expected_revision"],
        "allowed-node",
        "opf",
        frozenset({"title"}),
    )
    plan = planner.execute(access, (request,))
    assert plan.expires_at_ms == 901000
    assert plan.targets[0].before.title == "Original file title"
    assert plan.targets[0].file.values.title == schema["values"]["title"]
    assert plan.targets[0].file.fields == frozenset({"title"})
    assert (root / "allowed/metadata.opf").read_bytes() == original
    assert [entry.name for entry in (root / "allowed").iterdir()] == ["metadata.opf"]
    assert catalog.get_metadata_schema(access, "book", "allowed") == schema
    with pytest.raises(AutomationAccessError, match="METADATA_CONFLICT"):
        planner.execute(access, (replace(request, expected_revision="stale"),))


def test_clear_requires_explicit_selection_and_preserves_database(db_session, tmp_path):
    access, root, catalog, planner = setup(db_session, tmp_path)
    db_session.get(LibraryBookMetadata, "allowed").description = None
    db_session.commit()
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    request = StandardWriteSelection(
        "book",
        "allowed",
        schema["expected_revision"],
        "allowed-node",
        "opf",
        frozenset({"description"}),
    )
    with pytest.raises(AutomationAccessError, match="EXPLICIT_CLEAR_REQUIRED"):
        planner.execute(access, (request,))
    plan = planner.execute(
        access, (replace(request, clear_fields=frozenset({"description"})),)
    )
    assert plan.targets[0].file.values.description is None
    assert not (root / "allowed/metadata.opf").exists()


def test_duplicate_physical_targets_are_not_merged_implicitly(db_session, tmp_path):
    access, _, catalog, planner = setup(db_session, tmp_path)
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    request = StandardWriteSelection(
        "book",
        "allowed",
        schema["expected_revision"],
        "allowed-node",
        "opf",
        frozenset({"title"}),
    )
    with pytest.raises(AutomationAccessError, match="SHARED_WRITEBACK_TARGET"):
        planner.execute(access, (request, request))


def test_standard_plan_roundtrip_uses_existing_queue_and_is_idempotent(
    db_session, tmp_path
):
    from datetime import UTC, datetime

    from sqlalchemy import func, select

    from app.models.organize import MetadataWritebackTarget
    from app.modules.metadata.infrastructure import writeback_queue
    from app.modules.metadata.infrastructure.standard_writeback_store import (
        SqlAlchemyStandardWritePlans,
    )

    access, root, catalog, planner = setup(db_session, tmp_path)
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    request = StandardWriteSelection(
        "book",
        "allowed",
        schema["expected_revision"],
        "allowed-node",
        "opf",
        frozenset({"title"}),
    )
    plan = planner.execute(access, (request,))
    store = SqlAlchemyStandardWritePlans(db_session, queue_capacity=1)
    store.save(plan)
    db_session.commit()
    assert store.load(plan.id, access.grant_id, access.user_id) == plan
    assert store.enqueue(plan, "operation", "request", 2000) == "operation"
    db_session.commit()
    assert store.enqueue(plan, "other", "retry", 1_000_000) == "operation"
    assert (
        db_session.scalar(select(func.count()).select_from(MetadataWritebackTarget))
        == 1
    )
    claimed = writeback_queue.claim_next_target(
        db_session, owner_id="worker", now=datetime.now(UTC)
    )
    assert claimed is not None
    payload = writeback_queue.decode_claimed_target(claimed)["payload"]
    assert payload == {"standard_operation_id": "operation", "ordinal": 0}
    assert not (root / "allowed/metadata.opf").exists()
