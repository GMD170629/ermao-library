"""ORM queries for organize job list, detail, and pending views."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import case, exists, func, inspect, literal, or_, select
from sqlalchemy.orm import Session

from app.models.library import LibraryWork
from app.models.organize import MetadataLookupTask, MetadataProviderExecution, OrganizeJob
from app.modules.organize.infrastructure.runs import job_entity_as_legacy_dict

STATUS_CATEGORIES = ("SUCCESS", "FAILED", "RECOGNIZING", "WAITING")

REASON_ALIASES: dict[str, str] = {
    "历史手动加入": "MANUAL_SELECTED",
    "手动重新识别": "MANUAL_RECOGNIZE",
    "尚未识别": "UNRECOGNIZED",
    "缺少元数据": "MISSING_METADATA",
    "元数据质量偏低": "QUALITY_BELOW_THRESHOLD",
    "新增读物": "NEW_IMPORT",
    "导入解析失败": "IMPORT_FAILED",
    "缺少封面": "MISSING_COVER",
    "缺少作者": "MISSING_AUTHOR",
    "标题异常": "ODD_TITLE",
    "新增后自动执行": "NEW",
    "定时识别": "SCHEDULE",
}

SOURCE_ALIASES: dict[str, str] = {
    "embedded": "内嵌元数据",
    "filename": "文件名",
    "aggregation": "自动聚合",
    "external": "外部数据源",
    "rule": "整理规则",
}


@dataclass(frozen=True)
class OrganizeJobPageResult:
    rows: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
    total_pages: int
    status_counts: dict[str, int]


def has_work_table(db: Session) -> bool:
    return inspect(db.connection()).has_table("LibraryWork")


def has_job_tables(db: Session) -> bool:
    return inspect(db.connection()).has_table("OrganizeJob") and has_work_table(db)


def job_column_names(db: Session) -> set[str]:
    if not inspect(db.connection()).has_table("OrganizeJob"):
        return set()
    return {column["name"] for column in inspect(db.connection()).get_columns("OrganizeJob")}


def has_lookup_table(db: Session) -> bool:
    return inspect(db.connection()).has_table("MetadataLookupTask")


def has_execution_table(db: Session) -> bool:
    return inspect(db.connection()).has_table("MetadataProviderExecution")


def latest_lookup_status_subquery():
    return (
        select(func.upper(func.coalesce(MetadataLookupTask.status, "")))
        .where(MetadataLookupTask.organize_job_id == OrganizeJob.id)
        .order_by(MetadataLookupTask.created_at.desc(), MetadataLookupTask.id.desc())
        .limit(1)
        .correlate(OrganizeJob)
        .scalar_subquery()
    )


def status_category_expression(db: Session):
    job_status = func.upper(func.coalesce(OrganizeJob.status, ""))
    lookup_status = (
        func.coalesce(latest_lookup_status_subquery(), "")
        if has_lookup_table(db)
        else literal("")
    )
    return case(
        (job_status.in_(("APPLIED", "COMPLETED")), "SUCCESS"),
        (job_status.in_(("FAILED", "REVIEWING", "DISMISSED", "CANCELLED")), "FAILED"),
        (or_(job_status == "RUNNING", lookup_status == "RUNNING"), "RECOGNIZING"),
        else_="WAITING",
    )


def _base_job_select(db: Session):
    return select(OrganizeJob).join(LibraryWork, LibraryWork.id == OrganizeJob.work_id)


def count_status_categories(db: Session) -> dict[str, int]:
    counts = {category: 0 for category in STATUS_CATEGORIES}
    if not has_job_tables(db):
        return counts
    category_expr = status_category_expression(db)
    rows = db.execute(
        select(category_expr.label("category"), func.count())
        .select_from(OrganizeJob)
        .join(LibraryWork, LibraryWork.id == OrganizeJob.work_id)
        .group_by(category_expr)
    ).all()
    for category, count in rows:
        key = str(category or "")
        if key in counts:
            counts[key] = int(count or 0)
    return counts


def provider_ids_matching_search(
    search: str,
    providers: Sequence[dict[str, Any]],
) -> list[str]:
    normalized = search.strip().lower()
    if not normalized:
        return []
    matched = [
        str(provider.get("id") or "")
        for provider in providers
        if normalized in str(provider.get("name") or "").lower()
    ]
    matched.extend(
        provider_id
        for provider_id, label in SOURCE_ALIASES.items()
        if normalized in label.lower()
    )
    return [provider_id for provider_id in matched if provider_id]


def _search_predicates(
    db: Session,
    search: str,
    *,
    provider_ids: Sequence[str],
) -> list[Any]:
    normalized = search.strip().lower()
    if not normalized:
        return []
    term = f"%{normalized}%"
    predicates: list[Any] = [
        func.lower(func.coalesce(LibraryWork.title, "")).like(term),
        func.lower(func.coalesce(LibraryWork.author, "")).like(term),
        func.lower(func.coalesce(OrganizeJob.summary, "")).like(term),
        func.lower(func.coalesce(OrganizeJob.issue_codes, "")).like(term),
    ]
    columns = job_column_names(db)
    if "reasonCodes" in columns:
        predicates.append(func.lower(func.coalesce(OrganizeJob.reason_codes, "")).like(term))
    if "trigger" in columns:
        predicates.append(func.lower(func.coalesce(OrganizeJob.trigger, "")).like(term))
    if has_execution_table(db):
        predicates.append(
            exists(
                select(MetadataProviderExecution.id).where(
                    MetadataProviderExecution.job_id == OrganizeJob.id,
                    func.lower(func.coalesce(MetadataProviderExecution.provider_id, "")).like(term),
                )
            )
        )
    if has_lookup_table(db):
        predicates.append(
            exists(
                select(MetadataLookupTask.id).where(
                    MetadataLookupTask.organize_job_id == OrganizeJob.id,
                    or_(
                        func.lower(func.coalesce(MetadataLookupTask.result_source, "")).like(term),
                        func.lower(func.coalesce(MetadataLookupTask.provider_order, "")).like(term),
                    ),
                )
            )
        )
    for label, code in REASON_ALIASES.items():
        if normalized not in label.lower():
            continue
        code_term = f"%{code.lower()}%"
        predicates.append(func.lower(func.coalesce(OrganizeJob.issue_codes, "")).like(code_term))
        if "reasonCodes" in columns:
            predicates.append(func.lower(func.coalesce(OrganizeJob.reason_codes, "")).like(code_term))
        if "trigger" in columns:
            predicates.append(func.lower(func.coalesce(OrganizeJob.trigger, "")).like(code_term))
    for provider_id in provider_ids:
        provider_key = provider_id.lower()
        provider_terms: list[Any] = []
        if has_execution_table(db):
            provider_terms.append(
                exists(
                    select(MetadataProviderExecution.id).where(
                        MetadataProviderExecution.job_id == OrganizeJob.id,
                        func.lower(func.coalesce(MetadataProviderExecution.provider_id, "")) == provider_key,
                    )
                )
            )
        if has_lookup_table(db):
            provider_terms.append(
                exists(
                    select(MetadataLookupTask.id).where(
                        MetadataLookupTask.organize_job_id == OrganizeJob.id,
                        or_(
                            func.lower(func.coalesce(MetadataLookupTask.result_source, "")) == provider_key,
                            func.lower(func.coalesce(MetadataLookupTask.provider_order, "")).like(
                                f'%"{provider_key}"%'
                            ),
                        ),
                    )
                )
            )
        if provider_terms:
            predicates.append(or_(*provider_terms))
    return [or_(*predicates)]


def _filter_predicates(
    db: Session,
    *,
    status: str,
    search: str,
    provider_ids: Sequence[str],
) -> list[Any]:
    predicates: list[Any] = []
    normalized_status = status.strip().upper()
    if normalized_status != "ALL":
        predicates.append(status_category_expression(db) == normalized_status)
    predicates.extend(_search_predicates(db, search, provider_ids=provider_ids))
    return predicates


def count_filtered_jobs(
    db: Session,
    *,
    status: str,
    search: str,
    provider_ids: Sequence[str],
) -> int:
    if not has_job_tables(db):
        return 0
    stmt = select(func.count()).select_from(OrganizeJob).join(
        LibraryWork, LibraryWork.id == OrganizeJob.work_id
    )
    predicates = _filter_predicates(db, status=status, search=search, provider_ids=provider_ids)
    if predicates:
        stmt = stmt.where(*predicates)
    return int(db.scalar(stmt) or 0)


def list_filtered_job_rows(
    db: Session,
    *,
    page: int,
    page_size: int,
    status: str,
    search: str,
    provider_ids: Sequence[str],
) -> list[dict[str, Any]]:
    if not has_job_tables(db):
        return []
    stmt = _base_job_select(db)
    predicates = _filter_predicates(db, status=status, search=search, provider_ids=provider_ids)
    if predicates:
        stmt = stmt.where(*predicates)
    rows = db.scalars(
        stmt.order_by(
            OrganizeJob.created_at.desc(),
            OrganizeJob.updated_at.desc(),
            OrganizeJob.id.desc(),
        )
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    return [job_entity_as_legacy_dict(row) for row in rows]


def paginate_organize_jobs(
    db: Session,
    *,
    requested_page: int,
    page_size: int,
    status: str,
    search: str,
    provider_ids: Sequence[str],
) -> OrganizeJobPageResult:
    status_counts = count_status_categories(db)
    if not has_job_tables(db):
        return OrganizeJobPageResult(
            rows=[],
            page=1,
            page_size=page_size,
            total=0,
            total_pages=1,
            status_counts=status_counts,
        )
    total = count_filtered_jobs(
        db,
        status=status,
        search=search,
        provider_ids=provider_ids,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(requested_page, total_pages)
    rows = list_filtered_job_rows(
        db,
        page=page,
        page_size=page_size,
        status=status,
        search=search,
        provider_ids=provider_ids,
    )
    return OrganizeJobPageResult(
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
        status_counts=status_counts,
    )


def list_pending_job_rows(db: Session, *, limit: int) -> list[dict[str, Any]]:
    if not has_job_tables(db):
        return []
    rows = db.scalars(
        select(OrganizeJob)
        .join(LibraryWork, LibraryWork.id == OrganizeJob.work_id)
        .where(
            OrganizeJob.status == "REVIEWING",
            func.coalesce(LibraryWork.hidden, False).is_(False),
        )
        .order_by(OrganizeJob.updated_at.desc(), OrganizeJob.id.desc())
        .limit(limit)
    ).all()
    return [job_entity_as_legacy_dict(row) for row in rows]


def latest_lookup_rows_by_job(
    db: Session,
    job_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    if not job_ids or not has_lookup_table(db):
        return {}
    rows = db.scalars(
        select(MetadataLookupTask)
        .where(MetadataLookupTask.organize_job_id.in_(job_ids))
        .order_by(
            MetadataLookupTask.organize_job_id.asc(),
            MetadataLookupTask.created_at.desc(),
            MetadataLookupTask.id.desc(),
        )
    ).all()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        job_id = str(row.organize_job_id or "")
        if not job_id or job_id in result:
            continue
        result[job_id] = {
            "status": row.status,
            "resultSource": row.result_source,
            "providerOrder": row.provider_order,
            "errorSummary": row.error_summary,
        }
    return result


def execution_rows_by_job(
    db: Session,
    job_ids: Sequence[str],
) -> dict[str, list[dict[str, Any]]]:
    if not job_ids or not has_execution_table(db):
        return {}
    rows = db.scalars(
        select(MetadataProviderExecution)
        .where(MetadataProviderExecution.job_id.in_(job_ids))
        .order_by(
            MetadataProviderExecution.job_id.asc(),
            MetadataProviderExecution.created_at.asc(),
            MetadataProviderExecution.id.asc(),
        )
    ).all()
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        job_id = str(row.job_id or "")
        if not job_id:
            continue
        result.setdefault(job_id, []).append(
            {
                "id": row.id,
                "providerId": row.provider_id,
                "status": row.status,
                "attempts": row.attempts,
                "errorSummary": row.error_summary,
                "startedAt": row.started_at,
                "finishedAt": row.finished_at,
            }
        )
    return result
