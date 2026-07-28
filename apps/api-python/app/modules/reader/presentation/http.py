"""Retired Reader V1 HTTP surface. Active reading uses /api/reader/v2."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.schemas.responses import fail

router = APIRouter(tags=["reader-v1-retired"])


def _reader_v1_retired(replacement: str) -> Response:
    return fail(
        "READER_V1_RETIRED",
        status_code=410,
        details={"replacement": replacement},
    )


@router.get("/reader/preferences", status_code=410)
def list_reader_preferences() -> Response:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.put("/reader/preferences", status_code=410)
async def save_reader_preferences() -> Response:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.get("/reader/preferences/{reader_type}", status_code=410)
def get_reader_preference(reader_type: str) -> Response:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.put("/reader/preferences/{reader_type}", status_code=410)
@router.patch("/reader/preferences/{reader_type}", status_code=410)
async def save_reader_preference(reader_type: str) -> Response:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.get("/reader/{edition_id}/bootstrap", status_code=410)
def reader_bootstrap(edition_id: str) -> Response:
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/bootstrap")


@router.get("/editions/{edition_id}/progress", status_code=410)
def get_progress(edition_id: str) -> Response:
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/progress")


@router.post("/editions/{edition_id}/progress", status_code=410)
@router.put("/editions/{edition_id}/progress", status_code=410)
@router.patch("/editions/{edition_id}/progress", status_code=410)
async def save_progress(edition_id: str) -> Response:
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/progress")
