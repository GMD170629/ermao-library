from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import OperationalError
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
    mark_organize_policy_scheduled_command,
    sync_organize_runs,
    sync_organize_runs_command,
)
from app.bootstrap.organize import (
    cancel_organize_job_command as persist_cancel_organize_job,
)
from app.bootstrap.organize import (
    create_organize_run_command as persist_organize_run,
)
from app.bootstrap.organize import (
    delete_organize_job_command as persist_delete_organize_job,
)
from app.bootstrap.organize import (
    recognize_organize_job_command as persist_recognize_organize_job,
)
from app.bootstrap.organize import (
    update_organize_policy_command as persist_organize_policy,
)
from app.core.database_errors import is_database_busy_error
from app.modules.organize.application.commands import prepare_organize_policy_update
from app.modules.organize.application.dto import PreparedOrganizeJobEnqueue
from app.modules.organize.infrastructure import eligibility as organize_eligibility
from app.modules.organize.infrastructure import jobs as organize_jobs
from app.modules.organize.infrastructure import runs as organize_runs
from app.services.metadata_provider_registry import enabled_metadata_provider_ids

LOGGER = logging.getLogger(__name__)
DATABASE_BUSY_RETRY_DELAYS_SECONDS = (0.25, 1.0)
DATABASE_BUSY_LOG_INTERVAL_SECONDS = 30.0
ACTIVE_JOB_STATUSES = (
    "LOOKUP_PENDING",
    "PENDING",
    "QUEUED",
    "RUNNING",
    "RETRY_WAIT",
    "REVIEWING",
)
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
    "update_organize_policy_command",
]


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"py_{prefix}_{uuid4().hex}"


def update_organize_policy_command(
    db: Session, payload: dict[str, Any]
) -> dict[str, Any]:
    """Own the policy mutation transaction outside the HTTP adapter."""

    current = get_organize_policy(db)
    prepared = prepare_organize_policy_update(current, payload, timestamp=_now())
    return persist_organize_policy(db, prepared)


def update_organize_policy(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible named policy command."""

    return update_organize_policy_command(db, payload)


def eligible_organize_works(
    db: Session,
    policy: dict[str, Any] | None = None,
    *,
    book_ids: list[str] | None = None,
    trigger: str = "MANUAL",
    limit: int = 500,
    force_selected: bool = False,
) -> list[dict[str, Any]]:
    policy = policy or get_organize_policy(db)
    return organize_eligibility.select_eligible_works(
        db,
        rules=policy["rules"],
        book_ids=book_ids,
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
                "availableMediaKinds": work.get("availableMediaKinds") or [],
                "coverPath": work.get("coverPath"),
                "metadataQuality": int(work.get("metadataQuality") or 0),
                "reasonCodes": work.get("reasonCodes") or [],
                "createdAt": work.get("createdAt"),
            }
            for work in works
        ],
    }


def _run_dedupe_key(
    trigger: str, book_ids: list[str], supplied: str | None = None
) -> str:
    if supplied:
        return supplied
    digest = hashlib.sha256("\n".join(sorted(book_ids)).encode("utf-8")).hexdigest()[
        :20
    ]
    return f"{trigger.lower()}:{digest}:{uuid4().hex}"


def create_organize_run(
    db: Session,
    *,
    trigger: str = "MANUAL",
    book_ids: list[str] | None = None,
    dedupe_key: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    normalized_trigger = str(trigger or "MANUAL").upper()
    if normalized_trigger not in {"MANUAL", "SCHEDULE", "NEW"}:
        raise ValueError("不支持的整理任务触发方式")
    policy = get_organize_policy(db)
    selected = [str(item) for item in (book_ids or []) if str(item).strip()]
    works = eligible_organize_works(
        db,
        policy,
        book_ids=selected or None,
        trigger=normalized_trigger,
        limit=limit,
        force_selected=bool(selected) and normalized_trigger == "MANUAL",
    )
    selections = {
        str(work["id"]): organize_eligibility.first_resource_selection_for_book(
            db, str(work["id"])
        )
        for work in works
    }
    works = [work for work in works if selections[str(work["id"])] is not None]
    provider_plans = {
        str(work["id"]): enabled_metadata_provider_ids(
            db, selections[str(work["id"])][1]
        )
        for work in works
    }
    # All policy, eligibility, media and provider projections are detached
    # before dedupe/ID construction or the write unit of work begins.
    db.close()
    ids = [str(work["id"]) for work in works]
    key = _run_dedupe_key(normalized_trigger, ids, dedupe_key)
    existing = organize_runs.get_run_by_dedupe_key(db, key)
    db.close()
    if existing:
        return organize_runs.run_view(existing)

    now = _now()
    run_id = _id("organize_run")
    run_status = "RUNNING" if works else "COMPLETED"
    scope = {"bookIds": selected, "rules": policy["rules"]}
    job_plans = tuple(
        PreparedOrganizeJobEnqueue(
            job_id=_id("organize_job"),
            task_id=_id("metadata_lookup"),
            book_id=str(work["id"]),
            resource_id=selections[str(work["id"])][0],
            provider_order=tuple(provider_plans[str(work["id"])]),
            reasons=tuple(str(reason) for reason in work.get("reasonCodes") or []),
        )
        for work in works
    )
    # The eligibility read and inserts are intentionally separated. A
    # concurrent organizer may claim a work in between; the database
    # unique index is the final arbiter, so the actual count is filled
    # after the inserts below.
    queued_count = persist_organize_run(
        db,
        run_id=run_id,
        trigger=normalized_trigger,
        scope=scope,
        dedupe_key=key,
        run_status=run_status,
        timestamp=now,
        job_plans=job_plans,
    )
    persisted_run = get_organize_run(db, run_id)
    db.close()
    return persisted_run or {
        "id": run_id,
        "status": "RUNNING" if queued_count else "COMPLETED",
        "queuedCount": queued_count,
    }


def cancel_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = organize_runs.get_job_row(db, job_id)
    if not job:
        raise ValueError("整理任务不存在")
    if str(job.get("status")) in TERMINAL_JOB_STATUSES:
        raise ValueError("当前状态无法取消")
    now = _now()
    persist_cancel_organize_job(
        db, job_id=job_id, book_id=str(job["bookId"]), timestamp=now
    )
    return organize_runs.get_job_row(db, job_id) or {}


def recognize_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = organize_runs.get_job_row(db, job_id)
    if not job:
        raise ValueError("整理记录不存在")
    book = organize_jobs.get_book_row(db, str(job["bookId"]))
    if not book:
        raise ValueError("图书已不存在")
    current_unresolved = organize_jobs.get_unresolved_job_for_book(
        db,
        book_id=str(job["bookId"]),
        exclude_job_id=job_id,
    )
    if current_unresolved:
        # Re-recognition is a work-level intent. Reuse its unresolved record
        # when the action originated from an older successful history row.
        job = current_unresolved
        job_id = str(current_unresolved["id"])
    now = _now()
    selection = organize_eligibility.first_resource_selection_for_book(
        db,
        str(job["bookId"]),
        str(job.get("resourceId") or "") or None,
    )
    if selection is None:
        raise ValueError("作品没有可整理的版本")
    _, media_kind, resource_id = selection
    providers = enabled_metadata_provider_ids(db, media_kind)
    task_ids = organize_jobs.list_lookup_task_ids_for_job(db, job_id)
    new_task_id = _id("metadata_lookup")
    run_id = str(job.get("runId") or "") or None

    # A new recognition pass owns a clean set of provider executions and does
    # not carry previous provider rows into the new automatic run.
    persist_recognize_organize_job(
        db,
        job_id=job_id,
        task_ids=tuple(task_ids),
        task_id=new_task_id,
        book_id=str(job["bookId"]),
        resource_id=resource_id,
        provider_order=tuple(providers),
        run_id=run_id,
        timestamp=now,
    )
    return organize_runs.get_job_row(db, job_id) or {}


def retry_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    """Backward-compatible service alias for callers from older releases."""

    return recognize_organize_job(db, job_id)


def delete_organize_job(db: Session, job_id: str) -> dict[str, Any]:
    job = organize_runs.get_job_row(db, job_id)
    if not job:
        raise ValueError("整理记录不存在")

    book_id = str(job.get("bookId") or "")
    run_id = str(job.get("runId") or "") or None
    task_ids = organize_jobs.list_lookup_task_ids_for_job(db, job_id)
    now = _now()
    remaining_status = organize_jobs.latest_job_status_for_book_excluding(
        db, book_id, job_id
    )
    curated = organize_jobs.book_is_curated(db, book_id)
    curation_state = remaining_status or ("APPLIED" if curated else "UNASSESSED")
    persist_delete_organize_job(
        db,
        job_id=job_id,
        task_ids=tuple(task_ids),
        book_id=book_id,
        curation_state=curation_state,
        run_id=run_id,
        timestamp=now,
    )
    return {"id": job_id, "bookId": book_id, "deleted": True}


def process_organize_schedule_tick(db: Session) -> int:
    policy = get_organize_policy(db)
    db.close()
    runs_updated = sync_organize_runs_command(db)
    queued = 0
    now = _now()
    if policy["autoRunOnNew"]:
        new_works = eligible_organize_works(db, policy, trigger="NEW", limit=500)
        db.close()
        if new_works:
            ids = [str(item["id"]) for item in new_works]
            result = create_organize_run(
                db,
                trigger="NEW",
                book_ids=ids,
                dedupe_key=f"new:{hashlib.sha256('|'.join(sorted(ids)).encode()).hexdigest()[:24]}",
            )
            queued += int(result.get("queuedCount") or 0)
    next_run = policy.get("nextRunAt")
    next_due = False
    if next_run:
        try:
            next_due = datetime.fromisoformat(str(next_run)) <= now
        except ValueError:
            next_due = True
    if policy["enabled"] and policy["scheduleMode"] == "INTERVAL" and next_due:
        due_key = f"schedule:{next_run!s}"
        result = create_organize_run(db, trigger="SCHEDULE", dedupe_key=due_key)
        queued += int(result.get("queuedCount") or 0)
        next_run_at = now + timedelta(minutes=policy["intervalMinutes"])
        mark_organize_policy_scheduled_command(
            db,
            timestamp=now,
            next_run_at=next_run_at,
        )
    elif runs_updated:
        pass
    return queued


class OrganizerScheduler:
    def __init__(
        self, db_factory: Callable[[], Session], poll_seconds: float = 5.0
    ) -> None:
        self._db_factory = db_factory
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._last_busy_log_at: float | None = None
        self._thread = threading.Thread(
            target=self._run, name="organizer-scheduler", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(2.0, self._poll_seconds + 1.0))

    def _process_iteration(self) -> bool:
        for attempt in range(len(DATABASE_BUSY_RETRY_DELAYS_SECONDS) + 1):
            if attempt and self._stop.wait(
                DATABASE_BUSY_RETRY_DELAYS_SECONDS[attempt - 1]
            ):
                return False
            try:
                with self._db_factory() as db:
                    process_organize_schedule_tick(db)
                return True
            except OperationalError as error:
                if not is_database_busy_error(error) or attempt == len(
                    DATABASE_BUSY_RETRY_DELAYS_SECONDS
                ):
                    raise
        raise AssertionError("organize retry loop exhausted")

    def _record_iteration_error(self, error: BaseException) -> None:
        if not is_database_busy_error(error):
            LOGGER.exception("organizer scheduler iteration failed")
            return
        now = monotonic()
        if (
            self._last_busy_log_at is not None
            and now - self._last_busy_log_at < DATABASE_BUSY_LOG_INTERVAL_SECONDS
        ):
            return
        LOGGER.warning(
            "organizer_schedule_iteration outcome=deferred reason=database_busy"
        )
        self._last_busy_log_at = now

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if not self._process_iteration():
                    break
            except Exception as error:  # noqa: BLE001 - worker containment boundary.
                self._record_iteration_error(error)
            self._stop.wait(self._poll_seconds)
