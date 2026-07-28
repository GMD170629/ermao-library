"""Retired external-source HTTP tombstones (contract-compatible)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.responses import fail, ok

router = APIRouter(tags=["download-sources"])


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)

@router.get("/sources")
def list_sources(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"sources": []})


@router.post("/sources")
async def create_source(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("外部资源功能已移除", status_code=410)


@router.put("/sources/{source_id}")
@router.patch("/sources/{source_id}")
async def update_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    await request.json()
    return fail("来源不存在", status_code=404)


@router.get("/sources/{source_id}")
def get_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("来源不存在", status_code=404)


@router.delete("/sources/{source_id}")
def delete_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("来源不存在", status_code=404)


@router.post("/sources/{source_id}/test")
def test_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("源不存在", status_code=404)


@router.post("/sources/{source_id}/search")
async def search_source(source_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    keyword = str(payload.get("keyword") or payload.get("query") or "").strip()
    if not keyword:
        return fail("请输入搜索关键词", status_code=400)
    return fail("源不存在", status_code=404)


@router.get("/source-search-records")
def list_source_records(request: Request, sourceId: str | None = None, status: str | None = None, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok({"records": [], "total": 0})


@router.post("/source-search-records")
async def create_source_record(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    await request.json()
    return fail("源不存在", status_code=404)


@router.post("/source-search-records/create-download-task")
async def create_download_from_search_result(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    await request.json()
    return fail("源不存在", status_code=404)


@router.get("/source-search-records/{record_id}")
def get_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.delete("/source-search-records/{record_id}")
def delete_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.put("/source-search-records/{record_id}")
async def update_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.post("/source-search-records/{record_id}/ignore")
@router.post("/source-search-records/{record_id}/save")
def mark_source_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


@router.post("/source-search-records/{record_id}/create-download-task")
async def create_download_from_record(record_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return fail("搜索记录不存在", status_code=404)


