"""Atomic filesystem publisher for browser-uploaded import sources."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from app.modules.imports.application.save_uploaded_files import (
    SavedUploadFile,
    SaveUploadedFilesCommand,
    UploadFileTooLargeError,
    UploadPublicationError,
    safe_upload_filename,
)


class AtomicUploadedFilePublisher:
    """Publish a complete batch via hidden temporary files and atomic renames."""

    def __init__(self, *, nonce_factory: Callable[[], str] | None = None) -> None:
        self._nonce_factory = nonce_factory or (lambda: uuid4().hex)

    def publish(self, command: SaveUploadedFilesCommand) -> tuple[SavedUploadFile, ...]:
        directory = command.target_directory.expanduser().resolve()
        if not directory.is_dir():
            raise UploadPublicationError("target directory is not available")

        reserved_paths: set[Path] = set()
        staged_paths: list[Path] = []
        published_paths: list[Path] = []
        saved_files: list[SavedUploadFile] = []
        remaining_audio_bytes = command.audio_bundle_max_bytes
        nonce = self._nonce_factory()

        try:
            for index, source in enumerate(command.sources):
                target = self._unique_target(directory, source.filename, reserved_paths)
                reserved_paths.add(target)
                staged = directory / f".upload-{nonce}-{index}.part"
                staged_paths.append(staged)
                copied = self._copy_stream(
                    source.stream,
                    staged,
                    max_bytes=(
                        min(source.max_bytes, remaining_audio_bytes)
                        if source.is_audio and source.max_bytes is not None
                        else remaining_audio_bytes
                        if source.is_audio
                        else source.max_bytes
                    ),
                )
                if source.is_audio:
                    remaining_audio_bytes -= copied
                    if remaining_audio_bytes < 0:
                        raise UploadFileTooLargeError(
                            "audio batch exceeds configured size"
                        )
                staged.replace(target)
                staged_paths.remove(staged)
                published_paths.append(target)
                saved_files.append(
                    SavedUploadFile(
                        filename=target.name,
                        path=target,
                        size_bytes=copied,
                    )
                )
        except OSError as exc:
            self._cleanup(staged_paths, published_paths)
            raise UploadPublicationError("unable to save upload files") from exc
        except UploadPublicationError:
            self._cleanup(staged_paths, published_paths)
            raise
        return tuple(saved_files)

    @staticmethod
    def _unique_target(
        directory: Path, filename: str, reserved_paths: set[Path]
    ) -> Path:
        safe_name = safe_upload_filename(filename)
        parsed = Path(safe_name)
        stem = parsed.stem or "upload"
        suffix = parsed.suffix
        index = 0
        while True:
            candidate = directory / (
                safe_name if index == 0 else f"{stem}-{index}{suffix}"
            )
            resolved = candidate.resolve()
            if directory != resolved.parent:
                raise UploadPublicationError("target path escapes directory")
            if not resolved.exists() and resolved not in reserved_paths:
                return resolved
            index += 1

    @staticmethod
    def _copy_stream(source: BinaryIO, target: Path, *, max_bytes: int | None) -> int:
        copied = 0
        with target.open("xb") as handle:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if max_bytes is not None and copied > max_bytes:
                    raise UploadFileTooLargeError("upload exceeds configured size")
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        return copied

    @staticmethod
    def _cleanup(staged_paths: list[Path], published_paths: list[Path]) -> None:
        for path in reversed(staged_paths):
            path.unlink(missing_ok=True)
        for path in reversed(published_paths):
            path.unlink(missing_ok=True)
