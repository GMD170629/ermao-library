"""Named organize unit-of-work boundary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import TracebackType
from typing import Any, Protocol, Self

from app.contracts.local_metadata import validate_local_metadata_priority
from app.modules.organize.application.dto import PreparedOrganizePolicyUpdate

MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 7 * 24 * 60


class OrganizeUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class OrganizeWriteTransaction:
    def __init__(self, unit_of_work: OrganizeUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exception, traceback
        if exception_type is None:
            self._unit_of_work.commit()
        else:
            self._unit_of_work.rollback()
        return False


def prepare_organize_policy_update(
    current: dict[str, Any],
    payload: dict[str, Any],
    *,
    timestamp: datetime,
) -> PreparedOrganizePolicyUpdate:
    schedule_mode = str(payload.get("scheduleMode", current["scheduleMode"])).upper()
    if schedule_mode not in {"MANUAL", "INTERVAL"}:
        raise ValueError("执行方式仅支持手动或定时间隔")
    try:
        interval = int(payload.get("intervalMinutes", current["intervalMinutes"]))
    except (TypeError, ValueError):
        raise ValueError("执行间隔格式不正确") from None
    if interval < MIN_INTERVAL_MINUTES or interval > MAX_INTERVAL_MINUTES:
        raise ValueError(
            f"执行间隔需在 {MIN_INTERVAL_MINUTES} 到 {MAX_INTERVAL_MINUTES} 分钟之间"
        )
    enabled = bool(payload.get("enabled", current["enabled"]))
    auto_run_on_new = bool(payload.get("autoRunOnNew", current["autoRunOnNew"]))
    rules_payload = payload.get("rules", current["rules"])
    if not isinstance(rules_payload, dict):
        raise TypeError("识别范围配置格式不正确")
    rules = {
        "unrecognized": bool(
            rules_payload.get("unrecognized", current["rules"]["unrecognized"])
        ),
        "missingMetadata": bool(
            rules_payload.get("missingMetadata", current["rules"]["missingMetadata"])
        ),
    }
    try:
        local_metadata_priority = validate_local_metadata_priority(
            payload.get("localMetadataPriority", current["localMetadataPriority"])
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(str(exc)) from exc
    newly_enabled_for_new = auto_run_on_new and not current["autoRunOnNew"]
    auto_since = (
        timestamp if newly_enabled_for_new else current.get("autoRunOnNewSince")
    )
    if not auto_run_on_new:
        auto_since = None
    next_run_at = None
    if enabled and schedule_mode == "INTERVAL":
        old_next = current.get("nextRunAt")
        settings_changed = (
            not current["enabled"]
            or current["scheduleMode"] != schedule_mode
            or current["intervalMinutes"] != interval
        )
        next_run_at = (
            timestamp + timedelta(minutes=interval)
            if settings_changed or not old_next
            else old_next
        )
    if "nextRunAt" in payload:
        supplied_next_run = payload["nextRunAt"]
        if supplied_next_run is None:
            next_run_at = None
        elif isinstance(supplied_next_run, datetime):
            next_run_at = supplied_next_run
        else:
            try:
                next_run_at = datetime.fromisoformat(str(supplied_next_run))
            except ValueError as exc:
                raise ValueError("下次执行时间格式不正确") from exc
    return PreparedOrganizePolicyUpdate(
        enabled=enabled,
        schedule_mode=schedule_mode,
        interval_minutes=interval,
        auto_run_on_new=auto_run_on_new,
        auto_run_on_new_since=auto_since,
        rules_json=json.dumps(rules, ensure_ascii=False),
        write_metadata_to_files=bool(
            payload.get("writeMetadataToFiles", current["writeMetadataToFiles"])
        ),
        prefer_local_metadata=bool(
            payload.get("preferLocalMetadata", current["preferLocalMetadata"])
        ),
        local_metadata_priority_json=json.dumps(
            local_metadata_priority, ensure_ascii=False
        ),
        next_run_at=next_run_at,
        updated_at=timestamp,
    )
