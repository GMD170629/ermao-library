"""Retired external-source HTTP tombstones (contract-compatible)."""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.contracts.http import MessageError
from app.contracts.http_errors import (
    BasicBadRequestError,
    BasicNotFoundError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.download.presentation.source_schemas import (
    EmptySourceRecordsPayload,
    EmptySourceRecordsResponse,
    EmptySourcesPayload,
    EmptySourcesResponse,
    RetiredSourceMutationRequest,
    RetiredSourceRecordMutationRequest,
    RetiredSourceSearchRequest,
)


class SourceRetiredError(BasicNotFoundError):
    status_code = 410


router = APIRouter(tags=["download-sources"], route_class=TypedContractRoute)


def _auth(db: Session, request: Request, settings: Settings):
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        raise BasicUnauthorizedError(MessageError(message="UNAUTHORIZED"))
    return user


@router.get("/sources")
def list_sources(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    EmptySourcesResponse,
    ErrorResponses(BasicUnauthorizedError),
]:
    _auth(db, request, settings)
    return EmptySourcesResponse(data=EmptySourcesPayload(sources=()))


@router.post("/sources")
def create_source(
    request: Request,
    payload: Annotated[RetiredSourceMutationRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    Never,
    ErrorResponses(BasicUnauthorizedError, SourceRetiredError),
]:
    _auth(db, request, settings)
    del payload
    raise SourceRetiredError(MessageError(message="外部资源功能已移除"))


@router.put("/sources/{source_id}")
@router.patch("/sources/{source_id}")
def update_source(
    source_id: str,
    request: Request,
    payload: Annotated[RetiredSourceMutationRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    del payload
    raise BasicNotFoundError(MessageError(message="来源不存在"))


@router.get("/sources/{source_id}")
def get_source(
    source_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    raise BasicNotFoundError(MessageError(message="来源不存在"))


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    raise BasicNotFoundError(MessageError(message="来源不存在"))


@router.post("/sources/{source_id}/test")
def test_source(
    source_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    raise BasicNotFoundError(MessageError(message="源不存在"))


@router.post("/sources/{source_id}/search")
def search_source(
    source_id: str,
    request: Request,
    payload: Annotated[RetiredSourceSearchRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    Never,
    ErrorResponses(BasicUnauthorizedError, BasicBadRequestError, BasicNotFoundError),
]:
    _auth(db, request, settings)
    keyword = str(
        (payload.keyword if payload is not None else None)
        or (payload.query if payload is not None else None)
        or ""
    ).strip()
    if not keyword:
        raise BasicBadRequestError(MessageError(message="请输入搜索关键词"))
    raise BasicNotFoundError(MessageError(message="源不存在"))


@router.get("/source-search-records")
def list_source_records(
    request: Request,
    sourceId: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[EmptySourceRecordsResponse, ErrorResponses(BasicUnauthorizedError)]:
    _auth(db, request, settings)
    return EmptySourceRecordsResponse(
        data=EmptySourceRecordsPayload(records=(), total=0)
    )


@router.post("/source-search-records")
def create_source_record(
    request: Request,
    payload: Annotated[RetiredSourceRecordMutationRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    del payload
    raise BasicNotFoundError(MessageError(message="源不存在"))


@router.post("/source-search-records/create-download-task")
def create_download_from_search_result(
    request: Request,
    payload: Annotated[RetiredSourceRecordMutationRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    del payload
    raise BasicNotFoundError(MessageError(message="源不存在"))


@router.get("/source-search-records/{record_id}")
def get_source_record(
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    raise BasicNotFoundError(MessageError(message="搜索记录不存在"))


@router.delete("/source-search-records/{record_id}")
def delete_source_record(
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    raise BasicNotFoundError(MessageError(message="搜索记录不存在"))


@router.put("/source-search-records/{record_id}")
def update_source_record(
    record_id: str,
    request: Request,
    payload: Annotated[RetiredSourceRecordMutationRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    del payload
    raise BasicNotFoundError(MessageError(message="搜索记录不存在"))


@router.post("/source-search-records/{record_id}/ignore")
@router.post("/source-search-records/{record_id}/save")
def mark_source_record(
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    raise BasicNotFoundError(MessageError(message="搜索记录不存在"))


@router.post("/source-search-records/{record_id}/create-download-task")
def create_download_from_record(
    record_id: str,
    request: Request,
    payload: Annotated[RetiredSourceRecordMutationRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Never, ErrorResponses(BasicUnauthorizedError, BasicNotFoundError)]:
    _auth(db, request, settings)
    del payload
    raise BasicNotFoundError(MessageError(message="搜索记录不存在"))
