import pytest

from app.models import Library
from app.modules.library.application.file_move_plans import (
    MoveActor,
    PrepareFileMovePlan,
)
from app.modules.library.domain.file_moves import FileMoveError, MoveRequest
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from tests.integration.modules.automation.test_file_reads import file_access


def test_scoped_complete_directory_plan_preserves_identity_and_is_pure(
    db_session, tmp_path
):
    access, root = file_access(db_session, tmp_path)
    db_session.get(Library, "test-library").organization_mode = "VOLUMES"
    db_session.commit()
    (root / "allowed/metadata.opf").write_bytes(b"keep exactly")
    actor = MoveActor(
        access.user_id, access.grant_id, access.permissions.library_ids, False
    )
    topology = SqlAlchemyMoveTopology(db_session)
    prepare = PrepareFileMovePlan(
        topology, AnchoredMoveInspection(), lambda: 1000, lambda: "plan"
    )
    source = topology.source("allowed-node", actor.library_ids)
    plan = prepare.execute(
        actor, (MoveRequest("allowed-node", "test-library", "renamed"),)
    )
    assert plan.moves[0].source.book_ids == ("allowed",)
    assert plan.moves[0].source.revision == source.revision
    assert plan.moves[0].inventory.byte_count == 12
    assert (root / "allowed/metadata.opf").read_bytes() == b"keep exactly"
    assert not (root / "renamed").exists()
    with pytest.raises(FileMoveError, match="BOOK_OWNERSHIP_WOULD_CHANGE"):
        prepare.execute(
            actor, (MoveRequest("allowed-node", "test-library", "group/book"),)
        )
    with pytest.raises(FileMoveError, match="RESOURCE_NOT_FOUND"):
        topology.source("secret-node", actor.library_ids)
    # Layout configuration is part of the frozen source version.
    db_session.get(Library, "test-library").organization_mode = "FLAT"
    db_session.commit()
    assert (
        topology.source("allowed-node", actor.library_ids).revision != source.revision
    )
