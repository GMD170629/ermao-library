"""Seven-day storage for generated page thumbnails, never source media."""

from __future__ import annotations

import logging
import os
import re
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from time import time

from app.core.exception_diagnostics import capture_exception, record_exception

LOGGER = logging.getLogger(__name__)
PREVIEW_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60
_SHARD_NAME = re.compile(r"[0-9a-f]{2}")
_CACHE_NAME = re.compile(r"(?:[0-9a-f]{64}\.webp|\.[0-9a-f]{64}\.webp\.[^/\\]+\.tmp)")


class ResourcePreviewCache:
    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()
        self._root = self._storage_root / "cache" / "resource-previews"

    def _path(self, digest: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("invalid preview cache identity")
        return self._root / digest[:2] / f"{digest}.webp"

    def _validate_directory(self, directory: Path) -> None:
        current = self._storage_root
        for component in directory.relative_to(self._storage_root).parts:
            current /= component
            try:
                observed = current.lstat()
            except FileNotFoundError as _caught_error:
                # diagnostics-control-flow: A cache directory may not exist yet.
                capture_exception(_caught_error, level="debug")
                continue
            if not stat.S_ISDIR(observed.st_mode) or getattr(
                observed, "st_file_attributes", 0
            ) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                raise ValueError("preview cache directory is not a regular directory")

    @staticmethod
    def _record_failure(stage: str, error: Exception) -> None:
        record_exception(
            LOGGER,
            "media.preview_cache.failed",
            error,
        )

    def read(self, digest: str) -> bytes | None:
        try:
            path = self._path(digest)
            self._validate_directory(path.parent)
            observed = path.lstat()
            if not stat.S_ISREG(observed.st_mode):
                raise ValueError("preview cache entry is not a regular file")
            if observed.st_mtime <= time() - PREVIEW_CACHE_TTL_SECONDS:
                return None
            flags = (
                os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            with os.fdopen(os.open(path, flags), "rb") as handle:
                return handle.read()
        except FileNotFoundError as _caught_error:
            # diagnostics-control-flow: Cold/expired cache entries are optional;
            # the maintenance worker can also remove one before it is opened.
            capture_exception(_caught_error, level="debug")
            return None
        except (OSError, ValueError) as error:
            capture_exception(error)
            self._record_failure("read", error)
            return None

    def publish(self, digest: str, content: bytes) -> None:
        temporary: Path | None = None
        try:
            path = self._path(digest)
            self._validate_directory(path.parent)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._validate_directory(path.parent)
            with tempfile.NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        except (OSError, ValueError) as error:
            capture_exception(error)
            self._record_failure("publish", error)
        finally:
            if temporary is not None:
                try:
                    self._validate_directory(temporary.parent)
                    temporary.unlink(missing_ok=True)
                except (OSError, ValueError) as error:
                    capture_exception(error)
                    self._record_failure("publish_cleanup", error)

    def prune(self, *, cancelled: Callable[[], bool] = lambda: False) -> int:
        cutoff = time() - PREVIEW_CACHE_TTL_SECONDS
        deleted = 0
        try:
            self._validate_directory(self._root)
            with os.scandir(self._root) as shards:
                for shard in shards:
                    if cancelled():
                        break
                    if not _SHARD_NAME.fullmatch(shard.name):
                        continue
                    try:
                        if not shard.is_dir(follow_symlinks=False):
                            continue
                        directory = Path(shard.path)
                        self._validate_directory(directory)
                        with os.scandir(directory) as entries:
                            for entry in entries:
                                if cancelled():
                                    return deleted
                                if not _CACHE_NAME.fullmatch(entry.name):
                                    continue
                                try:
                                    observed = entry.stat(follow_symlinks=False)
                                    if (
                                        stat.S_ISREG(observed.st_mode)
                                        and observed.st_mtime <= cutoff
                                    ):
                                        self._validate_directory(directory)
                                        Path(entry.path).unlink()
                                        deleted += 1
                                except FileNotFoundError as _caught_error:
                                    # diagnostics-control-flow: Another maintenance
                                    # process may have removed the same cache entry.
                                    capture_exception(_caught_error, level="debug")
                                    continue
                                except (OSError, ValueError) as error:
                                    capture_exception(error)
                                    self._record_failure("prune_entry", error)
                    except FileNotFoundError as _caught_error:
                        # diagnostics-control-flow: An optional cache shard can
                        # disappear concurrently with directory enumeration.
                        capture_exception(_caught_error, level="debug")
                        continue
                    except (OSError, ValueError) as error:
                        capture_exception(error)
                        self._record_failure("prune_directory", error)
        except FileNotFoundError as _caught_error:
            # diagnostics-control-flow: No previews have been cached yet.
            capture_exception(_caught_error, level="debug")
        except (OSError, ValueError) as error:
            capture_exception(error)
            self._record_failure("prune", error)
        return deleted
