"""Organize HTTP surface."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.organize import organize_job_queries, organize_runs
from app.contracts.http_errors import ErrorResponses
from app.core.config import Settings, get_settings
from app.core.time import timestamp_ms_to_iso
from app.db.session import get_db
from app.modules.library.public import book_view, get_book
from app.modules.organize.application.dto import OrganizeJobListItem
from app.modules.organize.presentation.schemas import (
    DeletedOrganizeJobPayload,
    DeletedOrganizeJobResponse,
    OrganizeBadRequestError,
    OrganizeCandidatesPayload,
    OrganizeCandidatesResponse,
    OrganizeErrorBody,
    OrganizeJobPayload,
    OrganizeJobResponse,
    OrganizeJobsPayload,
    OrganizeJobsResponse,
    OrganizeNotFoundError,
    OrganizePolicyPayload,
    OrganizePolicyResponse,
    OrganizeRunsPayload,
    OrganizeRunsResponse,
    PendingOrganizeJobsPayload,
    PendingOrganizeJobsResponse,
    UpdateOrganizePolicyRequest,
)
from app.schemas.responses import fail
from app.services.metadata_file_writeback import (
    metadata_writeback_view_for_lookup_task,
)
from app.services.metadata_provider_registry import list_metadata_providers
from app.services.organize_scheduler import (
    delete_organize_job,
    get_organize_policy,
    list_organize_runs,
    organize_candidate_summary,
    recognize_organize_job,
    update_organize_policy_command,
)

router = APIRouter(tags=["organize"], route_class=TypedContractRoute)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except ValueError:
        return fallback


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    return timestamp_ms_to_iso(value) or str(value)


def _load_book(db: Session, book_id: str) -> dict[str, Any] | None:
    return get_book(db, book_id)


def _book_view(
    db: Session, book: dict[str, Any], user_id: str | None = None
) -> dict[str, Any]:
    return book_view(db, book, user_id)


def _positive_int(value: Any, fallback: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(maximum, max(1, parsed))


def _organize_job_list_view(job: OrganizeJobListItem) -> dict[str, object]:
    return {
        "id": job.id,
        "trigger": job.trigger,
        "statusCategory": job.status_category,
        "issueCodes": job.issue_codes,
        "reasonCodes": job.reason_codes,
        "metadataSources": job.metadata_sources,
        "createdAt": job.created_at,
        "updatedAt": job.updated_at,
        "book": {
            "id": job.book.id,
            "title": job.book.title,
            "author": job.book.author,
            "availableMediaKinds": job.book.available_media_kinds,
        },
    }


def _organize_job_view(
    db: Session,
    job: dict[str, Any],
    user_id: str | None,
    pending_only: bool = False,
    *,
    lookup: dict[str, Any] | None = None,
    executions: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    book = _load_book(db, str(job.get("bookId") or ""))
    if not book:
        return None
    if lookup is None:
        lookup = organize_job_queries.latest_lookup_rows_by_job(
            db, [str(job.get("id") or "")]
        ).get(str(job.get("id") or ""))
    if executions is None:
        executions = organize_job_queries.execution_rows_by_job(
            db, [str(job.get("id") or "")]
        ).get(str(job.get("id") or ""), [])
    raw_status = str(job.get("status") or "REVIEWING").upper()
    lookup_status = str((lookup or {}).get("status") or "").upper()
    if raw_status in {"APPLIED", "COMPLETED"}:
        status_category = "SUCCESS"
    elif raw_status in {"FAILED", "REVIEWING", "DISMISSED", "CANCELLED"}:
        status_category = "FAILED"
    elif raw_status == "RUNNING" or lookup_status == "RUNNING":
        status_category = "RECOGNIZING"
    else:
        status_category = "WAITING"
    provider_order = _parse_json((lookup or {}).get("providerOrder"), [])
    if not isinstance(provider_order, list):
        provider_order = []
    metadata_sources: list[str] = []
    for source in [
        (lookup or {}).get("resultSource"),
        *[execution.get("providerId") for execution in executions],
        *provider_order,
    ]:
        normalized_source = str(source or "").strip()
        if normalized_source and normalized_source not in metadata_sources:
            metadata_sources.append(normalized_source)
    return {
        "id": job.get("id"),
        "runId": job.get("runId"),
        "resourceId": job.get("resourceId"),
        "trigger": job.get("trigger") or "SCHEDULE",
        "status": raw_status,
        "statusCategory": status_category,
        "issueCodes": _parse_json(job.get("issueCodes"), []),
        "reasonCodes": _parse_json(job.get("reasonCodes"), []),
        "summary": job.get("summary"),
        "errorSummary": job.get("errorSummary"),
        "metadataLookupStatus": (lookup or {}).get("status"),
        "metadataLookupSource": (lookup or {}).get("resultSource"),
        "metadataLookupProviders": provider_order,
        "metadataSources": metadata_sources,
        "metadataLookupError": (lookup or {}).get("errorSummary"),
        "providerExecutions": executions,
        "metadataWriteback": metadata_writeback_view_for_lookup_task(
            db, str((lookup or {}).get("id") or "") or None
        ),
        "startedAt": _dt(job.get("startedAt")),
        "finishedAt": _dt(job.get("finishedAt")),
        "createdAt": _dt(job.get("createdAt")),
        "updatedAt": _dt(job.get("updatedAt")),
        "book": _book_view(db, book, user_id),
    }


@router.get("/organize/policy", response_model=OrganizePolicyResponse)
def get_organize_policy_route(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrganizePolicyResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        return OrganizePolicyResponse(
            data=OrganizePolicyPayload.model_validate(
                {"policy": get_organize_policy(db)}
            )
        )
    except ValueError as exc:
        return fail(str(exc), status_code=503)


@router.put("/organize/policy", response_model=OrganizePolicyResponse)
async def update_organize_policy_route(
    payload: UpdateOrganizePolicyRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrganizePolicyResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        policy = update_organize_policy_command(
            db,
            payload.model_dump(by_alias=True, exclude_unset=True),
        )
        return OrganizePolicyResponse(
            data=OrganizePolicyPayload.model_validate({"policy": policy})
        )
    except (TypeError, ValueError) as exc:
        return fail(str(exc), status_code=400)


@router.get("/organize/candidates", response_model=OrganizeCandidatesResponse)
def get_organize_candidates_route(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrganizeCandidatesResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        return OrganizeCandidatesResponse(
            data=OrganizeCandidatesPayload.model_validate(
                {"candidates": organize_candidate_summary(db)}
            )
        )
    except ValueError as exc:
        return fail(str(exc), status_code=503)


@router.get("/organize/runs", response_model=OrganizeRunsResponse)
def list_organize_runs_route(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrganizeRunsResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    limit = _positive_int(request.query_params.get("limit"), 20, 100)
    return OrganizeRunsResponse(
        data=OrganizeRunsPayload.model_validate({"runs": list_organize_runs(db, limit)})
    )


@router.get("/organize/jobs", response_model=OrganizeJobsResponse)
def list_organize_jobs(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> OrganizeJobsResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    requested_page = _positive_int(request.query_params.get("page"), 1, 1_000_000)
    page_size = _positive_int(request.query_params.get("pageSize"), 20, 100)
    search = str(request.query_params.get("search") or "").strip().lower()
    status = str(request.query_params.get("status") or "ALL").strip().upper()
    if status not in {"ALL", "SUCCESS", "FAILED", "RECOGNIZING", "WAITING"}:
        status = "ALL"
    providers = list_metadata_providers(db)
    provider_ids = organize_job_queries.provider_ids_matching_search(
        search,
        providers,
    )
    page_result = organize_job_queries.paginate_organize_jobs(
        db,
        requested_page=requested_page,
        page_size=page_size,
        status=status,
        search=search,
        provider_ids=provider_ids,
    )
    jobs = [_organize_job_list_view(row) for row in page_result.rows]
    referenced_provider_ids = {
        source for row in page_result.rows for source in row.metadata_sources if source
    }
    provider_names = {
        str(provider.get("id")): str(provider.get("name"))
        for provider in providers
        if str(provider.get("id") or "") in referenced_provider_ids
        and provider.get("name")
    }
    return OrganizeJobsResponse(
        data=OrganizeJobsPayload.model_validate(
            {
                "jobs": jobs,
                "page": page_result.page,
                "pageSize": page_result.page_size,
                "total": page_result.total,
                "totalPages": page_result.total_pages,
                "statusCounts": page_result.status_counts,
                "providerNames": provider_names,
            }
        )
    )


@router.get("/organize/pending", response_model=PendingOrganizeJobsResponse)
def list_pending_organize(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PendingOrganizeJobsResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page_size = _positive_int(request.query_params.get("pageSize"), 50, 200)
    rows = organize_job_queries.list_pending_job_rows(db, limit=page_size)
    job_ids = [str(row.get("id") or "") for row in rows]
    lookups = organize_job_queries.latest_lookup_rows_by_job(db, job_ids)
    executions_by_job = organize_job_queries.execution_rows_by_job(db, job_ids)
    jobs = [
        view
        for row in rows
        if (
            view := _organize_job_view(
                db,
                row,
                getattr(user, "id", None),
                pending_only=True,
                lookup=lookups.get(str(row.get("id") or "")),
                executions=executions_by_job.get(str(row.get("id") or ""), []),
            )
        )
        is not None
    ]
    return PendingOrganizeJobsResponse(
        data=PendingOrganizeJobsPayload.model_validate(
            {"jobs": jobs, "books": [job["book"] for job in jobs], "total": len(jobs)}
        )
    )


@router.get("/organize/jobs/{job_id}", response_model=OrganizeJobResponse)
def get_organize_job(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[OrganizeJobResponse | Response, ErrorResponses(OrganizeNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    job = organize_runs.get_job_row(db, job_id)
    if not job:
        raise OrganizeNotFoundError(OrganizeErrorBody(message="整理任务不存在"))
    view = _organize_job_view(db, job, getattr(user, "id", None))
    if not view:
        raise OrganizeNotFoundError(OrganizeErrorBody(message="整理任务不存在"))
    return OrganizeJobResponse(data=OrganizeJobPayload.model_validate({"job": view}))


@router.post("/organize/jobs/{job_id}/recognize", response_model=OrganizeJobResponse)
def recognize_organize_job_route(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    OrganizeJobResponse | Response,
    ErrorResponses(OrganizeBadRequestError, OrganizeNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        recognize_organize_job(db, job_id)
        job = organize_runs.get_job_row(db, job_id) or {}
        return OrganizeJobResponse(
            data=OrganizeJobPayload.model_validate(
                {"job": _organize_job_view(db, job, getattr(user, "id", None))}
            )
        )
    except ValueError as exc:
        body = OrganizeErrorBody(message=str(exc))
        if "不存在" in str(exc):
            raise OrganizeNotFoundError(body) from exc
        raise OrganizeBadRequestError(body) from exc


@router.delete("/organize/jobs/{job_id}", response_model=DeletedOrganizeJobResponse)
def delete_organize_job_route(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    DeletedOrganizeJobResponse | Response,
    ErrorResponses(OrganizeBadRequestError, OrganizeNotFoundError),
]:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    try:
        return DeletedOrganizeJobResponse(
            data=DeletedOrganizeJobPayload.model_validate(
                delete_organize_job(db, job_id)
            )
        )
    except ValueError as exc:
        body = OrganizeErrorBody(message=str(exc))
        if "不存在" in str(exc):
            raise OrganizeNotFoundError(body) from exc
        raise OrganizeBadRequestError(body) from exc
