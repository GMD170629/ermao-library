"""Backup HTTP surface, preserving the established `/api/backups` contract."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import require_system_manager
from app.api.typed_route import TypedContractRoute
from app.bootstrap.backup import build_backup_use_cases
from app.bootstrap.media import media_streaming
from app.contracts.http_errors import ErrorResponses
from app.core.config import Settings, get_settings
from app.core.exception_diagnostics import record_exception
from app.db.session import get_db, release_read_transaction
from app.modules.backup.application.operations import (
    BackupArchive,
    BackupNotFoundError,
    BackupOperationError,
    BackupRequestError,
)
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


def _backup_error(error: BackupOperationError) -> Response:
    diagnostic_id = record_exception(
        logging.getLogger(__name__),
        "backup.operation.failed",
        error.__cause__ or error,
        context={"stage": error.stage, "code": error.problem.code},
    )
    stages = {
        "upload": ("上传备份", "Upload backup"),
        "create": ("创建备份", "Create backup"),
        "list": ("读取备份列表", "List backups"),
        "inspect": ("检查备份兼容性", "Check backup compatibility"),
        "validate": ("验证备份数据", "Validate backup data"),
        "restore": ("恢复备份", "Restore backup"),
        "file": ("访问备份文件", "Access backup file"),
    }
    zh, en = stages.get(error.stage, (error.stage, error.stage))
    return JSONResponse(
        {
            "ok": False,
            "error": {
                "code": error.problem.code,
                "message": f"{zh}：{error.problem.message}",
                "params": {
                    **error.problem.params,
                    "messageEn": f"{en}: {error.problem.message_en}",
                    "stage": error.stage,
                    "diagnosticId": diagnostic_id,
                },
            },
        },
        status_code=error.status_code,
        headers={"X-Error-Id": diagnostic_id},
    )


def _backup_payload(backup: BackupArchive) -> dict[str, object]:
    check = backup.compatibility
    compatibility = (
        None
        if check is None
        else {
            "status": check.status,
            "formatVersion": check.format_version,
            "databaseRevision": check.database_revision,
            "requiredFormatVersion": check.required_format_version,
            "requiredDatabaseRevision": check.required_database_revision,
            "problem": None
            if check.problem is None
            else {
                "code": check.problem.code,
                "message": check.problem.message,
                "messageEn": check.problem.message_en,
                "params": check.problem.params,
            },
        }
    )
    return {
        "id": backup.id,
        "kind": backup.kind,
        "name": backup.name,
        "filename": backup.filename,
        "sizeBytes": backup.size_bytes,
        "createdAt": backup.created_at,
        "counts": backup.counts,
        "compatibility": compatibility,
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
    release_read_transaction(db)
    try:
        backups = build_backup_use_cases(db, settings).list.execute()
    except BackupOperationError as error:
        return _backup_error(error)
    return ok({"backups": [_backup_payload(backup) for backup in backups]})


@router.post("/backups/upload", status_code=201, response_model=BackupResponse)
def upload_backup(
    request: Request,
    file: Annotated[UploadFile, File()],
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[BackupResponse | Response, ErrorResponses(SystemManagerRequiredError)]:
    _user, auth_error = _manager(db, request, settings)
    if auth_error:
        return auth_error
    release_read_transaction(db)
    try:
        backup = build_backup_use_cases(db, settings).upload.execute(
            file.filename or "", file.file
        )
    except BackupOperationError as error:
        return _backup_error(error)
    return ok({"backup": _backup_payload(backup)}, status_code=201)


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
    release_read_transaction(db)
    try:
        backup = build_backup_use_cases(db, settings).get.execute(backup_id)
    except BackupOperationError as error:
        return _backup_error(error)
    except (BackupNotFoundError, BackupRequestError) as error:
        record_exception(
            logging.getLogger(__name__),
            "modules.backup.presentation.http.get_backup.failed",
            error,
            context={"stage": "get_backup"},
        )
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
    release_read_transaction(db)
    try:
        backup = build_backup_use_cases(db, settings).create.execute()
    except BackupOperationError as error:
        return _backup_error(error)
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
    release_read_transaction(db)
    try:
        result = build_backup_use_cases(db, settings).restore.execute(backup_id)
    except BackupOperationError as error:
        return _backup_error(error)
    except BackupNotFoundError as error:
        record_exception(
            logging.getLogger(__name__),
            "modules.backup.presentation.http.restore_backup.failed",
            error,
            context={"stage": "restore_backup"},
        )
        return fail("备份不存在", status_code=404)
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
    release_read_transaction(db)
    try:
        deleted = build_backup_use_cases(db, settings).delete.execute(backup_id)
    except BackupOperationError as error:
        return _backup_error(error)
    except BackupRequestError as error:
        record_exception(
            logging.getLogger(__name__),
            "modules.backup.presentation.http.delete_backup.failed",
            error,
            context={"stage": "delete_backup"},
        )
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
    user_id = user.id
    release_read_transaction(db)
    try:
        descriptor = build_backup_use_cases(db, settings).download.execute(backup_id)
    except BackupOperationError as error:
        return _backup_error(error)
    except (BackupNotFoundError, BackupRequestError) as error:
        record_exception(
            logging.getLogger(__name__),
            "modules.backup.presentation.http.download_backup.failed",
            error,
            context={"stage": "download_backup"},
        )
        return fail("备份不存在", status_code=404)
    return media_streaming.send_file(
        Path(descriptor.archive_path),
        request,
        user_id,
        media_type="application/zip",
        name=descriptor.filename,
        route="backup-download",
        asset_id=backup_id,
    )
