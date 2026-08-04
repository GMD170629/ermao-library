import json

from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import LibraryMediaVersion, LibraryVolume
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.services.metadata_provider_registry import (
    enabled_metadata_provider_ids,
    get_metadata_provider,
    list_metadata_provider_pipelines,
    list_metadata_providers,
    update_metadata_provider,
    update_metadata_provider_pipeline,
)
from app.services.organize_scheduler import (
    create_organize_run,
    delete_organize_job,
    get_organize_policy,
    organize_candidate_summary,
    process_organize_schedule_tick,
    recognize_organize_job,
    update_organize_policy,
)
from app.services.organize_service import merge_works
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def _insert_work(
    db: Session,
    work_id: str,
    *,
    created_at: str = "2026-07-21T00:00:00+00:00",
    with_media_version: bool = True,
) -> None:
    db.execute(
        text(
            """
            INSERT INTO `LibraryWork`
                (`id`, `origin`, `title`, `normalizedTitle`, `author`, `normalizedAuthor`,
                 `tags`, `metadataQuality`, `organizeStatus`, `hidden`, `organized`,
                 `createdAt`, `updatedAt`)
            VALUES
                (:id, 'MANUAL', :title, :title, '未知作者', '未知作者', '[]', 0,
                 'UNASSESSED', 0, 0, :created_at, :created_at)
            """
        ),
        {"id": work_id, "title": f"测试作品 {work_id}", "created_at": created_at},
    )
    db.commit()
    if with_media_version:
        _insert_volume(
            db,
            work_id=work_id,
            media_version_id=f"media-{work_id}",
            media_kind="EBOOK",
            volume_id=f"volume-{work_id}",
            volume_format="EPUB",
        )


def _insert_volume(
    db: Session,
    *,
    work_id: str,
    media_version_id: str,
    media_kind: str,
    volume_id: str,
    volume_format: str,
    sort_order: int = 0,
) -> None:
    db.add(
        LibraryMediaVersion(
            id=media_version_id,
            work_id=work_id,
            media_kind=media_kind,
        )
    )
    db.add(
        LibraryVolume(
            id=volume_id,
            media_version_id=media_version_id,
            title=f"卷册 {volume_id}",
            format=volume_format,
            resource_key=f"resource:{volume_id}",
            sort_order=sort_order,
        )
    )
    db.commit()


def test_organize_jobs_target_the_first_stably_ordered_volume(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "volume-target-work", with_media_version=False)
            _insert_volume(
                db,
                work_id="volume-target-work",
                media_version_id="ebook-media",
                media_kind="EBOOK",
                volume_id="second-volume",
                volume_format="PDF",
                sort_order=20,
            )
            db.add(
                LibraryVolume(
                    id="first-volume",
                    media_version_id="ebook-media",
                    title="第一卷",
                    format="EPUB",
                    resource_key="resource:first-volume",
                    sort_order=10,
                )
            )
            db.commit()
            _insert_volume(
                db,
                work_id="volume-target-work",
                media_version_id="audio-media",
                media_kind="AUDIOBOOK",
                volume_id="audio-volume",
                volume_format="MP3",
                sort_order=0,
            )

            create_organize_run(db, work_ids=["volume-target-work"])

            job = db.scalars(
                select(OrganizeJob).where(OrganizeJob.work_id == "volume-target-work")
            ).one()
            lookup = db.scalars(
                select(MetadataLookupTask).where(
                    MetadataLookupTask.organize_job_id == job.id
                )
            ).one()
            assert job.volume_id == "first-volume"
            assert lookup.volume_id == "first-volume"
    finally:
        engine.dispose()


def test_merge_works_coalesces_media_versions_and_appends_volumes(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "target-work", with_media_version=False)
            _insert_work(db, "source-work", with_media_version=False)
            _insert_volume(
                db,
                work_id="target-work",
                media_version_id="target-ebook",
                media_kind="EBOOK",
                volume_id="target-epub",
                volume_format="EPUB",
                sort_order=7,
            )
            _insert_volume(
                db,
                work_id="source-work",
                media_version_id="source-ebook",
                media_kind="EBOOK",
                volume_id="source-pdf",
                volume_format="PDF",
                sort_order=1,
            )
            _insert_volume(
                db,
                work_id="source-work",
                media_version_id="source-comic",
                media_kind="COMIC",
                volume_id="source-comic-volume",
                volume_format="CBZ",
                sort_order=3,
            )

            merge_works(db, "source-work", "target-work")

            versions = db.scalars(
                select(LibraryMediaVersion)
                .where(LibraryMediaVersion.work_id == "target-work")
                .order_by(LibraryMediaVersion.media_kind)
            ).all()
            assert [(row.id, row.media_kind) for row in versions] == [
                ("source-comic", "COMIC"),
                ("target-ebook", "EBOOK"),
            ]
            assert not db.scalars(
                select(LibraryMediaVersion).where(
                    LibraryMediaVersion.work_id == "source-work"
                )
            ).all()
            source_pdf = db.get(LibraryVolume, "source-pdf")
            assert source_pdf is not None
            assert source_pdf.media_version_id == "target-ebook"
            assert source_pdf.sort_order == 8
            assert db.get(LibraryVolume, "source-comic-volume").media_version_id == (
                "source-comic"
            )
    finally:
        engine.dispose()


def test_manual_run_is_the_only_component_that_creates_queue_items(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "manual-work")
            assert db.execute(text("SELECT COUNT(*) FROM `OrganizeJob`")).scalar() == 0
            assert organize_candidate_summary(db)["total"] == 1

            update_metadata_provider(db, "douban", {"enabled": True})
            run = create_organize_run(db, work_ids=["manual-work"])

            assert run["trigger"] == "MANUAL"
            assert run["queuedCount"] == 1
            job = (
                db.execute(
                    text("SELECT * FROM `OrganizeJob` WHERE `workId` = 'manual-work'")
                )
                .mappings()
                .one()
            )
            task = (
                db.execute(
                    text(
                        "SELECT * FROM `MetadataLookupTask` WHERE `workId` = 'manual-work'"
                    )
                )
                .mappings()
                .one()
            )
            assert job["status"] == "LOOKUP_PENDING"
            assert job["importTaskId"] is None
            assert json.loads(job["reasonCodes"]) == ["MANUAL_SELECTED"]
            assert json.loads(task["providerOrder"]) == ["douban", "bangumi"]
    finally:
        engine.dispose()


def test_auto_run_on_new_respects_enablement_boundary(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "historical-work", created_at="2020-01-01T00:00:00+00:00")
            policy = update_organize_policy(db, {"autoRunOnNew": True})
            assert policy["autoRunOnNewSince"]
            _insert_work(db, "new-work", created_at="2999-01-01T00:00:00+00:00")

            assert process_organize_schedule_tick(db) == 1
            queued = (
                db.execute(
                    text(
                        "SELECT `workId`, `trigger`, `reasonCodes` FROM `OrganizeJob` ORDER BY `workId`"
                    )
                )
                .mappings()
                .all()
            )
            assert [
                {
                    "workId": item["workId"],
                    "trigger": item["trigger"],
                    "reasonCodes": json.loads(item["reasonCodes"]),
                }
                for item in queued
            ] == [
                {
                    "workId": "new-work",
                    "trigger": "NEW",
                    "reasonCodes": ["UNRECOGNIZED", "MISSING_METADATA"],
                }
            ]
            assert process_organize_schedule_tick(db) == 0
    finally:
        engine.dispose()


def test_interval_schedule_queues_due_candidates_and_advances_next_run(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "scheduled-work")
            update_metadata_provider(db, "douban", {"enabled": True})
            update_organize_policy(
                db, {"enabled": True, "scheduleMode": "INTERVAL", "intervalMinutes": 15}
            )
            db.execute(
                text(
                    "UPDATE `OrganizePolicy` SET `nextRunAt` = '2026-01-01T00:00:00+00:00' WHERE `id` = 'default'"
                )
            )
            db.commit()

            assert process_organize_schedule_tick(db) == 1
            job = (
                db.execute(
                    text(
                        "SELECT `trigger`, `reasonCodes` FROM `OrganizeJob` WHERE `workId` = 'scheduled-work'"
                    )
                )
                .mappings()
                .one()
            )
            assert job["trigger"] == "SCHEDULE"
            assert "UNRECOGNIZED" in json.loads(job["reasonCodes"])
            policy = get_organize_policy(db)
            assert policy["lastScheduledAt"]
            assert str(policy["nextRunAt"]) > str(policy["lastScheduledAt"])
    finally:
        engine.dispose()


def test_unresolved_work_is_not_queued_again_until_recognition_completes(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "unrecognized-work")
            first_run = create_organize_run(db, work_ids=["unrecognized-work"])
            first_job = (
                db.execute(
                    text(
                        "SELECT `id` FROM `OrganizeJob` WHERE `workId` = 'unrecognized-work'"
                    )
                )
                .mappings()
                .one()
            )
            db.execute(
                text(
                    "UPDATE `OrganizeJob` SET `status` = 'FAILED', `summary` = '没有找到匹配结果' "
                    "WHERE `id` = :id"
                ),
                {"id": first_job["id"]},
            )
            db.execute(
                text(
                    "UPDATE `LibraryWork` SET `organized` = 0, `organizeStatus` = 'REVIEWING' "
                    "WHERE `id` = 'unrecognized-work'"
                )
            )
            db.commit()

            update_organize_policy(
                db,
                {"enabled": True, "scheduleMode": "INTERVAL", "intervalMinutes": 15},
            )
            db.execute(
                text(
                    "UPDATE `OrganizePolicy` SET `nextRunAt` = '2026-01-01T00:00:00+00:00' "
                    "WHERE `id` = 'default'"
                )
            )
            db.commit()

            assert organize_candidate_summary(db)["total"] == 0
            assert process_organize_schedule_tick(db) == 0
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM `OrganizeJob` WHERE `workId` = 'unrecognized-work'"
                    )
                ).scalar()
                == 1
            )

            db.execute(
                text(
                    "UPDATE `OrganizeJob` SET `status` = 'COMPLETED' WHERE `id` = :id"
                ),
                {"id": first_job["id"]},
            )
            db.execute(
                text(
                    "UPDATE `LibraryWork` SET `organized` = 1, `organizeStatus` = 'APPLIED' "
                    "WHERE `id` = 'unrecognized-work'"
                )
            )
            db.commit()

            second_run = create_organize_run(db, work_ids=["unrecognized-work"])
            second_job_id = db.execute(
                text(
                    "SELECT `id` FROM `OrganizeJob` WHERE `workId` = 'unrecognized-work' "
                    "AND `status` = 'LOOKUP_PENDING'"
                )
            ).scalar_one()
            redirected_recognition = recognize_organize_job(db, str(first_job["id"]))

            assert first_run["queuedCount"] == 1
            assert second_run["queuedCount"] == 1
            assert redirected_recognition["id"] == second_job_id
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM `OrganizeJob` WHERE `workId` = 'unrecognized-work'"
                    )
                ).scalar()
                == 2
            )
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM `OrganizeJob` WHERE `workId` = 'unrecognized-work' "
                        "AND `status` IN ('LOOKUP_PENDING', 'PENDING', 'QUEUED', 'RUNNING', "
                        "'RETRY_WAIT', 'REVIEWING', 'FAILED')"
                    )
                ).scalar()
                == 1
            )
    finally:
        engine.dispose()


def test_missing_description_alone_does_not_make_an_organized_work_eligible(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "description-only-work")
            db.execute(
                text(
                    "UPDATE `LibraryWork` SET `organized` = 1, `organizeStatus` = 'APPLIED', "
                    "`coverPath` = 'covers/local.jpg' WHERE `id` = 'description-only-work'"
                )
            )
            db.commit()

            summary = organize_candidate_summary(db)

            assert summary["total"] == 0
            assert summary["works"] == []
    finally:
        engine.dispose()


def test_provider_registry_seeds_builtins_and_never_returns_secret_values(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            assert {provider["id"] for provider in list_metadata_providers(db)} == {
                "douban",
                "bangumi",
                "ai",
            }
            updated = update_metadata_provider(
                db,
                "ai",
                {
                    "config": {
                        "baseUrl": "https://example.test/v1",
                        "model": "test-model",
                        "apiKey": "top-secret",
                    },
                    "enabled": True,
                },
            )
            assert "apiKey" not in updated["config"]
            assert updated["configuredSecrets"]["apiKey"] is True
            assert "top-secret" not in json.dumps(
                get_metadata_provider(db, "ai"), ensure_ascii=False
            )
            policy = get_organize_policy(db)
            assert policy["scheduleMode"] == "MANUAL"
            assert policy["writeMetadataToFiles"] is False
            assert policy["preferLocalMetadata"] is True
            assert policy["localMetadataPriority"] == [
                "SIDECAR_OPF",
                "EMBEDDED",
                "PATH",
            ]
            assert "overwriteTitleAuthor" not in policy
            assert policy["rules"] == {"unrecognized": True, "missingMetadata": True}
    finally:
        engine.dispose()


def test_provider_pipelines_are_independent_ordered_and_composable(tmp_path) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            pipelines = {
                item["mediaKind"]: item["providers"]
                for item in list_metadata_provider_pipelines(db)
            }
            assert [item["providerId"] for item in pipelines["EBOOK"]] == [
                "douban",
                "bangumi",
                "ai",
            ]
            assert [item["providerId"] for item in pipelines["COMIC"]] == [
                "bangumi",
                "ai",
            ]
            assert [item["providerId"] for item in pipelines["AUDIOBOOK"]] == [
                "douban",
                "ai",
            ]
            assert {
                media_kind: [
                    item["providerId"] for item in providers if item["enabled"]
                ]
                for media_kind, providers in pipelines.items()
            } == {
                "EBOOK": ["douban", "bangumi"],
                "COMIC": ["bangumi"],
                "AUDIOBOOK": ["douban"],
            }

            update_metadata_provider(
                db,
                "ai",
                {
                    "config": {
                        "baseUrl": "https://example.test/v1",
                        "model": "test-model",
                        "apiKey": "secret",
                    }
                },
            )
            update_metadata_provider_pipeline(
                db,
                "EBOOK",
                [
                    {"providerId": "ai", "enabled": True},
                    {"providerId": "douban", "enabled": True},
                ],
            )
            update_metadata_provider_pipeline(
                db, "COMIC", [{"providerId": "bangumi", "enabled": True}]
            )

            assert enabled_metadata_provider_ids(db, "EBOOK") == ["ai", "douban"]
            assert enabled_metadata_provider_ids(db, "COMIC") == ["bangumi"]
            assert enabled_metadata_provider_ids(db, "AUDIOBOOK") == ["douban"]
            pipelines = {
                item["mediaKind"]: item["providers"]
                for item in list_metadata_provider_pipelines(db)
            }
            assert [item["providerId"] for item in pipelines["COMIC"]] == ["bangumi"]
            assert [item["providerId"] for item in pipelines["AUDIOBOOK"]] == [
                "douban",
                "ai",
            ]
    finally:
        engine.dispose()


def test_queue_record_can_be_rerecognized_from_any_state_and_deleted_without_deleting_work(
    tmp_path,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    engine = create_sqlite_engine(settings.database_path)
    try:
        bootstrap_database(engine, settings)
        with Session(engine) as db:
            _insert_work(db, "queue-work")
            update_metadata_provider(db, "douban", {"enabled": True})
            run = create_organize_run(db, work_ids=["queue-work"])
            job = (
                db.execute(
                    text("SELECT * FROM `OrganizeJob` WHERE `workId` = 'queue-work'")
                )
                .mappings()
                .one()
            )
            old_task = (
                db.execute(
                    text(
                        "SELECT * FROM `MetadataLookupTask` WHERE `organizeJobId` = :job_id"
                    ),
                    {"job_id": job["id"]},
                )
                .mappings()
                .one()
            )
            db.execute(
                text(
                    "UPDATE `OrganizeJob` SET `status` = 'APPLIED', `finishedAt` = 'now' WHERE `id` = :id"
                ),
                {"id": job["id"]},
            )
            db.execute(
                text(
                    "UPDATE `MetadataLookupTask` SET `status` = 'COMPLETED' WHERE `id` = :id"
                ),
                {"id": old_task["id"]},
            )
            db.execute(
                text(
                    "INSERT INTO `MetadataProviderExecution` "
                    "(`id`, `jobId`, `lookupTaskId`, `providerId`, `status`, `attempts`, `createdAt`, `updatedAt`) "
                    "VALUES ('execution-old', :job_id, :task_id, 'douban', 'COMPLETED', 1, 'now', 'now')"
                ),
                {"job_id": job["id"], "task_id": old_task["id"]},
            )
            db.execute(
                text(
                    "INSERT INTO `MetadataSuggestion` "
                    "(`id`, `jobId`, `field`, `suggestedValue`, `source`, `reason`, `createdAt`, `updatedAt`) "
                    "VALUES ('legacy-suggestion', :job_id, 'author', '\"旧作者\"', 'douban', '旧建议', 'now', 'now')"
                ),
                {"job_id": job["id"]},
            )
            db.execute(
                text(
                    "INSERT INTO `DuplicateCandidate` "
                    "(`id`, `jobId`, `targetWorkId`, `reasons`, `suggestedAction`, `createdAt`, `updatedAt`) "
                    "VALUES ('legacy-duplicate', :job_id, 'queue-work', '[\"title\"]', 'KEEP_SEPARATE', 'now', 'now')"
                ),
                {"job_id": job["id"]},
            )
            db.commit()

            recognized = recognize_organize_job(db, str(job["id"]))

            assert recognized["status"] == "LOOKUP_PENDING"
            assert recognized["trigger"] == "MANUAL"
            assert json.loads(recognized["reasonCodes"]) == ["MANUAL_RECOGNIZE"]
            new_task = (
                db.execute(
                    text(
                        "SELECT * FROM `MetadataLookupTask` WHERE `organizeJobId` = :job_id"
                    ),
                    {"job_id": job["id"]},
                )
                .mappings()
                .one()
            )
            assert new_task["id"] != old_task["id"]
            assert new_task["status"] == "PENDING"
            assert json.loads(new_task["providerOrder"]) == ["douban", "bangumi"]
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM `MetadataProviderExecution` WHERE `jobId` = :job_id"
                    ),
                    {"job_id": job["id"]},
                ).scalar()
                == 0
            )
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM `MetadataSuggestion` WHERE `jobId` = :job_id"
                    ),
                    {"job_id": job["id"]},
                ).scalar()
                == 0
            )
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM `DuplicateCandidate` WHERE `jobId` = :job_id"
                    ),
                    {"job_id": job["id"]},
                ).scalar()
                == 0
            )

            deleted = delete_organize_job(db, str(job["id"]))

            assert deleted == {"id": job["id"], "workId": "queue-work", "deleted": True}
            assert (
                db.execute(
                    text("SELECT COUNT(*) FROM `OrganizeJob` WHERE `id` = :id"),
                    {"id": job["id"]},
                ).scalar()
                == 0
            )
            assert (
                db.execute(
                    text(
                        "SELECT COUNT(*) FROM `MetadataLookupTask` WHERE `organizeJobId` = :id"
                    ),
                    {"id": job["id"]},
                ).scalar()
                == 0
            )
            work = (
                db.execute(
                    text(
                        "SELECT `organized`, `organizeStatus` FROM `LibraryWork` WHERE `id` = 'queue-work'"
                    )
                )
                .mappings()
                .one()
            )
            assert dict(work) == {"organized": 0, "organizeStatus": "UNASSESSED"}
            saved_run = (
                db.execute(
                    text(
                        "SELECT `status`, `queuedCount`, `completedCount` FROM `OrganizeRun` WHERE `id` = :id"
                    ),
                    {"id": run["id"]},
                )
                .mappings()
                .one()
            )
            assert dict(saved_run) == {
                "status": "COMPLETED",
                "queuedCount": 0,
                "completedCount": 0,
            }
    finally:
        engine.dispose()
