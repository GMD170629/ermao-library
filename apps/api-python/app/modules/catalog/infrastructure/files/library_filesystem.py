"""Local filesystem root preflight for current Libraries.

This adapter intentionally probes only a requested root. Discovery and child
symlink handling belong to the scanner/admission stages and are not performed
here.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.modules.catalog.domain.errors import (
    RootExpansionNotAllowed,
    RootNotAbsolute,
    RootNotDirectory,
    RootProtected,
    RootRequired,
    RootUnavailable,
    RootUnreadable,
)
from app.modules.catalog.domain.model import PathComparison
from app.modules.catalog.domain.root_paths import RootObservation


@dataclass(frozen=True, slots=True)
class LibraryFilesystemConfig:
    """Application-owned paths that a user source root must not claim."""

    protected_roots: tuple[Path, ...] = ()

    @classmethod
    def from_paths(cls, paths: Iterable[str | Path]) -> LibraryFilesystemConfig:
        return cls(
            protected_roots=tuple(
                _canonical_existing_or_future_path(Path(path)) for path in paths
            )
        )


class LocalLibraryFilesystem:
    """Filesystem adapter used by current Library configuration use cases."""

    def __init__(self, config: LibraryFilesystemConfig | None = None) -> None:
        self._config = config or LibraryFilesystemConfig()

    def preflight(
        self, requested_path: str, *, path_comparison: PathComparison
    ) -> RootObservation:
        """Resolve and validate one root without traversing its children.

        ``Path.resolve(strict=True)`` accepts a symlink supplied as the root
        and records its canonical target. Child links are not followed here;
        scanner adapters must use ``follow_symlinks=False``.
        """

        if not isinstance(path_comparison, PathComparison):
            raise TypeError("path_comparison must be a PathComparison")
        if not isinstance(requested_path, str) or not requested_path.strip():
            raise RootRequired()
        # ``strip`` is used only to detect an empty value.  Whitespace can be
        # a legitimate filename and must not be silently removed.
        try:
            candidate = Path(requested_path)
        except (TypeError, ValueError) as exc:
            raise RootUnavailable() from exc
        if requested_path.startswith("~"):
            raise RootExpansionNotAllowed()
        if not candidate.is_absolute():
            raise RootNotAbsolute()
        return self._observe(candidate, path_comparison=path_comparison)

    def revalidate(
        self,
        requested_path: str,
        observation: RootObservation,
        *,
        path_comparison: PathComparison,
    ) -> RootObservation:
        """Repeat preflight for the original request path.

        The application use case compares the refreshed claim and filesystem
        identity against the prior observation under the root-registry lease.
        """

        del observation
        return self.preflight(requested_path, path_comparison=path_comparison)

    def _observe(
        self, candidate: Path, *, path_comparison: PathComparison
    ) -> RootObservation:
        # Child-name comparison is a Library grammar setting. Root identity is
        # always normalized with the host filesystem's path semantics.
        del path_comparison
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RootUnavailable() from exc
        if not resolved.is_dir():
            raise RootNotDirectory()
        if not os.access(resolved, os.R_OK | os.X_OK):
            raise RootUnreadable()
        if any(
            _overlaps(resolved, protected) for protected in self._config.protected_roots
        ):
            raise RootProtected()

        # Keep the exact spelling returned by the host filesystem.  NFC is
        # appropriate for comparison keys, but changing the physical path can
        # point at a different (or nonexistent) entry on normalization-sensitive
        # filesystems.
        canonical_path = str(resolved)
        try:
            stat_result = resolved.stat()
        except (OSError, ValueError) as exc:
            raise RootUnavailable() from exc
        filesystem_identity = f"{stat_result.st_dev}:{stat_result.st_ino}"
        components = _root_identity_components(resolved)
        root_path_key = _root_path_key(canonical_path)
        return RootObservation(
            canonical_path=canonical_path,
            root_path_key=root_path_key,
            components=components,
            filesystem_identity=filesystem_identity,
            writable=os.access(resolved, os.W_OK | os.X_OK),
        )


def _canonical_existing_or_future_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return path.expanduser().absolute()


def _overlaps(candidate: Path, protected: Path) -> bool:
    candidate_components = _root_identity_components(candidate)
    protected_components = _root_identity_components(protected)
    return (
        candidate_components[: len(protected_components)] == protected_components
        or protected_components[: len(candidate_components)] == candidate_components
    )


def _root_identity_components(path: Path) -> tuple[str, ...]:
    return tuple(_host_identity_text(part) for part in path.parts)


def _root_path_key(canonical_path: str) -> str:
    return _host_identity_text(canonical_path)


def _host_identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    host_normalized = os.path.normcase(normalized)
    portable = _portable_separators(unicodedata.normalize("NFC", host_normalized))
    return _without_redundant_trailing_separator(portable)


def _portable_separators(value: str) -> str:
    portable = value.replace(os.sep, "/")
    if os.altsep is not None:
        portable = portable.replace(os.altsep, "/")
    return portable


def _without_redundant_trailing_separator(value: str) -> str:
    # Filesystem anchors keep their separator so they remain absolute.
    if value == "/" or (len(value) == 3 and value[1:] == ":/"):
        return value
    return value.rstrip("/")


__all__ = [
    "LibraryFilesystemConfig",
    "LocalLibraryFilesystem",
]
