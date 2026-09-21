from dataclasses import replace

import pytest

from app.bootstrap.automation import build_grant_manager
from app.core.auth import create_session
from app.models import User
from app.modules.automation.application.writeback_plans import StandardWriteSelection
from app.modules.metadata.infrastructure.standard_writeback_store import (
    SqlAlchemyStandardWritePlans,
)
from tests.integration.modules.automation.test_management_http import ORIGIN, sign_in
from tests.integration.modules.automation.test_move_execution import prepare
from tests.integration.modules.automation.test_writeback_plans import setup


def cookie(client, db):
    _, token = create_session(db, "mcp-owner")
    db.commit()
    client.cookies.set("shuku_session", token)


def writeback(db, tmp_path):
    access, root, catalog, planner = setup(db, tmp_path)
    grant = build_grant_manager(db).create(
        user_id=access.user_id, name="writeback", permissions=access.permissions
    )
    access = replace(access, grant_id=grant.grant.id)
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    plan = planner.execute(
        access,
        (
            StandardWriteSelection(
                "book",
                "allowed",
                schema["expected_revision"],
                "allowed-node",
                "opf",
                frozenset({"title"}),
            ),
        ),
    )
    store = SqlAlchemyStandardWritePlans(db, queue_capacity=20)
    store.save(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db.commit()
    return access.grant_id, root


@pytest.mark.parametrize("kind", ["file_move", "metadata_writeback"])
def test_cookie_history_and_cancel_after_revocation(client, db_session, tmp_path, kind):
    if kind == "file_move":
        actor, root, _ = prepare(db_session, tmp_path)
        grant_id = actor.grant_id
    else:
        grant_id, root = writeback(db_session, tmp_path)
    cookie(client, db_session)
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    response = client.get("/api/automation/operations")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    operation = response.json()["data"]["operations"][0]
    assert operation["kind"] == kind
    assert operation["operation_id"] == "operation"
    assert operation["targets"][0]["relative_path"].startswith("allowed")
    assert str(root) not in response.text
    assert client.post("/api/automation/operations/operation/cancel").status_code == 403
    assert (
        client.delete(f"/api/automation/grants/{grant_id}", headers=ORIGIN).status_code
        == 200
    )
    assert (
        len(client.get("/api/automation/operations").json()["data"]["operations"]) == 1
    )
    cancelled = client.post(
        "/api/automation/operations/operation/cancel", headers=ORIGIN
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["operation"]["cancel_requested"]
    assert before == {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    sign_in(client, db_session, "other", admin=True)
    assert client.get("/api/automation/operations").json()["data"]["operations"] == []
    assert (
        client.post(
            "/api/automation/operations/operation/cancel", headers=ORIGIN
        ).status_code
        == 404
    )
    client.cookies.clear()
    assert (
        client.get(
            "/api/automation/operations", headers={"Authorization": "Bearer unrelated"}
        ).status_code
        == 401
    )


def test_current_account_authority_loss_hides_owned_operation(
    client, db_session, tmp_path
):
    prepare(db_session, tmp_path)
    cookie(client, db_session)
    user = db_session.get(User, "mcp-owner")
    user.role = "member"
    user.can_manage_system = False
    db_session.commit()
    assert client.get("/api/automation/operations").json()["data"]["operations"] == []
    assert client.post(
        "/api/automation/operations/operation/cancel", headers=ORIGIN
    ).status_code in {403, 404}
