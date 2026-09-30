"""Filesystem inventory must run after the topology read releases its transaction."""

from contextlib import nullcontext

from app.modules.library.application.file_deletions import (
    DeletePlan,
    DeleteTarget,
    FileDeletions,
)
from app.modules.library.application.file_move_plans import MoveSource
from app.modules.library.domain.file_moves import MoveInventory


def test_delete_plan_releases_topology_read_before_inventory(tmp_path):
    active = False

    def topology(node_id, libraries):
        nonlocal active
        active = True
        return MoveSource(node_id, "library", "source", tmp_path, "revision", ("book",))

    class Files:
        def inspect(self, source):
            assert not active
            return MoveInventory((), 0, 0)

    class Store:
        def save(self, plan):
            assert not active

    class UnitOfWork:
        def rollback(self):
            nonlocal active
            active = False

        def commit(self):
            assert not active

    use_case = FileDeletions(
        topology,
        Store(),
        UnitOfWork(),
        Files(),
        lambda source: "task",
        lambda task_id: "SUCCEEDED",
        lambda: 1,
        lambda: "plan",
        None,
    )
    assert use_case.plan("user", "grant", frozenset({"library"}), ("node",)).id == "plan"


def test_delete_execution_releases_read_transactions_before_file_access(tmp_path):
    active = False
    source = MoveSource("node", "library", "source", tmp_path, "revision", ("book",))
    plan = DeletePlan(
        "plan", "user", "grant", 1, 1000,
        (DeleteTarget(source, MoveInventory((), 0, 0)),), execution_version=2,
    )

    class Store:
        def load(self, plan_id, user_id, grant_id):
            nonlocal active
            active = True
            return plan

        def save(self, saved):
            nonlocal active
            active = True

    class UnitOfWork:
        def rollback(self):
            nonlocal active
            active = False

        def commit(self):
            nonlocal active
            active = False

    class Files:
        def lock(self, plan_id):
            return nullcontext()

        def validate(self, target):
            assert not active

        def delete(self, target):
            assert not active

    class Authorization:
        def library_ids(self):
            nonlocal active
            active = True
            return frozenset({"library"})

    def topology(node_id, libraries):
        nonlocal active
        active = True
        return source

    use_case = FileDeletions(
        topology, Store(), UnitOfWork(), Files(),
        lambda item: "task", lambda task_id: "SUCCEEDED",
        lambda: 2, lambda: "new", None,
    )
    result = use_case.execute("plan", "user", "grant", Authorization())
    assert result.targets[0].stage == "COMPLETED"
