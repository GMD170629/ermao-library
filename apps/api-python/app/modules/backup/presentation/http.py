"""Backup HTTP surface, preserving the established `/api/backups` contract."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager
from app.api.typed_route import TypedContractRoute
from app.bootstrap.backup import build_backup_use_cases
from app.bootstrap.media import media_streaming
from app.contracts.http_errors import ErrorResponses
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.backup.application.operations import (
    BackupArchive,
    BackupFormatError,
    BackupNotFoundError,
)
from app.modules.backup.application.restore import BackupRecordValidationError
from app.modules.backup.presentation.schemas import (
    BackupArchiveResponse,
    BackupDeleteResponse,
    BackupResponse,
    BackupRestoreRequest,
    BackupRestoreResponse,
    BackupsResponse,
    SystemManagerRequiredError,
)
from app.schemas.responses import fail, ok

router = APIRouter(tags=["system"], route_class=TypedContractRoute)


def _manager(db: Session, request: Request, settings: Settings):
    return require_system_manager(db, request, settings)


def _backup_payload(backup: BackupArchive) -> dict[str, object]:
    return {
        "id": backup.id,
        "kind": backup.kind,
        "name": backup.name,
        "filename": backup.filename,
        "sizeBytes": backup.size_bytes,
        "createdAt": backup.created_at,
        "counts": backup.counts,
    }


@router.get("/backups", response_model=BackupsResponse)
def list_backups(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[BackupsResponse | Response, ErrorResponses(SystemManagerRequiredError)]:
    _user, auth_error = _manager(db, request, settings)
    if auth_error:
        return auth_error
    backups = build_backup_use_cases(db, settings).list.execute()
    return ok({"backups": [_backup_payload(backup) for backup in backups]})


@router.get("/backups/{backup_id}", response_model=BackupResponse)
def get_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[BackupResponse | Response, ErrorResponses(SystemManagerRequiredError)]:
    _user, auth_error = _manager(db, request, settings)
    if auth_error:
        return auth_error
    try:
        backup = build_backup_use_cases(db, settings).get.execute(backup_id)
    except (BackupNotFoundError, ValueError):
        return fail("备份不存在", status_code=404)
    return ok({"backup": _backup_payload(backup)})


@router.post("/backups", status_code=201, response_model=BackupResponse)
def create_backup(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[BackupResponse | Response, ErrorResponses(SystemManagerRequiredError)]:
    _user, auth_error = _manager(db, request, settings)
    if auth_error:
        return auth_error
    backup = build_backup_use_cases(db, settings).create.execute()
    return ok({"backup": _backup_payload(backup)}, status_code=201)


@router.post("/backups/{backup_id}/restore", response_model=BackupRestoreResponse)
def restore_backup(
    backup_id: str,
    request: Request,
    _payload: BackupRestoreRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BackupRestoreResponse | Response, ErrorResponses(SystemManagerRequiredError)
]:
    _user, auth_error = _manager(db, request, settings)
    if auth_error:
        return auth_error
    try:
        result = build_backup_use_cases(db, settings).restore.execute(backup_id)
    except BackupNotFoundError:
        return fail("备份不存在", status_code=404)
    except (BackupFormatError, BackupRecordValidationError) as exc:
        return fail(str(exc), status_code=400, code="BACKUP_CONTENT_INVALID")
    except ValueError as exc:
        if str(exc) == "BACKUP_REVISION_UNSUPPORTED":
            return fail(
                "备份数据库版本不受支持，请使用旧版应用恢复后再升级。 "
                "/ Unsupported backup revision; restore it with the old "
                "application before upgrading.",
                status_code=400,
                code="BACKUP_REVISION_UNSUPPORTED",
            )
        return fail(str(exc), status_code=400)
    return ok(
        {
            "id": result.id,
            "restored": True,
            "restoredAt": result.restored_at,
            "counts": result.counts,
            "restoredCounts": result.restored_counts,
            "actualCounts": result.actual_counts,
        }
    )


@router.delete("/backups/{backup_id}", response_model=BackupDeleteResponse)
def delete_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    BackupDeleteResponse | Response, ErrorResponses(SystemManagerRequiredError)
]:
    _user, auth_error = _manager(db, request, settings)
    if auth_error:
        return auth_error
    try:
        deleted = build_backup_use_cases(db, settings).delete.execute(backup_id)
    except ValueError:
        deleted = False
    return ok({"deleted": deleted, "id": backup_id})


@router.get("/backups/{backup_id}/download", response_class=BackupArchiveResponse)
def download_backup(
    backup_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[Response, ErrorResponses(SystemManagerRequiredError)]:
    user, auth_error = _manager(db, request, settings)
    if auth_error:
        return auth_error
    try:
        descriptor = build_backup_use_cases(db, settings).download.execute(backup_id)
    except (BackupNotFoundError, ValueError):
        return fail("备份不存在", status_code=404)
    return media_streaming.send_file(
        Path(descriptor.archive_path),
        request,
        user.id,
        media_type="application/zip",
        name=descriptor.filename,
        route="backup-download",
        asset_id=backup_id,
    )
