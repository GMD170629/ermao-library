from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.auth import hash_password
from app.models.auth import User
from app.models.organize import MetadataOpfQueueState, OrganizePolicy
from tests.support.sqlalchemy import StatementRecorder

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


ADMIN_EMAIL = "queue-contract@example.com"
ADMIN_PASSWORD = "QueueContract123!"


def _login_admin(client: TestClient, db_session: Session) -> None:
    db_session.add(
        User(
            email=ADMIN_EMAIL,
            name="Queue Contract",
            password_hash=hash_password(ADMIN_PASSWORD),
            role="admin",
            can_manage_system=True,
        )
    )
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200


def test_metadata_opf_status_exposes_pending_preparations(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    db_session.add(
        MetadataOpfQueueState(
            id="default",
            pending_targets=2,
            pending_preparations=3,
            updated_at=datetime.now(UTC),
        )
    )
    db_session.commit()

    response = client.get("/api/metadata/opf-sync/status")

    assert response.status_code == 200
    assert response.json()["data"]["queue"] == {
        "pendingTargets": 2,
        "pendingPreparations": 3,
        "capacity": 50_000,
        "utilization": 2 / 50_000,
    }


def test_fresh_organize_policy_get_is_stable_and_read_only(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    engine = db_session.get_bind()

    with StatementRecorder(engine) as recorder:
        recorder.reset_after_warmup()
        first = client.get("/api/organize/policy")
        second = client.get("/api/organize/policy")

    assert first.status_code == 200
    assert second.status_code == 200
    first_policy = first.json()["data"]["policy"]
    assert first_policy == second.json()["data"]["policy"]
    assert first_policy["updatedAt"] == "1970-01-01T00:00:00Z"
    assert recorder.dml_count == 0
    assert (
        db_session.scalar(select(func.count()).select_from(OrganizePolicy)) or 0
    ) == 0


def test_organize_policy_update_persists_explicit_request_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)

    response = client.put(
        "/api/organize/policy",
        json={
            "enabled": True,
            "scheduleMode": "INTERVAL",
            "intervalMinutes": 15,
            "rules": {"unrecognized": False, "missingMetadata": True},
        },
    )

    assert response.status_code == 200
    policy = response.json()["data"]["policy"]
    assert policy["enabled"] is True
    assert policy["scheduleMode"] == "INTERVAL"
    assert policy["intervalMinutes"] == 15
    assert policy["rules"] == {
        "unrecognized": False,
        "missingMetadata": True,
    }
    persisted = db_session.get(OrganizePolicy, "default")
    assert persisted is not None
    assert persisted.enabled is True
    assert persisted.interval_minutes == 15


def test_release_title_parser_accepts_documented_json_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)

    response = client.post(
        "/api/tracking/release-title-parser",
        json={"title": "Example Vol.3 Ch.4"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["parsed"] == {
        "title": "Example Vol.3 Ch.4",
        "volume": 3.0,
        "chapter": 4.0,
    }


def test_consumed_request_bodies_are_documented_in_openapi(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    operations = {
        ("put", "/api/metadata/provider-pipelines/{media_kind}"),
        ("put", "/api/metadata/providers/{provider_id}"),
        ("patch", "/api/metadata/providers/{provider_id}"),
        ("put", "/api/organize/policy"),
        ("post", "/api/books/import"),
        ("post", "/api/tracking/release-title-parser"),
        ("post", "/api/download-tasks"),
        ("put", "/api/download-tasks/{task_id}"),
        ("post", "/api/sources"),
        ("put", "/api/sources/{source_id}"),
        ("patch", "/api/sources/{source_id}"),
        ("post", "/api/sources/{source_id}/search"),
        ("post", "/api/source-search-records"),
        ("post", "/api/source-search-records/create-download-task"),
        ("put", "/api/source-search-records/{record_id}"),
        (
            "post",
            "/api/source-search-records/{record_id}/create-download-task",
        ),
        ("put", "/api/email-settings"),
        ("post", "/api/email-settings/smtp-test"),
        ("put", "/api/kindle-settings"),
        ("post", "/api/kindle-send-tasks"),
    }

    missing = {
        (method, path)
        for method, path in operations
        if "requestBody" not in schema["paths"][path][method]
    }
    assert missing == set()


def test_empty_bodies_never_escape_as_internal_errors(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    requests = (
        ("PUT", "/api/metadata/provider-pipelines/EBOOK"),
        ("PUT", "/api/metadata/providers/douban"),
        ("PATCH", "/api/metadata/providers/douban"),
        ("PUT", "/api/organize/policy"),
        ("POST", "/api/books/import"),
        ("POST", "/api/tracking/release-title-parser"),
        ("POST", "/api/download-tasks"),
        ("PUT", "/api/download-tasks/missing"),
        ("POST", "/api/sources"),
        ("PUT", "/api/sources/missing"),
        ("PATCH", "/api/sources/missing"),
        ("POST", "/api/sources/missing/search"),
        ("POST", "/api/source-search-records"),
        ("POST", "/api/source-search-records/create-download-task"),
        ("PUT", "/api/source-search-records/missing"),
        (
            "POST",
            "/api/source-search-records/missing/create-download-task",
        ),
        ("PUT", "/api/email-settings"),
        ("POST", "/api/email-settings/smtp-test"),
        ("PUT", "/api/kindle-settings"),
        ("POST", "/api/kindle-send-tasks"),
    )

    responses = [client.request(method, path, content=b"") for method, path in requests]

    assert all(response.status_code < 500 for response in responses), [
        (request, response.status_code, response.text)
        for request, response in zip(requests, responses, strict=True)
        if response.status_code >= 500
    ]
