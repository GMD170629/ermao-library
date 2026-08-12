"""Retired Edition-first Reader and media HTTP surfaces."""

from __future__ import annotations

from typing import Annotated, Never

from fastapi import APIRouter

from app.api.typed_route import TypedContractRoute
from app.contracts.http_errors import ErrorResponses
from app.contracts.retired_resources import RetiredResourceError, retired_resource_error

router = APIRouter(tags=["reader-v1-retired"], route_class=TypedContractRoute)


def _reader_v1_retired(replacement: str) -> Never:
    raise retired_resource_error(replacement)


@router.get("/reader/preferences", status_code=410)
def list_reader_preferences() -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("Reader v4 stores client preferences locally")


@router.put("/reader/preferences", status_code=410)
async def save_reader_preferences() -> Annotated[
    Never, ErrorResponses(RetiredResourceError)
]:
    return _reader_v1_retired("Reader v4 stores client preferences locally")


@router.get("/reader/preferences/{reader_type}", status_code=410)
def get_reader_preference(
    reader_type: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("Reader v4 stores client preferences locally")


@router.put("/reader/preferences/{reader_type}", status_code=410)
@router.patch("/reader/preferences/{reader_type}", status_code=410)
async def save_reader_preference(
    reader_type: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("Reader v4 stores client preferences locally")


@router.get("/reader/{edition_id}/bootstrap", status_code=410)
def reader_bootstrap(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("/api/reader/v4/volumes/{volumeId}/bootstrap")


@router.get("/editions/{edition_id}/progress", status_code=410)
def get_progress(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("/api/reader/v4/volumes/{volumeId}/progress")


@router.post("/editions/{edition_id}/progress", status_code=410)
@router.put("/editions/{edition_id}/progress", status_code=410)
@router.patch("/editions/{edition_id}/progress", status_code=410)
async def save_progress(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("/api/reader/v4/volumes/{volumeId}/progress")


@router.get("/editions/{edition_id}/file", status_code=410)
@router.head("/editions/{edition_id}/file", status_code=410)
def retired_edition_file(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("/api/volumes/{volumeId}/file")


@router.get("/editions/{edition_id}/cover", status_code=410)
def retired_edition_cover(
    edition_id: str,
) -> Annotated[Never, ErrorResponses(RetiredResourceError)]:
    return _reader_v1_retired("/api/volumes/{volumeId}/cover")
