from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timedelta, timezone
from time import time_ns
from typing import Any, Callable

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.bootstrap.organize import (
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_POLICY_ID,
    DEFAULT_RULES,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    ensure_organize_policy,
    get_organize_policy,
    get_organize_run,
    list_organize_runs,
    mark_policy_scheduled,
    sync_organize_runs,
    update_organize_policy,
)
from app.modules.organize.infrastructure import eligibility as organize_eligibility
from app.modules.organize.infrastructure import jobs as organize_jobs
from app.modules.organize.infrastructure import runs as organize_runs
from app.services.metadata_provider_registry import enabled_metadata_provider_ids


LOGGER = logging.getLogger(__name__)
ACTIVE_JOB_STATUSES = ("LOOKUP_PENDING", "PENDING", "QUEUED", "RUNNING", "RETRY_WAIT", "REVIEWING")
UNRESOLVED_JOB_STATUSES = organize_eligibility.UNRESOLVED_JOB_STATUSES
TERMINAL_JOB_STATUSES = ("APPLIED", "COMPLETED", "DISMISSED", "CANCELLED", "FAILED")

__all__ = [
    "ACTIVE_JOB_STATUSES",
    "DEFAULT_INTERVAL_MINUTES",
    "DEFAULT_POLICY_ID",
    "DEFAULT_RULES",
    "MAX_INTERVAL_MINUTES",
    "MIN_INTERVAL_MINUTES",
    "TERMINAL_JOB_STATUSES",
    "UNRESOLVED_JOB_STATUSES",
    "OrganizerScheduler",
    "cancel_organize_job",
    "create_organize_run",
    "delete_organize_job",
    "eligible_organize_works",
    "ensure_organize_policy",
    "get_organize_policy",
    "get_organize_run",
    "list_organize_runs",
    "organize_candidate_summary",
    "process_organize_schedule_tick",
    "recognize_organize_job",
    "retry_organize_job",
    "sync_organize_runs",
    "update_organize_policy",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"py_{prefix}_{time_ns()}"


def _has_table(db: Session, table: str) -> bool:
    return inspect(db.connection()).has_table(table)


def eligible_organize_works(
    db: Session,
    policy: dict[str, Any] | None = None,
    *,
    work_ids: list[str] | None = None,
    trigger: str = "MANUAL",
    limit: int = 500,
    force_selected: bool = False,
) -> list[dict[str, Any]]:
    policy = policy or get_organize_policy(db)
    return organize_eligibility.select_eligible_works(
        db,
        rules=policy["rules"],
        work_ids=work_ids,
        trigger=trigger,
        limit=limit,
        force_selected=force_selected,
        auto_run_on_new_since=policy.get("autoRunOnNewSince"),
    )


def organize_candidate_summary(db: Session) -> dict[str, Any]:
    policy = get_organize_policy(db)
    works = eligible_organize_works(db, policy, limit=2000)
    counts: dict[str, int] = {}
    for work in works:
        for reason in work.get("reasonCodes") or []:
            counts[reason] = counts.get(reason, 0) + 1
    return {
        "total": len(works),
        "reasonCounts": counts,
        "works": [
            {
                "id": work.get("id"),
                "title": work.get("title"),
                "author": work.get("author"),
                "workType": work.get("workType"),
                "coverPath": work.get("coverPath"),
                "metadataQuality": int(work.get("metadataQuality") or 0),
                "reasonCodes": work.get("reasonCodes") or [],
                "createdAt": work.get("createdAt"),
            }
            for work in works
        ],
    }


def _run_dedupe_key(trigger: str, work_ids: list[str], supplied: str | None = None) -> str:
    if supplied:
        return supplied
    digest = hashlib.sha256("\n".join(sorted(work_ids)).encode("utf-8")).hexdigest()[:20]
    return f"{trigger.lower()}:{digest}:{time_ns()}"


def create_organize_run(
    db: Session,
    *,
    trigger: str = "MANUAL",
    work_ids: list[str] | None = None,
    dedupe_key: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    if not all(_has_table(db, table) for table in ("OrganizeRun", "OrganizeJob", "MetadataLookupTask")):
        raise ValueError("整理队列数据表尚未初始化")
    normalized_trigger = str(trigger or "MANUAL").upper()
    if normalized_trigger not in {"MANUAL", "SCHEDULE", "NEW"}:
        raise ValueError("不支持的整理任务触发方式")
    policy = get_organize_policy(db)
    selected = [str(item) for item in (work_ids or []) if str(item).strip()]
    works = eligible_organize_works(
        db,
        policy,
        work_ids=selected or None,
        trigger=normalized_trigger,
        limit=limit,
        force_selected=bool(selected) and normalized_trigger == "MANUAL",
    )
    provider_plans = {
        str(work["id"]): enabled_metadata_provider_ids(db, str(work.get("workType") or ""))
        for work in works
    }
    ids = [str(work["id"]) for work in works]
    key = _run_dedupe_key(normalized_trigger, ids, dedupe_key)
    existing = organize_runs.get_run_by_dedupe_key(db, key)
    if existing:
        return organize_runs.run_view(existing)

    now = _now()
    run_id = _id("organize_run")
    run_status = "RUNNING" if works else "COMPLETED"
    scope = {"workIds": selected, "rules": policy["rules"]}
    # The eligibility read and inserts are intentionally separated. A
    # concurrent organizer may claim a work in between; the database
    # unique index is the final arbiter, so the actual count is filled
    # after the inserts below.
    organize_jobs.insert_organize_run(
        db,
        run_id=run_id,
        trigger=normalized_trigger,
        scope=scope,
        dedupe_key=key,
        status=run_status,
        started_at=now,
        finished_at=now if not works else None,
        now=now,
    )
    for work in works:
        work_id = str(work["id"])
        edition_id = organize_eligibility.primary_edition_id_for_work(db, work)
        provider_order = provider_plans[work_id]
        job_id = _id("organize_job")
        task_id = _id("metadata_lookup")
        reasons = list(work.get("reasonCodes") or [])
        inserted = organize_jobs.try_insert_unresolved_job(
            db,
            job_id=job_id,
            run_id=run_id,
            work_id=work_id,
            edition_id=edition_id,
            trigger=normalized_trigger,
            reasons=reasons,
            summary="等待元数据插件识别",
            now=now,
        )
        if not inserted:
            continue
        organize_jobs.insert_lookup_task(
            db,
            task_id=task_id,
            work_id=work_id,
            edition_id=edition_id,
            job_id=job_id,
            provider_order=provider_order,
            now=now,
        )
        organize_jobs.mark_work_organize_status(db, work_id=work_id, status="LOOKUP_PENDING", now=now)
    queued_count = organize_jobs.finalize_run_enqueue(db, run_id=run_id, now=now)
    db.commit()
    return get_organize_run(db, run_id) or {
        "id": run_id,
        "status": "RUNNING" if queued_count else "COMPLETED",
        "queuedCount": queued_count,
    }


def cancel_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = organize_runs.get_job_row(db, job_id) if _has_table(db, "OrganizeJob") else None
    if not job:
        raise ValueError("整理任务不存在")
    if str(job.get("status")) in TERMINAL_JOB_STATUSES:
        raise ValueError("当前状态无法取消")
    now = _now()
    organize_jobs.cancel_lookup_tasks_for_job(db, job_id=job_id, now=now)
    organize_jobs.cancel_job(db, job_id=job_id, now=now)
    organize_jobs.mark_work_organize_status(db, work_id=str(job["workId"]), status="UNASSESSED", now=now)
    sync_organize_runs(db)
    db.commit()
    return organize_runs.get_job_row(db, job_id) or {}


def recognize_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = organize_runs.get_job_row(db, job_id) if _has_table(db, "OrganizeJob") else None
    if not job:
        raise ValueError("整理记录不存在")
    work = organize_jobs.get_work_row(db, str(job["workId"]))
    if not work:
        raise ValueError("作品已不存在")
    current_unresolved = organize_jobs.get_unresolved_job_for_work(
        db,
        work_id=str(job["workId"]),
        exclude_job_id=job_id,
    )
    if current_unresolved:
        # Re-recognition is a work-level intent. Reuse its unresolved record
        # when the action originated from an older successful history row.
        job = current_unresolved
        job_id = str(current_unresolved["id"])
    now = _now()
    providers = enabled_metadata_provider_ids(db, str(work.get("workType") or ""))
    task_ids = organize_jobs.list_lookup_task_ids_for_job(db, job_id)

    # A new recognition pass owns a clean set of provider executions. Keep the
    # legacy review tables readable for old backups, but never carry their rows
    # into a new automatic run.
    organize_jobs.clear_job_recognition_artifacts(db, job_id=job_id, task_ids=task_ids)
    organize_jobs.insert_lookup_task(
        db,
        task_id=_id("metadata_lookup"),
        work_id=str(job["workId"]),
        edition_id=job.get("editionId"),
        job_id=job_id,
        provider_order=providers,
        now=now,
    )
    organize_jobs.reset_job_for_recognition(db, job_id=job_id, now=now)
    organize_jobs.mark_work_organize_status(
        db,
        work_id=str(job["workId"]),
        status="LOOKUP_PENDING",
        now=now,
    )
    if job.get("runId"):
        organize_jobs.reopen_run(db, run_id=str(job["runId"]), now=now)
    db.commit()
    return organize_runs.get_job_row(db, job_id) or {}


def retry_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    """Backward-compatible service alias for callers from older releases."""

    return recognize_organize_job(db, job_id)


def delete_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = organize_runs.get_job_row(db, job_id) if _has_table(db, "OrganizeJob") else None
    if not job:
        raise ValueError("整理记录不存在")

    work_id = str(job.get("workId") or "")
    run_id = str(job.get("runId") or "") or None
    task_ids = organize_jobs.list_lookup_task_ids_for_job(db, job_id)
    organize_jobs.delete_job_graph(db, job_id=job_id, task_ids=task_ids)

    now = _now()
    if work_id and _has_table(db, "LibraryWork"):
        remaining_status = organize_jobs.latest_job_status_for_work(db, work_id)
        organized = organize_jobs.work_is_organized(db, work_id)
        organize_status = remaining_status or ("APPLIED" if organized else "UNASSESSED")
        organize_jobs.mark_work_organize_status(db, work_id=work_id, status=organize_status, now=now)
    if run_id and _has_table(db, "OrganizeRun"):
        organize_jobs.refresh_run_queue_count(db, run_id=run_id, now=now)
    sync_organize_runs(db)
    db.commit()
    return {"id": job_id, "workId": work_id, "deleted": True}


def process_organize_schedule_tick(db: Session) -> int:
    policy = get_organize_policy(db)
    runs_updated = sync_organize_runs(db)
    queued = 0
    now = _now()
    if policy["autoRunOnNew"]:
        new_works = eligible_organize_works(db, policy, trigger="NEW", limit=500)
        if new_works:
            ids = [str(item["id"]) for item in new_works]
            result = create_organize_run(
                db,
                trigger="NEW",
                work_ids=ids,
                dedupe_key=f"new:{hashlib.sha256('|'.join(sorted(ids)).encode()).hexdigest()[:24]}",
            )
            queued += int(result.get("queuedCount") or 0)
    next_run = policy.get("nextRunAt")
    next_due = False
    if next_run:
        try:
            next_due = datetime.fromisoformat(str(next_run).replace("Z", "+00:00")) <= now
        except ValueError:
            next_due = True
    if policy["enabled"] and policy["scheduleMode"] == "INTERVAL" and next_due:
        due_key = f"schedule:{str(next_run)}"
        result = create_organize_run(db, trigger="SCHEDULE", dedupe_key=due_key)
        queued += int(result.get("queuedCount") or 0)
        mark_policy_scheduled(
            db,
            now=now,
            next_run_at=now + timedelta(minutes=policy["intervalMinutes"]),
        )
        db.commit()
    elif runs_updated:
        db.commit()
    return queued


class OrganizerScheduler:
    def __init__(self, db_factory: Callable[[], Session], poll_seconds: float = 5.0) -> None:
        self._db_factory = db_factory
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="organizer-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(2.0, self._poll_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self._db_factory() as db:
                    process_organize_schedule_tick(db)
            except Exception:
                LOGGER.exception("organizer scheduler iteration failed")
            self._stop.wait(self._poll_seconds)
