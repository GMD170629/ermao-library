"""Map ORM row mappings to ImportTaskDTO."""

from __future__ import annotations

from collections.abc import Mapping

from app.modules.imports.application.dto import ImportTaskDTO


def import_task_dto_from_row(row: Mapping[str, object]) -> ImportTaskDTO:
    source_path = row.get("sourcePath")
    if source_path is None:
        source_path = row.get("source_path")
    origin = row.get("origin")
    if origin != "SCAN":
        raise ValueError("Import task origin must be SCAN")
    status = row.get("status")
    return ImportTaskDTO(
        id=str(row["id"]),
        source_path=str(source_path or ""),
        origin=origin,
        status=str(status or "PENDING"),
        original_name=_optional_str(
            row.get("originalName")
            if "originalName" in row
            else row.get("original_name")
        ),
        requested_title=_optional_str(
            row.get("requestedTitle")
            if "requestedTitle" in row
            else row.get("requested_title")
        ),
        requested_author=_optional_str(
            row.get("requestedAuthor")
            if "requestedAuthor" in row
            else row.get("requested_author")
        ),
        recognized_metadata=_optional_mapping(
            row.get("recognizedMetadata")
            if "recognizedMetadata" in row
            else row.get("recognized_metadata")
        ),
        library_id=_optional_str(
            row.get("libraryId") if "libraryId" in row else row.get("library_id")
        ),
        media_kind_policy=str(
            row.get("mediaKindPolicy") or row.get("media_kind_policy") or "MIXED"
        ),
        work_id=_optional_str(
            row.get("workId") if "workId" in row else row.get("work_id")
        ),
        volume_id=_optional_str(
            row.get("volumeId") if "volumeId" in row else row.get("volume_id")
        ),
        task_kind=str(row.get("taskKind") or row.get("task_kind") or "FILE"),
        bundle_key=_optional_str(
            row.get("bundleKey") if "bundleKey" in row else row.get("bundle_key")
        ),
        asset_count=int(row.get("assetCount") or row.get("asset_count") or 1),
        processed_asset_count=int(
            row.get("processedAssetCount") or row.get("processed_asset_count") or 0
        ),
        progress=int(row.get("progress") or 0),
        duplicate=bool(row.get("duplicate") or False),
        duration=int(row.get("duration") or 0),
        error_summary=_optional_str(
            row.get("errorSummary")
            if "errorSummary" in row
            else row.get("error_summary")
        ),
        error_code=_optional_str(
            row.get("errorCode") if "errorCode" in row else row.get("error_code")
        ),
        retryable=bool(row.get("retryable") or False),
        attempts=int(row.get("attempts") or 0),
        lease_owner=_optional_str(
            row.get("leaseOwner") if "leaseOwner" in row else row.get("lease_owner")
        ),
        message=_optional_str(row.get("message")),
    )


def _optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_mapping(value: object | None) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None
