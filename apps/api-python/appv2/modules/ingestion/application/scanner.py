from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from appv2.modules.ingestion.contracts import (
    FileDiscoveryPort,
    ImportRequest,
    IngestionUnitOfWork,
    MonitorFolder,
)

AUDIO_SUFFIXES = {".m4a", ".m4b", ".mp3"}


class IngestionScanner:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], IngestionUnitOfWork],
        discovery: FileDiscoveryPort,
        stability_seconds: float,
    ) -> None:
        self._uow_factory = uow_factory
        self._discovery = discovery
        self._stability_seconds = stability_seconds

    def run_once(self) -> bool:
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            scan = uow.ingestion.claim_scan_run(
                now=now,
                recovery_before=now - timedelta(minutes=10),
            )
            if scan is None:
                return False
            policy = uow.ingestion.get_policy()
            uow.commit()

        try:
            folders = self._folders_for(scan.monitor_folder_id)
            directories_scanned = 0
            files_scanned = 0
            candidates_found = 0
            queued = 0
            ignored = 0
            errors: list[dict[str, str]] = []
            for folder in folders:
                if not folder.enabled:
                    continue
                directories_scanned += 1
                try:
                    configured_ignore = folder.options.get("ignorePatterns", [])
                    folder_ignore_patterns = (
                        [value for value in configured_ignore if isinstance(value, str)]
                        if isinstance(configured_ignore, list)
                        else []
                    )
                    folder_options = {
                        **folder.options,
                        "allowedExtensions": list(policy.allowed_extensions),
                        "ignorePatterns": [
                            *policy.ignore_patterns,
                            *folder_ignore_patterns,
                        ],
                    }
                    candidates, unstable = self._discovery.discover_stable(
                        folder.path,
                        recursive=folder.recursive,
                        stability_seconds=(
                            policy.stability_check_seconds if policy.stability_check_enabled else 0
                        ),
                        options=folder_options,
                    )
                except (OSError, ValueError) as error:
                    errors.append({"path": folder.path, "code": type(error).__name__})
                    continue
                files_scanned += len(candidates) + unstable
                candidates_found += len(candidates)
                ignored += unstable
                new_jobs, known_paths = self._enqueue_candidates(
                    folder=folder,
                    paths=candidates,
                    trigger=scan.trigger,
                    requested_by=scan.requested_by,
                )
                queued += new_jobs
                ignored += known_paths
                with self._uow_factory() as uow:
                    uow.ingestion.update_folder(
                        folder.id,
                        enabled=None,
                        recursive=None,
                        options=None,
                        scanned_at=datetime.now(UTC),
                    )
                    uow.commit()
            with self._uow_factory() as uow:
                uow.ingestion.complete_scan_run(
                    scan.id,
                    directories_scanned=directories_scanned,
                    files_scanned=files_scanned,
                    candidates_found=candidates_found,
                    queued=queued,
                    ignored=ignored,
                    errors=tuple(errors),
                    finished_at=datetime.now(UTC),
                )
                uow.commit()
        except Exception as error:
            with self._uow_factory() as uow:
                uow.ingestion.fail_scan_run(
                    scan.id,
                    errors=(
                        {
                            "path": "",
                            "code": type(error).__name__,
                        },
                    ),
                    finished_at=datetime.now(UTC),
                )
                uow.commit()
            raise
        return True

    def _folders_for(self, monitor_folder_id: uuid.UUID | None) -> list[MonitorFolder]:
        with self._uow_factory() as uow:
            if monitor_folder_id is None:
                return uow.ingestion.list_folders()
            folder = uow.ingestion.get_folder(monitor_folder_id)
            return [folder] if folder is not None else []

    def _enqueue_candidates(
        self,
        *,
        folder: MonitorFolder,
        paths: list[str],
        trigger: str,
        requested_by: uuid.UUID | None,
    ) -> tuple[int, int]:
        queued = 0
        ignored = 0
        now = datetime.now(UTC)
        audio_members: dict[str, list[str]] = {}
        for path in paths:
            candidate = Path(path)
            if candidate.suffix.casefold() not in AUDIO_SUFFIXES:
                continue
            bundle_root = os.path.normcase(os.path.realpath(candidate.parent))
            audio_members.setdefault(bundle_root, []).append(
                os.path.normcase(os.path.realpath(candidate))
            )
        audio_bundles: dict[str, tuple[str, str]] = {}
        for bundle_root, unsorted_members in audio_members.items():
            members = sorted(unsorted_members)
            source_path = members[0]
            idempotency_key = hashlib.sha256(
                f"audio-bundle\0{folder.id}\0{bundle_root}\0".encode() + "\0".join(members).encode()
            ).hexdigest()
            audio_bundles[bundle_root] = (source_path, idempotency_key)
        with self._uow_factory() as uow:
            for path in paths:
                normalized = os.path.normcase(os.path.realpath(path))
                bundle = (
                    audio_bundles.get(os.path.normcase(os.path.realpath(Path(path).parent)))
                    if Path(path).suffix.casefold() in AUDIO_SUFFIXES
                    else None
                )
                source_path, key = (
                    bundle
                    if bundle is not None
                    else (
                        path,
                        hashlib.sha256(f"monitor\0{folder.id}\0{normalized}".encode()).hexdigest(),
                    )
                )
                result = uow.ingestion.observe_and_enqueue(
                    monitor_folder_id=folder.id,
                    normalized_path=normalized,
                    request=ImportRequest(
                        source_path=source_path,
                        requested_by=requested_by,
                        idempotency_key=key,
                        origin="manual" if trigger == "manual" else "watch",
                        monitor_folder_id=folder.id,
                        triggered_by="user" if trigger == "manual" else "system",
                    ),
                    seen_at=now,
                )
                if result is None or result.duplicate:
                    ignored += 1
                else:
                    queued += 1
            uow.commit()
        return queued, ignored
