"""Recoverable file quarantine used by import-task deletion."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from collections.abc import Callable, Iterable

from app.modules.imports.application.deletion import (
    FileCleanupFailure,
    FileCleanupResult,
    ImportFileQuarantineError,
    ImportDeletionToken,
    QuarantinedFile,
)


class LocalImportDeletionFiles:
    def __init__(self, storage_root: Path, allowed_roots: Iterable[Path]) -> None:
        self._storage_root = storage_root.expanduser().resolve()
        roots = [self._storage_root, *allowed_roots]
        self._allowed_roots = tuple(
            sorted(
                {root.expanduser().resolve() for root in roots},
                key=lambda value: len(value.parts),
                reverse=True,
            )
        )
        self._manifest_root = self._storage_root / ".import-delete-manifests"

    def quarantine(
        self, owner_id: str, paths: Iterable[str]
    ) -> ImportDeletionToken:
        operation_id = uuid.uuid4().hex
        requested = tuple(dict.fromkeys(str(path) for path in paths if str(path)))
        missing: list[str] = []
        entries: list[QuarantinedFile] = []
        failures: list[FileCleanupFailure] = []

        for raw_path in requested:
            candidate = Path(raw_path).expanduser()
            try:
                root, resolved = self._resolve_allowed_path(candidate)
                if not resolved.exists() and not resolved.is_symlink():
                    missing.append(str(resolved))
                    continue
                if not resolved.is_file() and not resolved.is_symlink():
                    failures.append(
                        FileCleanupFailure(str(resolved), "目标不是文件")
                    )
                    continue
                quarantine = (
                    root
                    / ".shuku-import-delete"
                    / operation_id
                    / f"{len(entries):04d}-{resolved.name}"
                )
                entries.append(QuarantinedFile(str(resolved), str(quarantine)))
            except OSError as exc:
                failures.append(FileCleanupFailure(str(candidate), str(exc)))

        if failures:
            raise ImportFileQuarantineError(tuple(failures))

        token = ImportDeletionToken(
            operation_id=operation_id,
            owner_id=owner_id,
            manifest_path=str(self._manifest_root / f"{operation_id}.json"),
            files=tuple(entries),
            missing_paths=tuple(missing),
        )
        self._write_manifest(token)
        moved: list[QuarantinedFile] = []
        try:
            for entry in token.files:
                quarantine_path = Path(entry.quarantine_path)
                quarantine_path.parent.mkdir(parents=True, exist_ok=True)
                os.replace(entry.original_path, quarantine_path)
                moved.append(entry)
                self._write_manifest(token)
        except OSError as exc:
            self._restore_entries(reversed(moved))
            self._remove_manifest(token)
            raise ImportFileQuarantineError(
                (FileCleanupFailure(entry.original_path, str(exc)),)
            ) from exc
        return token

    def restore(self, token: ImportDeletionToken) -> None:
        failures = self._restore_entries(reversed(token.files))
        if failures:
            raise ImportFileQuarantineError(tuple(failures))
        self._remove_empty_quarantine_directories(token)
        self._remove_manifest(token)

    def finalize(self, token: ImportDeletionToken) -> FileCleanupResult:
        failures: list[FileCleanupFailure] = []
        deleted = 0
        for entry in token.files:
            quarantine = Path(entry.quarantine_path)
            try:
                if quarantine.exists() or quarantine.is_symlink():
                    quarantine.unlink()
                    deleted += 1
            except OSError as exc:
                failures.append(FileCleanupFailure(entry.original_path, str(exc)))
        if not failures:
            self._remove_empty_quarantine_directories(token)
            self._remove_manifest(token)
        return FileCleanupResult(
            deleted_files=deleted,
            missing_paths=token.missing_paths,
            failures=tuple(failures),
        )

    def recover_pending(
        self,
        *,
        database_record_exists: Callable[[str], bool],
    ) -> tuple[int, int]:
        """Recover manifests left by process interruption.

        A task that still exists owns its files, so they are restored. A deleted
        task has committed successfully and its quarantined files are finalized.
        """

        restored = 0
        finalized = 0
        if not self._manifest_root.exists():
            return restored, finalized
        for manifest in sorted(self._manifest_root.glob("*.json")):
            token = self._read_manifest(manifest)
            if token is None:
                continue
            if database_record_exists(token.owner_id):
                self.restore(token)
                restored += 1
            else:
                self.finalize(token)
                finalized += 1
        return restored, finalized

    def _resolve_allowed_path(self, candidate: Path) -> tuple[Path, Path]:
        absolute = Path(os.path.abspath(candidate))
        resolved = absolute.resolve(strict=False)
        for root in self._allowed_roots:
            original_inside_root = absolute != root and root in absolute.parents
            target_inside_root = resolved != root and root in resolved.parents
            if original_inside_root and target_inside_root:
                return root, absolute
        raise OSError("目标路径不在允许删除的目录中")

    def _write_manifest(self, token: ImportDeletionToken) -> None:
        manifest = Path(token.manifest_path)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest.with_suffix(".json.part")
        payload = {
            "operationId": token.operation_id,
            "ownerId": token.owner_id,
            "manifestPath": token.manifest_path,
            "files": [
                {
                    "originalPath": item.original_path,
                    "quarantinePath": item.quarantine_path,
                }
                for item in token.files
            ],
            "missingPaths": list(token.missing_paths),
        }
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, manifest)

    def _read_manifest(self, manifest: Path) -> ImportDeletionToken | None:
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            return ImportDeletionToken(
                operation_id=str(payload["operationId"]),
                owner_id=str(payload["ownerId"]),
                manifest_path=str(manifest),
                files=tuple(
                    QuarantinedFile(
                        original_path=str(item["originalPath"]),
                        quarantine_path=str(item["quarantinePath"]),
                    )
                    for item in payload.get("files", [])
                ),
                missing_paths=tuple(str(item) for item in payload.get("missingPaths", [])),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _restore_entries(
        self, entries: Iterable[QuarantinedFile]
    ) -> list[FileCleanupFailure]:
        failures: list[FileCleanupFailure] = []
        for entry in entries:
            original = Path(entry.original_path)
            quarantine = Path(entry.quarantine_path)
            if not quarantine.exists() and not quarantine.is_symlink():
                continue
            try:
                original.parent.mkdir(parents=True, exist_ok=True)
                if original.exists() or original.is_symlink():
                    raise OSError("原路径已被占用，无法恢复隔离文件")
                os.replace(quarantine, original)
            except OSError as exc:
                failures.append(FileCleanupFailure(entry.original_path, str(exc)))
        return failures

    def _remove_empty_quarantine_directories(
        self, token: ImportDeletionToken
    ) -> None:
        for directory in {
            Path(entry.quarantine_path).parent for entry in token.files
        }:
            try:
                directory.rmdir()
                directory.parent.rmdir()
            except OSError:
                pass

    def _remove_manifest(self, token: ImportDeletionToken) -> None:
        manifest = Path(token.manifest_path)
        manifest.unlink(missing_ok=True)
        try:
            manifest.parent.rmdir()
        except OSError:
            pass
