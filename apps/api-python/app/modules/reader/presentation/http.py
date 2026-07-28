"""Retired Reader V1 HTTP surface. Active reading uses /api/reader/v2."""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.contracts.http_errors import ErrorResponses
from app.modules.reader.presentation.schemas import (
    ReaderRetiredBody,
    ReaderRetiredDetails,
    ReaderRetiredError,
)

router = APIRouter(tags=["reader-v1-retired"], route_class=TypedContractRoute)


def _reader_v1_retired(replacement: str) -> Never:
    raise ReaderRetiredError(
        ReaderRetiredBody(
            details=ReaderRetiredDetails(replacement=replacement),
        )
    )


@router.get("/reader/preferences", status_code=410)
def list_reader_preferences() -> Annotated[Never, ErrorResponses(ReaderRetiredError)]:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.put("/reader/preferences", status_code=410)
async def save_reader_preferences() -> Annotated[Never, ErrorResponses(ReaderRetiredError)]:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.get("/reader/preferences/{reader_type}", status_code=410)
def get_reader_preference(reader_type: str) -> Annotated[Never, ErrorResponses(ReaderRetiredError)]:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.put("/reader/preferences/{reader_type}", status_code=410)
@router.patch("/reader/preferences/{reader_type}", status_code=410)
async def save_reader_preference(reader_type: str) -> Annotated[Never, ErrorResponses(ReaderRetiredError)]:
    return _reader_v1_retired("Reader V2 stores per-work client preferences locally")


@router.get("/reader/{edition_id}/bootstrap", status_code=410)
def reader_bootstrap(edition_id: str) -> Annotated[Never, ErrorResponses(ReaderRetiredError)]:
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/bootstrap")


@router.get("/editions/{edition_id}/progress", status_code=410)
def get_progress(edition_id: str) -> Annotated[Never, ErrorResponses(ReaderRetiredError)]:
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/progress")


@router.post("/editions/{edition_id}/progress", status_code=410)
@router.put("/editions/{edition_id}/progress", status_code=410)
@router.patch("/editions/{edition_id}/progress", status_code=410)
async def save_progress(edition_id: str) -> Annotated[Never, ErrorResponses(ReaderRetiredError)]:
    return _reader_v1_retired(f"/api/reader/v2/editions/{edition_id}/progress")
