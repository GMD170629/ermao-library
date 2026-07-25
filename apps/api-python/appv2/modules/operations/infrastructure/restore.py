from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config

from appv2.modules.operations.contracts import (
    RestoreControlInboxPort,
    RestoreExecutorPort,
    RestoreRequest,
)


class FileRestoreInbox(RestoreControlInboxPort):
    def __init__(self, control_root: Path) -> None:
        self._root = control_root
        self._active_path: Path | None = None

    def next_request(self) -> RestoreRequest | None:
        self._root.mkdir(parents=True, exist_ok=True)
        paths = sorted(self._root.glob("restore-*.request.json"))
        if not paths:
            return None
        self._active_path = paths[0]
        payload = json.loads(self._active_path.read_text(encoding="utf-8"))
        return RestoreRequest(
            request_id=str(payload["requestId"]),
            backup_id=uuid.UUID(str(payload["backupId"])),
            archive=str(payload["archive"]),
            checksum=str(payload["checksum"]),
            app_version=str(payload["appVersion"]),
            postgres_major=int(payload["postgresMajor"]),
            alembic_revision=str(payload["alembicRevision"]),
        )

    def complete(self, request: RestoreRequest) -> None:
        self._finish(request, "completed", None)

    def fail(self, request: RestoreRequest, detail: str) -> None:
        self._finish(request, "failed", detail)

    def _finish(self, request: RestoreRequest, status: str, detail: str | None) -> None:
        result = {
            "requestId": request.request_id,
            "backupId": str(request.backup_id),
            "status": status,
            "detail": detail,
            "completedAt": datetime.now(UTC).isoformat(),
        }
        result_path = self._root / f"restore-{request.request_id}.result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if self._active_path is not None:
            self._active_path.unlink(missing_ok=True)
            self._active_path = None


class PgRestoreExecutor(RestoreExecutorPort):
    def __init__(
        self,
        *,
        database_url: str,
        backups_root: Path,
        backend_root: Path,
        expected_version: str,
    ) -> None:
        self._database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._backups_root = backups_root.resolve()
        self._backend_root = backend_root
        self._expected_version = expected_version

    def execute(self, request: RestoreRequest) -> None:
        archive = Path(request.archive).resolve()
        if not archive.is_relative_to(self._backups_root) or not archive.is_file():
            raise ValueError("restore archive is outside the appv2 backup root")
        if request.postgres_major != 18:
            raise ValueError("only PostgreSQL 18 backups can be restored")
        if request.app_version != self._expected_version:
            raise ValueError("backup application version is incompatible")
        if _sha256(archive) != request.checksum:
            raise ValueError("backup checksum mismatch")
        executable = shutil.which("pg_restore")
        if executable is None:
            raise RuntimeError("PostgreSQL 18 pg_restore is not installed")
        subprocess.run(  # noqa: S603 - executable is resolved without a shell
            [
                executable,
                "--clean",
                "--if-exists",
                "--single-transaction",
                "--no-owner",
                "--no-acl",
                f"--dbname={self._database_url}",
                str(archive),
            ],
            check=True,
            timeout=60 * 60,
            env={**os.environ, "PGAPPNAME": "shuku-appv2-restore"},
        )
        config = Config(self._backend_root / "alembic-v2.ini")
        command.upgrade(config, "head")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
