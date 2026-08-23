"""Write HTTP adapters for upload and ContinueImport."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Never

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import (
    continue_library_import,
    continue_source_import,
    get_library,
    save_uploaded_files,
    source_node_library_id,
)
from app.bootstrap.system import (
    persist_system_setting_values,
    prepare_system_setting_values,
)
from app.contracts.http_errors import ErrorResponses
from app.core.authorization import can_access_library
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImportResult,
)
from app.modules.imports.presentation.path_helpers import enabled_library_for_path
from app.modules.imports.presentation.schemas import (
    ContinueImportPayload,
    ContinueImportResponse,
    ImportBadRequestError,
    ImportErrorBody,
    ImportFileListDetails,
    ImportForbiddenError,
    ImportInternalError,
    ImportNotFoundError,
    ImportUploadPayload,
    ImportUploadResponse,
)
from app.modules.imports.public import (
    SaveUploadedFilesCommand,
    UploadFileTooLargeError,
    UploadPublicationError,
    UploadSource,
    is_supported_import_filename,
    safe_upload_filename,
    target_directory_from_path,
)
from app.services.audio_metadata import is_supported_audio_file
from app.services.import_preferences import (
    extension_is_allowed,
    load_raw_import_preferences_projection,
    matches_ignore_patterns,
    prepare_import_preferences,
)

router = APIRouter(tags=["imports-write"], route_class=TypedContractRoute)
logger = logging.getLogger(__name__)


def _raise_import_error(
    message: str,
    status_code: int = 400,
    details: ImportFileListDetails | None = None,
    *,
    code: str | None = None,
) -> Never:
    body = ImportErrorBody(message=message, code=code, details=details)
    if status_code == 403:
        raise ImportForbiddenError(body)
    if status_code == 404:
        raise ImportNotFoundError(body)
    if status_code == 500:
        raise ImportInternalError(body)
    raise ImportBadRequestError(body)


def _auth(
    db: Session, request: Request, settings: Settings
) -> tuple[User | None, Response | None]:
    return require_user(db, request, settings)


def _continue_payload(result: ContinueImportResult) -> dict[str, object]:
    return {
        "taskId": result.task_id,
        "libraryId": result.library_id,
        "sourceNodeId": result.source_node_id,
        "requeuedFailed": result.requeued_failed,
        "enqueued": result.enqueued_scan,
    }


@router.post("/books/import", status_code=202, response_model=ImportUploadResponse)
def import_book_files(
    request: Request,
    file: Annotated[list[UploadFile] | None, File()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    target_path: Annotated[str | None, Form(alias="targetPath")] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportUploadResponse | Response,
    ErrorResponses(
        ImportBadRequestError,
        ImportForbiddenError,
        ImportNotFoundError,
        ImportInternalError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if user is None:
        _raise_import_error("当前用户无权导入文件", status_code=403)

    uploads = [*(file or []), *(files or [])]
    if not uploads:
        _raise_import_error("请选择要导入的文件")

    upload_names = tuple(
        safe_upload_filename(upload.filename or "upload") for upload in uploads
    )
    unsupported = [
        name for name in upload_names if not is_supported_import_filename(name)
    ]
    if unsupported:
        _raise_import_error(
            "当前版本不支持以下文件后缀。",
            details=ImportFileListDetails(files=unsupported),
        )

    import_preferences = prepare_import_preferences(
        load_raw_import_preferences_projection(db)
    )
    disabled_extensions = [
        name
        for name in upload_names
        if not extension_is_allowed(Path(name), import_preferences)
    ]
    if disabled_extensions:
        _raise_import_error(
            "部分文件后缀已在导入偏好中关闭。",
            details=ImportFileListDetails(files=disabled_extensions),
        )

    try:
        upload_directory = target_directory_from_path(target_path, "上传")
    except ValueError as exc:
        _raise_import_error(str(exc))
    ignored_files = [
        name
        for name in upload_names
        if matches_ignore_patterns(
            upload_directory / name,
            import_preferences.ignore_patterns,
        )
    ]
    if ignored_files:
        _raise_import_error(
            "部分文件命中全局导入忽略规则。",
            details=ImportFileListDetails(files=ignored_files),
        )

    library = enabled_library_for_path(db, upload_directory)
    library_id = str((library or {}).get("id") or "") or None
    if library_id is None:
        _raise_import_error(
            "上传目录必须位于已启用的书库中",
            code="UPLOAD_TARGET_OUTSIDE_LIBRARY",
        )
    if not can_access_library(db, user, library_id):
        _raise_import_error(
            "目标文件夹不存在或无权访问",
            status_code=404,
            code="LIBRARY_NOT_FOUND",
        )

    sources = tuple(
        UploadSource(
            filename=name,
            stream=upload.file,
            is_audio=is_supported_audio_file(name),
            max_bytes=(
                settings.audiobook_max_file_bytes
                if is_supported_audio_file(name)
                else None
            ),
        )
        for upload, name in zip(uploads, upload_names, strict=True)
    )

    # End any read transaction before touching the filesystem.  ContinueImport
    # opens its own short database transaction after publication succeeds.
    db.close()
    try:
        saved_uploads = save_uploaded_files(
            SaveUploadedFilesCommand(
                target_directory=upload_directory,
                sources=sources,
                audio_bundle_max_bytes=settings.audiobook_max_bundle_bytes,
            )
        )
    except UploadFileTooLargeError:
        _raise_import_error("上传文件超过允许的大小")
    except UploadPublicationError:
        logger.exception(
            "upload.files_save_failed",
            extra={
                "actor_id": user.id,
                "target_directory": str(upload_directory),
            },
        )
        _raise_import_error("保存上传文件失败", status_code=500)

    persist_system_setting_values(
        db,
        prepare_system_setting_values(
            {"library.lastUploadTargetPath": str(upload_directory)}
        ),
    )
    result = continue_library_import(db, library_id)
    logger.info(
        "upload.files_saved",
        extra={
            "actor_id": user.id,
            "target_directory": str(upload_directory),
            "file_count": len(saved_uploads),
            "library_id": library_id,
            "task_id": result.task_id,
        },
    )
    return ImportUploadResponse(
        data=ImportUploadPayload.model_validate(
            {
                "results": [
                    {
                        "sourcePath": str(saved.path),
                        "file": saved.filename,
                        "sizeBytes": saved.size_bytes,
                    }
                    for saved in saved_uploads
                ],
                "saved": len(saved_uploads),
                "taskId": result.task_id,
            }
        )
    )


@router.post(
    "/libraries/{library_id}/scan",
    status_code=202,
    response_model=ContinueImportResponse,
)
def continue_library(
    library_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ContinueImportResponse | Response,
    ErrorResponses(ImportForbiddenError, ImportNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    library = get_library(db, library_id)
    if (
        user is None
        or library is None
        or not bool(library.get("enabled"))
        or not can_access_library(db, user, library_id)
    ):
        _raise_import_error("书库不存在或无权访问", status_code=404)
    try:
        result = continue_library_import(db, library_id)
    except LookupError:
        _raise_import_error("书库不存在", status_code=404, code="LIBRARY_NOT_FOUND")
    return ContinueImportResponse(
        data=ContinueImportPayload.model_validate(_continue_payload(result))
    )


@router.post(
    "/source-nodes/{source_node_id}/continue",
    status_code=202,
    response_model=ContinueImportResponse,
)
def continue_source_node(
    source_node_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ContinueImportResponse | Response,
    ErrorResponses(ImportForbiddenError, ImportNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if user is None:
        _raise_import_error("目录不存在或无权访问", status_code=404)
    library_id = source_node_library_id(db, source_node_id)
    library = get_library(db, library_id) if library_id is not None else None
    if (
        library_id is None
        or library is None
        or not bool(library.get("enabled"))
        or not can_access_library(db, user, library_id)
    ):
        _raise_import_error("目录不存在或无权访问", status_code=404)
    try:
        result = continue_source_import(db, source_node_id)
    except LookupError:
        _raise_import_error("目录不存在", status_code=404, code="SOURCE_NODE_NOT_FOUND")
    return ContinueImportResponse(
        data=ContinueImportPayload.model_validate(_continue_payload(result))
    )


__all__ = ["router"]
