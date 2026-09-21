from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.bootstrap.automation import (
    build_automation_catalog,
    build_automation_writes,
    build_grant_manager,
)
from app.models import LibraryBookMetadata
from app.models.library import LibraryOperation
from app.modules.automation.application.refresh import RefreshMetadataChange
from app.modules.automation.domain.access import AutomationAccessError
from app.modules.automation.infrastructure.models import AutomationReceiptRow
from app.modules.library.public import MetadataPatchError
from tests.integration.modules.automation.test_file_reads import file_access, opf
from tests.integration.modules.automation.test_metadata_patches import change


def refresh_request(db, access):
    catalog = build_automation_catalog(db)
    observed = catalog.observe_file_metadata(access, "allowed-node", "sidecar", None)
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    return RefreshMetadataChange(
        "book",
        "allowed",
        schema["expected_revision"],
        "allowed-node",
        "sidecar",
        ("title", "author"),
        observed.file_revision,
        "patch",
    )


def test_refresh_explicit_source_records_provenance_and_replays_without_reading(
    db_session, tmp_path, monkeypatch
):
    access, root = file_access(db_session, tmp_path)
    source = root / "allowed/metadata.opf"
    source.write_bytes(opf())
    request = refresh_request(db_session, access)
    commands = build_automation_writes(db_session)
    before = source.read_bytes()
    outcome = commands.refresh_metadata(access, "refresh", (request,))
    assert outcome["updated"] == 1
    assert db_session.get(LibraryBookMetadata, "allowed").title == "文件标题"
    assert db_session.get(LibraryBookMetadata, "allowed").author == "作者"
    assert source.read_bytes() == before
    log = db_session.get(LibraryOperation, outcome["operation_id"])
    assert '"source": "sidecar"' in log.payload_json
    assert request.expected_file_revision in log.payload_json
    source.write_bytes(opf("New content after completion"))

    def never_read(*args, **kwargs):
        pytest.fail("completed request replay read a new file")

    monkeypatch.setattr(commands._catalog.file_metadata, "read", never_read)
    assert commands.refresh_metadata(access, "refresh", (request,)) == outcome


def test_refresh_rejects_changed_source_and_unrelated_target(db_session, tmp_path):
    access, root = file_access(db_session, tmp_path)
    source = root / "allowed/metadata.opf"
    source.write_bytes(opf())
    request = refresh_request(db_session, access)
    source.write_bytes(opf("A changed file"))
    commands = build_automation_writes(db_session)
    with pytest.raises(AutomationAccessError, match="SOURCE_CHANGED"):
        commands.refresh_metadata(access, "changed", (request,))
    with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
        commands.refresh_metadata(
            access, "unrelated", (replace(request, target_id="secret"),)
        )
    assert db_session.get(LibraryBookMetadata, "allowed").title == "二毛"
    assert list(db_session.scalars(select(AutomationReceiptRow))) == []


@pytest.mark.parametrize("interruption", ["metadata", "revoke"])
def test_changes_during_file_read_are_checked_before_database_commit(
    db_session, tmp_path, monkeypatch, interruption
):
    access, root = file_access(db_session, tmp_path)
    (root / "allowed/metadata.opf").write_bytes(opf())
    request = refresh_request(db_session, access)
    commands = build_automation_writes(db_session)
    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    original = commands._catalog.file_metadata.read

    def read_and_change(*args, **kwargs):
        observed = original(*args, **kwargs)
        with factory() as other:
            if interruption == "metadata":
                patch = change(other, access, fields={"title": "Concurrent winner"})
                build_automation_writes(other).update_metadata(
                    access, "winner", (patch,)
                )
            else:
                build_grant_manager(other).revoke(
                    user_id=access.user_id, grant_id=access.grant_id
                )
        return observed

    monkeypatch.setattr(commands._catalog.file_metadata, "read", read_and_change)
    with pytest.raises(
        (AutomationAccessError, MetadataPatchError), match="CONFLICT|UNAUTHORIZED"
    ):
        commands.refresh_metadata(access, "interrupted", (request,))
    assert db_session.get(LibraryBookMetadata, "allowed").title == (
        "Concurrent winner" if interruption == "metadata" else "二毛"
    )
    assert (
        db_session.scalar(
            select(AutomationReceiptRow).where(
                AutomationReceiptRow.request_id == "interrupted"
            )
        )
        is None
    )
