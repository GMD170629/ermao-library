from __future__ import annotations

import json
from typing import TYPE_CHECKING

from app.bootstrap.system import record_system_event
from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import (
    LibraryFacet,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import OrganizeRun
from app.services.library_management import sync_work_facets
from sqlalchemy import select

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


ADMIN_EMAIL = "openapi-regression@example.com"
ADMIN_PASSWORD = "OpenApiRegression123!"


def _login_admin(client: TestClient, db_session: Session) -> User:
    user = User(
        email=ADMIN_EMAIL,
        name="OpenAPI Regression",
        password_hash=hash_password(ADMIN_PASSWORD),
        role="admin",
        can_manage_system=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    response = client.post(
        "/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return user


def _seed_library(db_session: Session) -> tuple[LibraryWork, LibraryWork]:
    target_work = LibraryWork(
            library_id="test-library", 
        title="OpenAPI 回归作品",
        normalized_title="openapi 回归作品",
        author="测试作者",
        normalized_author="测试作者",
        tags=json.dumps(["科幻", "收藏", "待删除"], ensure_ascii=False),
        merge_key="openapi-regression-target",
    )
    source_work = LibraryWork(
            library_id="test-library", 
        title="OpenAPI 回归作品",
        normalized_title="openapi 回归作品",
        author="测试作者",
        normalized_author="测试作者",
        tags=json.dumps(["科幻小说"], ensure_ascii=False),
        merge_key="openapi-regression-source",
    )
    db_session.add_all([target_work, source_work])
    db_session.flush()
    target_media = LibraryMediaVersion(work_id=target_work.id, media_kind="EBOOK")
    source_media = LibraryMediaVersion(work_id=source_work.id, media_kind="EBOOK")
    db_session.add_all([target_media, source_media])
    db_session.flush()
    db_session.add_all(
        [
            LibraryVolume(
                media_version_id=target_media.id,
                title="初版",
                format="EPUB",
                resource_key="openapi-target-volume",
                import_status="IMPORTED",
            ),
            LibraryVolume(
                media_version_id=source_media.id,
                title="来源版",
                format="EPUB",
                resource_key="openapi-source-volume",
                import_status="IMPORTED",
            ),
        ]
    )
    db_session.commit()
    db_session.refresh(target_work)
    db_session.refresh(source_work)
    sync_work_facets(db_session, target_work.id)
    sync_work_facets(db_session, source_work.id)
    return target_work, source_work


def _facet_id(db_session: Session, name: str) -> str:
    facet = db_session.scalar(
        select(LibraryFacet).where(
            LibraryFacet.kind == "TAG",
            LibraryFacet.name == name,
        )
    )
    assert facet is not None
    return facet.id


def test_management_events_and_overview_accept_real_event_metadata(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _login_admin(client, db_session)
    metadata = {
        "sourceFormat": "TXT",
        "skipped": [],
        "nested": {"ids": ["work-a", "work-b"], "ratio": None},
    }
    record_system_event(
        db_session,
        source="library",
        action="IMPORT_COMPLETED",
        level="info",
        message="OpenAPI metadata regression",
        actor_type="user",
        actor_id=user.id,
        metadata=metadata,
    )
    db_session.commit()

    events_response = client.get("/api/management/events")
    assert events_response.status_code == 200
    assert events_response.json()["data"]["events"][0]["metadata"] == metadata

    overview_response = client.get("/api/management/overview")
    assert overview_response.status_code == 200
    assert overview_response.json()["data"]["recentEvents"][0]["metadata"] == metadata


def test_library_management_endpoints_return_their_documented_contracts(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    target_work, source_work = _seed_library(db_session)

    facets_response = client.get("/api/library/facets")
    assert facets_response.status_code == 200
    assert set(facets_response.json()["data"]["facets"]) == {
        "author",
        "series",
        "tag",
    }

    categories_response = client.get("/api/library/categories")
    assert categories_response.status_code == 200
    category = categories_response.json()["data"]["categories"][0]
    assert {"aliases", "bookCount"} <= category.keys()

    duplicates_response = client.get("/api/library/duplicates")
    assert duplicates_response.status_code == 200
    duplicates_data = duplicates_response.json()["data"]
    assert {
        "page": 1,
        "pageSize": 20,
        "total": 1,
        "totalPages": 1,
    }.items() <= duplicates_data.items()
    duplicate_group = duplicates_data["groups"][0]
    assert duplicate_group["reasons"] == ["标题与作者规范化后相同"]
    assert {work["id"] for work in duplicate_group["works"]} == {
        target_work.id,
        source_work.id,
    }

    tag_id = _facet_id(db_session, "科幻")
    rename_response = client.patch(
        f"/api/library/categories/{tag_id}",
        json={"name": "硬科幻"},
    )
    assert rename_response.status_code == 200
    assert rename_response.json()["data"]["name"] == "硬科幻"
    db_session.expire_all()
    renamed_tag = db_session.get(LibraryFacet, tag_id)
    assert renamed_tag is not None
    assert renamed_tag.name == "硬科幻"

    source_tag_id = _facet_id(db_session, "科幻小说")
    merge_response = client.post(
        "/api/library/categories/merge",
        json={"targetId": tag_id, "sourceIds": [source_tag_id]},
    )
    assert merge_response.status_code == 200
    assert merge_response.json()["data"]["targetId"] == tag_id
    db_session.expire_all()
    assert db_session.get(LibraryFacet, source_tag_id) is None
    merged_target = db_session.get(LibraryFacet, tag_id)
    assert merged_target is not None
    assert "科幻小说" in json.loads(merged_target.aliases)

    delete_tag_id = _facet_id(db_session, "待删除")
    delete_response = client.delete(f"/api/library/categories/{delete_tag_id}")
    assert delete_response.status_code == 200
    delete_operation = delete_response.json()["data"]["operation"]
    db_session.expire_all()
    assert db_session.get(LibraryFacet, delete_tag_id) is None
    target_after_delete = db_session.get(LibraryWork, target_work.id)
    assert target_after_delete is not None
    assert "待删除" not in json.loads(target_after_delete.tags)

    operations_response = client.get("/api/library/operations")
    assert operations_response.status_code == 200
    operation = operations_response.json()["data"]["operations"][0]
    assert "payloadJson" not in operation
    assert "inverseJson" not in operation
    assert "userId" not in operation

    undo_response = client.post(
        f"/api/library/operations/{delete_operation['id']}/undo"
    )
    assert undo_response.status_code == 200
    assert undo_response.json()["data"]["restored"] is True
    db_session.expire_all()
    assert db_session.get(LibraryFacet, delete_tag_id) is not None
    target_after_undo = db_session.get(LibraryWork, target_work.id)
    assert target_after_undo is not None
    assert "待删除" in json.loads(target_after_undo.tags)

    volume = db_session.scalar(
        select(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(LibraryMediaVersion.work_id == target_work.id)
    )
    assert volume is not None
    retired_edition_response = client.patch(
        f"/api/works/{target_work.id}/editions/{volume.media_version_id}",
        json={"versionName": "修订版"},
    )
    assert retired_edition_response.status_code == 410

    duplicate_response = client.post(
        "/api/library/duplicates/merge",
        json={
            "targetWorkId": target_work.id,
            "sourceWorkIds": [source_work.id],
        },
    )
    assert duplicate_response.status_code == 200
    duplicate_payload = duplicate_response.json()["data"]
    assert duplicate_payload["targetWorkId"] == target_work.id
    assert duplicate_payload["sourceWorkIds"] == [source_work.id]
    db_session.expire_all()
    merged_source = db_session.get(LibraryWork, source_work.id)
    assert merged_source is None
    moved_volume = db_session.scalar(
        select(LibraryVolume).where(
            LibraryVolume.resource_key == "openapi-source-volume"
        )
    )
    assert moved_volume is not None
    moved_media = db_session.get(LibraryMediaVersion, moved_volume.media_version_id)
    assert moved_media is not None
    assert moved_media.work_id == target_work.id
    target_media = db_session.scalars(
        select(LibraryMediaVersion).where(
            LibraryMediaVersion.work_id == target_work.id,
            LibraryMediaVersion.media_kind == "EBOOK",
        )
    ).all()
    assert len(target_media) == 1
    target_volume_ids = set(
        db_session.scalars(
            select(LibraryVolume.id).where(
                LibraryVolume.media_version_id == target_media[0].id
            )
        )
    )
    assert target_volume_ids == {volume.id, moved_volume.id}


def test_organize_runs_normalize_legacy_or_invalid_scope(
    client: TestClient,
    db_session: Session,
) -> None:
    _login_admin(client, db_session)
    db_session.add_all(
        [
            OrganizeRun(
                id="legacy-empty-scope",
                trigger="MANUAL",
                scope_json="{}",
                status="COMPLETED",
            ),
            OrganizeRun(
                id="legacy-invalid-scope",
                trigger="MANUAL",
                scope_json="not-json",
                status="COMPLETED",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/organize/runs")
    assert response.status_code == 200
    for run in response.json()["data"]["runs"]:
        assert run["scope"] == {
            "workIds": [],
            "rules": {"missingMetadata": True, "unrecognized": True},
        }
