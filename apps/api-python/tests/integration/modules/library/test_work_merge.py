from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.models.organize import OrganizeJob, OrganizePolicy

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


def _login(client: TestClient, db: Session) -> User:
    user = User(
        email="merge@example.com",
        name="Merge Admin",
        password_hash=hash_password("MergePassword123!"),
        role="admin",
        can_manage_system=True,
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "MergePassword123!"},
    )
    assert response.status_code == 200
    return user


def _login_member(client: TestClient, db: Session) -> User:
    user = User(
        email="merge-member@example.com",
        name="Merge Member",
        password_hash=hash_password("MergePassword123!"),
        role="member",
        can_manage_system=False,
        can_view_manual_imports=True,
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "MergePassword123!"},
    )
    assert response.status_code == 200
    return user


def _seed(db: Session) -> tuple[LibraryWork, LibraryWork, list[LibraryVolume]]:
    first = LibraryWork(
            library_id="test-library", 
        title="星海纪行 2",
        normalized_title="星海纪行 2",
        author="林川",
        normalized_author="林川",
        description="第二卷",
        publication_status="ONGOING",
        tracking_status="TRACKING",
        tags=json.dumps(["科幻", "收藏"], ensure_ascii=False),
        merge_key="merge-first",
    )
    second = LibraryWork(
            library_id="test-library", 
        title="星海纪行 1",
        normalized_title="星海纪行 1",
        author="林川",
        normalized_author="林川",
        tags=json.dumps(["科幻", "冒险"], ensure_ascii=False),
        merge_key="merge-second",
    )
    db.add_all([first, second])
    db.flush()
    media = [
        LibraryMediaVersion(work_id=first.id, media_kind="EBOOK"),
        LibraryMediaVersion(work_id=first.id, media_kind="COMIC"),
        LibraryMediaVersion(work_id=second.id, media_kind="EBOOK"),
        LibraryMediaVersion(work_id=second.id, media_kind="AUDIOBOOK"),
    ]
    db.add_all(media)
    db.flush()
    volumes = [
        LibraryVolume(
            media_version_id=media[0].id,
            title="电子书第二卷",
            volume_index=2,
            sort_order=0,
            format="EPUB",
            resource_key="merge-ebook-2",
            import_status="IMPORTED",
            cover_path="covers/ebook-2.jpg",
            cover_status="READY",
        ),
        LibraryVolume(
            media_version_id=media[1].id,
            title="漫画卷",
            sort_order=0,
            format="CBZ",
            resource_key="merge-comic",
            import_status="IMPORTED",
        ),
        LibraryVolume(
            media_version_id=media[2].id,
            title="电子书第一卷",
            volume_index=1,
            sort_order=0,
            format="EPUB",
            resource_key="merge-ebook-1",
            import_status="IMPORTED",
        ),
        LibraryVolume(
            media_version_id=media[3].id,
            title="有声卷",
            sort_order=0,
            format="M4B",
            resource_key="merge-audio",
            import_status="IMPORTED",
        ),
    ]
    db.add_all(volumes)
    db.commit()
    return first, second, volumes


def test_preview_merge_creates_a_new_non_reversible_work(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    first, second, volumes = _seed(db_session)

    preview = client.post(
        "/api/works/merge/preview", json={"workIds": [first.id, second.id]}
    )
    assert preview.status_code == 200
    preview_data = preview.json()["data"]
    assert [group["mediaKind"] for group in preview_data["mediaGroups"]] == [
        "EBOOK",
        "COMIC",
        "AUDIOBOOK",
    ]
    assert [volume["id"] for volume in preview_data["mediaGroups"][0]["volumes"]] == [
        volumes[2].id,
        volumes[0].id,
    ]
    assert preview_data["suggestedMetadata"]["tags"] == ["科幻", "收藏", "冒险"]

    response = client.post(
        "/api/works/merge",
        json={
            "workIds": [first.id, second.id],
            "metadata": {
                "title": "星海纪行",
                "author": "林川",
                "description": "合并后的作品",
                "seriesName": "星海系列",
                "seriesIndex": 1,
                "tags": ["科幻", "冒险"],
            },
            "coverVolumeId": volumes[0].id,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["workId"] not in {first.id, second.id}
    assert result["operation"]["undoAvailable"] is False
    db_session.expire_all()
    assert db_session.get(LibraryWork, first.id) is None
    assert db_session.get(LibraryWork, second.id) is None
    merged = db_session.get(LibraryWork, result["workId"])
    assert merged is not None
    assert merged.title == "星海纪行"
    assert merged.cover_path == "covers/ebook-2.jpg"
    merged_media = list(
        db_session.scalars(
            select(LibraryMediaVersion).where(
                LibraryMediaVersion.work_id == result["workId"]
            )
        ).all()
    )
    assert {item.media_kind for item in merged_media} == {
        "EBOOK",
        "COMIC",
        "AUDIOBOOK",
    }
    ebook_id = next(item.id for item in merged_media if item.media_kind == "EBOOK")
    ebook_volumes = list(
        db_session.scalars(
            select(LibraryVolume)
            .where(LibraryVolume.media_version_id == ebook_id)
            .order_by(LibraryVolume.sort_order)
        ).all()
    )
    assert [item.id for item in ebook_volumes] == [volumes[2].id, volumes[0].id]

    undo = client.post(f"/api/library/operations/{result['operation']['id']}/undo")
    assert undo.status_code == 400
    assert undo.json()["error"]["message"] == "该操作不可撤销"


def test_metadata_writeback_policy_enqueues_each_media_kind(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    first, second, volumes = _seed(db_session)
    db_session.add(OrganizePolicy(id="default", write_metadata_to_files=True))
    db_session.commit()

    response = client.post(
        "/api/works/merge",
        json={
            "workIds": [first.id, second.id],
            "metadata": {"title": "不可撤销合并", "author": "林川", "tags": []},
            "coverVolumeId": volumes[0].id,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()["data"]
    assert result["operation"]["undoAvailable"] is False
    # OPF tasks are ephemeral and may be drained before the response is built.
    assert result["metadataWritebacks"] == []
    undo = client.post(f"/api/library/operations/{result['operation']['id']}/undo")
    assert undo.status_code == 400
    assert undo.json()["error"]["message"] == "该操作不可撤销"


def test_merge_rejects_an_active_background_job(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    first, second, volumes = _seed(db_session)
    db_session.add(
        OrganizeJob(
            work_id=first.id,
            volume_id=volumes[0].id,
            media_version_id=volumes[0].media_version_id,
            trigger="MANUAL",
            status="RUNNING",
            issue_codes="[]",
        )
    )
    db_session.commit()

    response = client.post(
        "/api/works/merge",
        json={
            "workIds": [first.id, second.id],
            "metadata": {"title": "后台处理中", "author": "林川", "tags": []},
            "coverVolumeId": volumes[0].id,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "WORK_MERGE_IN_PROGRESS"
    db_session.expire_all()
    assert db_session.get(LibraryWork, first.id) is not None
    assert db_session.get(LibraryWork, second.id) is not None


def test_merge_does_not_reassign_unresolved_organize_jobs(
    client: TestClient, db_session: Session
) -> None:
    _login(client, db_session)
    first, second, volumes = _seed(db_session)
    jobs = [
        OrganizeJob(
            work_id=first.id,
            volume_id=volumes[0].id,
            media_version_id=volumes[0].media_version_id,
            trigger="MANUAL",
            status="REVIEWING",
            issue_codes="[]",
        ),
        OrganizeJob(
            work_id=second.id,
            volume_id=volumes[2].id,
            media_version_id=volumes[2].media_version_id,
            trigger="MANUAL",
            status="FAILED",
            issue_codes="[]",
        ),
    ]
    db_session.add_all(jobs)
    db_session.commit()
    job_ids = [job.id for job in jobs]

    response = client.post(
        "/api/works/merge",
        json={
            "workIds": [first.id, second.id],
            "metadata": {"title": "合并整理任务", "author": "林川", "tags": []},
            "coverVolumeId": volumes[0].id,
        },
    )

    assert response.status_code == 200, response.text
    merged_work_id = response.json()["data"]["workId"]
    db_session.expire_all()
    remaining_jobs = [
        job
        for job_id in job_ids
        if (job := db_session.get(OrganizeJob, job_id)) is not None
    ]
    assert all(job.work_id in {first.id, second.id} for job in remaining_jobs)
    assert db_session.scalar(
        select(OrganizeJob.id).where(OrganizeJob.work_id == merged_work_id)
    ) is None


def test_merge_preview_requires_system_management_permission(
    client: TestClient, db_session: Session
) -> None:
    _login_member(client, db_session)
    first, second, _volumes = _seed(db_session)
    response = client.post(
        "/api/works/merge/preview", json={"workIds": [first.id, second.id]}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SYSTEM_MANAGER_REQUIRED"
