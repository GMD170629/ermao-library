"""One lightweight compatibility check shared by listings and restore preflight."""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.exception_diagnostics import record_exception
from app.modules.backup.application.operations import (
    BackupCompatibility,
    BackupOperationError,
)
from app.modules.backup.infrastructure.problems import failure_problem, problem

BACKUP_FORMAT_VERSION = 5


@dataclass(frozen=True)
class InspectedBackup:
    metadata: dict[str, object]
    compatibility: BackupCompatibility


def inspect_backup(path: Path, required_revision: str) -> InspectedBackup:
    metadata: dict[str, object] = {}
    issue = None
    status = "compatible"
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            for name in ("metadata.json", "database-export.json"):
                if names.count(name) != 1:
                    raise BackupOperationError(
                        problem(
                            "BACKUP_MEMBER_INVALID",
                            f"备份中缺少文件或包含重复文件：{name}",
                            f"Missing or duplicate backup member: {name}",
                            member=name,
                        ),
                        stage="inspect",
                    )
            raw = json.loads(archive.read("metadata.json"))
            if not isinstance(raw, dict):
                raise TypeError("metadata.json must contain an object")
            metadata = raw
            for field, valid in (
                (
                    "version",
                    isinstance(raw.get("version"), int)
                    and not isinstance(raw.get("version"), bool),
                ),
                (
                    "databaseRevision",
                    isinstance(raw.get("databaseRevision"), str)
                    and bool(raw.get("databaseRevision")),
                ),
                ("app", isinstance(raw.get("app"), str)),
            ):
                if not valid:
                    raise BackupOperationError(
                        problem(
                            "BACKUP_METADATA_INVALID",
                            f"metadata.json 的 {field} 字段缺失或类型错误",
                            f"metadata.json has a missing or invalid {field} field",
                            field=field,
                        ),
                        stage="inspect",
                    )
            if "createdAt" in raw:
                try:
                    datetime.fromisoformat(str(raw["createdAt"]))
                except ValueError as error:
                    raise BackupOperationError(
                        problem(
                            "BACKUP_METADATA_INVALID",
                            "metadata.json 的创建日期 createdAt 无效",
                            "metadata.json contains an invalid createdAt date",
                            field="createdAt",
                        ),
                        stage="inspect",
                    ) from error
            counts = raw.get("counts")
            if counts is not None and (
                not isinstance(counts, dict)
                or any(
                    not isinstance(v, int) or isinstance(v, bool) or v < 0
                    for v in counts.values()
                )
            ):
                raise BackupOperationError(
                    problem(
                        "BACKUP_METADATA_INVALID",
                        "metadata.json 的 counts 必须包含非负整数",
                        "metadata.json counts must contain non-negative integers",
                        field="counts",
                    ),
                    stage="inspect",
                )
            if raw["app"] != "ermao-books":
                issue = problem(
                    "BACKUP_APP_MISMATCH",
                    "这不是二毛图书的备份",
                    "This backup was not created by Ermao Library",
                )
            elif raw["version"] != BACKUP_FORMAT_VERSION:
                actual = str(raw["version"])
                expected = str(BACKUP_FORMAT_VERSION)
                issue = problem(
                    "BACKUP_FORMAT_MISMATCH",
                    f"备份格式版本为 {actual}，当前要求 {expected}",
                    f"Backup format is {actual}; this application requires {expected}",
                    actual=actual,
                    expected=expected,
                )
            elif raw["databaseRevision"] != required_revision:
                actual = raw["databaseRevision"]
                issue = problem(
                    "BACKUP_DATABASE_MISMATCH",
                    f"备份数据库结构版本为 {actual}，当前要求 {required_revision}",
                    f"Backup database revision is {actual}; this application requires {required_revision}",
                    actual=actual,
                    expected=required_revision,
                )
            if issue:
                status = "incompatible"
    except Exception as error:  # noqa: BLE001 - isolate one damaged archive; retain diagnostics.
        record_exception(
            logging.getLogger(__name__),
            "backup.inspect.failed",
            error,
            context={"stage": "inspect"},
        )
        status = "unreadable"
        if isinstance(error, BackupOperationError):
            issue = error.problem
        elif isinstance(error, zipfile.BadZipFile):
            issue = problem(
                "BACKUP_ZIP_INVALID",
                "备份不是有效的 ZIP 文件或文件已损坏",
                "The backup is not a valid ZIP archive or is damaged",
            )
        elif isinstance(error, json.JSONDecodeError):
            issue = problem(
                "BACKUP_METADATA_INVALID",
                f"metadata.json 的 JSON 语法错误：第 {error.lineno} 行，第 {error.colno} 列",
                f"Invalid JSON in metadata.json at line {error.lineno}, column {error.colno}",
            )
        elif isinstance(error, (ValueError, TypeError, UnicodeError)):
            issue = problem(
                "BACKUP_METADATA_INVALID",
                "metadata.json 必须是有效编码的 JSON 对象",
                "metadata.json must contain a correctly encoded JSON object",
            )
        else:
            issue = failure_problem(error)
    return InspectedBackup(
        metadata,
        BackupCompatibility(
            status="compatible"
            if status == "compatible"
            else "incompatible"
            if status == "incompatible"
            else "unreadable",
            problem=issue,
            format_version=str(metadata["version"])
            if isinstance(metadata.get("version"), int)
            else None,
            database_revision=str(metadata["databaseRevision"])
            if isinstance(metadata.get("databaseRevision"), str)
            else None,
            required_format_version=str(BACKUP_FORMAT_VERSION),
            required_database_revision=required_revision,
        ),
    )


def require_compatible(path: Path, required_revision: str) -> InspectedBackup:
    result = inspect_backup(path, required_revision)
    if result.compatibility.problem:
        raise BackupOperationError(result.compatibility.problem, stage="inspect")
    return result
