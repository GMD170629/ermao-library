"""Safe, bilingual reasons for backup failures; original evidence stays in diagnostics."""

from __future__ import annotations

import errno
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.exception_diagnostics import sanitize_diagnostic_text
from app.modules.backup.application.operations import (
    BackupOperationError,
    BackupProblem,
)
from app.modules.backup.application.restore import BackupRecordValidationError


def problem(code: str, zh: str, en: str, **params: str) -> BackupProblem:
    return BackupProblem(code, zh, en, params)


def failure_problem(error: Exception) -> BackupProblem:
    if isinstance(error, BackupRecordValidationError):
        code, _, field = str(error).partition(":")
        reasons = {
            "BACKUP_FIELD_TYPE_INVALID": (
                "字段类型或日期格式错误",
                "Invalid field type or date format",
            ),
            "BACKUP_TABLE_INVALID": (
                "表记录必须是列表",
                "Table records must be a list",
            ),
            "BACKUP_RECORD_INVALID": ("记录必须是对象", "A record must be an object"),
            "BACKUP_DUPLICATE_PRIMARY_KEY": (
                "记录主键重复",
                "Duplicate record identity",
            ),
            "BACKUP_FOREIGN_KEY_INVALID": (
                "关联记录缺失",
                "Referenced record is missing",
            ),
            "BACKUP_ROW_DEPENDENCY_CYCLE": (
                "记录间存在循环引用",
                "Records contain circular references",
            ),
            "BACKUP_TABLE_DEPENDENCY_CYCLE": (
                "表之间存在循环依赖",
                "Tables contain circular dependencies",
            ),
            "BACKUP_TABLE_UNKNOWN": ("备份包含未知数据表", "Unknown backup table"),
        }
        zh, en = reasons.get(code, ("恢复计划无效", "Invalid restore plan"))
        return problem(
            code,
            f"{zh}：{field}" if field else zh,
            f"{en}: {field}" if field else en,
            field=field,
        )
    # Never stringify SQLAlchemy exceptions: they include statements and record values.
    if isinstance(error, DBAPIError):
        detail = str(error.orig)
        for prefix, code, zh, en in (
            (
                "UNIQUE constraint failed:",
                "BACKUP_UNIQUE_CONSTRAINT",
                "唯一约束冲突",
                "Unique constraint violation",
            ),
            (
                "NOT NULL constraint failed:",
                "BACKUP_REQUIRED_FIELD",
                "缺少必填字段",
                "Required field is missing",
            ),
            (
                "FOREIGN KEY constraint failed",
                "BACKUP_FOREIGN_KEY_INVALID",
                "关联记录缺失",
                "Referenced record is missing",
            ),
            (
                "CHECK constraint failed",
                "BACKUP_CHECK_CONSTRAINT",
                "数据未满足约束",
                "Data violates a check constraint",
            ),
            (
                "database is locked",
                "BACKUP_DATABASE_LOCKED",
                "数据库正在被其他操作占用",
                "Database is locked by another operation",
            ),
            (
                "database or disk is full",
                "BACKUP_DISK_FULL",
                "数据库或磁盘空间不足",
                "Database or disk is full",
            ),
            (
                "disk I/O error",
                "BACKUP_DATABASE_IO",
                "数据库读写发生 I/O 错误",
                "Database I/O error",
            ),
            (
                "attempt to write a readonly database",
                "BACKUP_DATABASE_READONLY",
                "数据库不可写",
                "Database is read-only",
            ),
        ):
            if detail.startswith(prefix):
                field = (
                    detail[len(prefix) :].strip()
                    if code in {"BACKUP_UNIQUE_CONSTRAINT", "BACKUP_REQUIRED_FIELD"}
                    else ""
                )
                return problem(
                    code,
                    f"{zh}：{field}" if field else zh,
                    f"{en}: {field}" if field else en,
                    field=field,
                )
        return problem(
            "BACKUP_DATABASE_ERROR",
            "数据库操作失败："
            + type(error.orig).__name__
            + ": "
            + sanitize_diagnostic_text(error.orig)[:500],
            "Database operation failed: "
            + type(error.orig).__name__
            + ": "
            + sanitize_diagnostic_text(error.orig)[:500],
        )
    if isinstance(error, OSError):
        if error.errno == errno.ENOSPC:
            return problem("BACKUP_DISK_FULL", "磁盘空间不足", "Not enough disk space")
        if error.errno in {errno.EACCES, errno.EPERM}:
            return problem(
                "BACKUP_PERMISSION_DENIED",
                "没有读取或写入备份所需的权限",
                "Permission denied when reading or writing backup data",
            )
        if error.errno == errno.ENOENT:
            return problem(
                "BACKUP_FILE_MISSING",
                "备份文件或操作所需文件不存在",
                "The backup or a required file does not exist",
            )
        summary = sanitize_diagnostic_text(error.strerror or type(error).__name__)
        return problem(
            "BACKUP_IO_ERROR", f"文件读写失败：{summary}", f"File I/O failed: {summary}"
        )
    if isinstance(error, ExceptionGroup):
        recovery_reasons = [
            failure_problem(item)
            for item in error.exceptions
            if isinstance(item, Exception)
        ]
        return problem(
            "BACKUP_RECOVERY_FAILED",
            "操作及清理或回滚失败："
            + "；".join(item.message for item in recovery_reasons),
            "Operation and cleanup or rollback failed: "
            + "; ".join(item.message_en for item in recovery_reasons),
        )
    summary = sanitize_diagnostic_text(str(error))[:500]
    return problem(
        "BACKUP_OPERATION_FAILED",
        f"{type(error).__name__}：{summary}",
        f"{type(error).__name__}: {summary}",
    )


@contextmanager
def backup_stage(stage: str) -> Iterator[None]:
    try:
        yield
    except BackupOperationError:
        raise
    except Exception as error:
        raise BackupOperationError(
            failure_problem(error),
            stage=stage,
            status_code=400
            if isinstance(error, BackupRecordValidationError)
            or (stage == "validate" and isinstance(error, IntegrityError))
            else 500,
        ) from error
