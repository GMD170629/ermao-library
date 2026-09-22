"""Resolve existing library files using the detail adapter containment rules."""

import logging
from pathlib import Path

from app.core.exception_diagnostics import record_exception


def resolve_existing_library_file(root_value: str, relative_value: str) -> Path | None:
    try:
        root = Path(root_value).expanduser().resolve(strict=True)
        candidate = root.joinpath(*Path(relative_value).parts)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError:
        # diagnostics-control-flow: optional asset-path/PDF-count lookup accepts
        # absent sources and returns no physical path; no operation was attempted.
        return None
    except (OSError, ValueError) as error:
        record_exception(logging.getLogger(__name__), "modules.library.infrastructure.source_paths.resolve_existing_library_file.failed", error,
                         context={"step": "resolve_existing_library_file"})
        return None
    if resolved != candidate or not resolved.is_file():
        return None
    return resolved
