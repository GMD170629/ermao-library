from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from appv2.modules.operations.contracts import (
    BackupArchive,
    BackupExecutorPort,
    BackupManifest,
    BackupView,
    RestoreControlPort,
)


class PgBackupExecutor(BackupExecutorPort):
    def __init__(self, *, database_url: str, backups_root: Path) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._root = backups_root

    def create(self, backup: BackupView) -> tuple[str, int]:
        self._root.mkdir(parents=True, exist_ok=True)
        archive = self._archive(backup)
        executable = shutil.which("pg_dump")
        if executable is None:
            raise RuntimeError("PostgreSQL 18 pg_dump is not installed")
        subprocess.run(  # noqa: S603 - executable is resolved without a shell
            [
                executable,
                "--format=custom",
                "--no-owner",
                "--no-acl",
                f"--file={archive}",
                self._database_url,
            ],
            check=True,
            timeout=60 * 60,
            env={**os.environ, "PGAPPNAME": "shuku-appv2-backup"},
        )
        checksum = _sha256(archive)
        manifest = BackupManifest(
            app_version=backup.app_version,
            postgres_major=backup.postgres_major,
            alembic_revision=backup.alembic_revision,
            checksum=checksum,
            created_at=datetime.now(UTC),
        )
        manifest_path = archive.with_suffix(f"{archive.suffix}.json")
        manifest_path.write_text(
            json.dumps(asdict(manifest), default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return checksum, archive.stat().st_size

    def delete(self, backup: BackupView) -> None:
        archive = self._archive(backup)
        archive.unlink(missing_ok=True)
        archive.with_suffix(f"{archive.suffix}.json").unlink(missing_ok=True)

    def open(self, backup: BackupView) -> BackupArchive:
        archive = self._archive(backup)
        if not archive.is_file() or not backup.checksum:
            raise FileNotFoundError("completed backup archive does not exist")

        def body() -> Iterable[bytes]:
            with archive.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    yield chunk

        return BackupArchive(
            body=body(),
            filename=backup.archive_name,
            size_bytes=archive.stat().st_size,
            checksum=backup.checksum,
        )

    def _archive(self, backup: BackupView) -> Path:
        path = (self._root / backup.archive_name).resolve()
        if not path.is_relative_to(self._root.resolve()):
            raise ValueError("backup archive escapes backup root")
        return path


class FileRestoreControl(RestoreControlPort):
    def __init__(self, *, control_root: Path, backups_root: Path) -> None:
        self._control_root = control_root
        self._backups_root = backups_root

    def request(self, backup: BackupView, requested_by: uuid.UUID) -> str:
        request_id = uuid.uuid4().hex
        self._control_root.mkdir(parents=True, exist_ok=True)
        archive = (self._backups_root / backup.archive_name).resolve()
        if not archive.is_file():
            raise ValueError("backup archive does not exist")
        payload = {
            "requestId": request_id,
            "backupId": str(backup.id),
            "archive": str(archive),
            "checksum": backup.checksum,
            "appVersion": backup.app_version,
            "postgresMajor": backup.postgres_major,
            "alembicRevision": backup.alembic_revision,
            "requestedBy": str(requested_by),
            "requestedAt": datetime.now(UTC).isoformat(),
        }
        temporary = self._control_root / f".restore-{request_id}.tmp"
        request_path = self._control_root / f"restore-{request_id}.request.json"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(request_path)
        return request_id


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
