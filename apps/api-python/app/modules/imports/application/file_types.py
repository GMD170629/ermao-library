"""Pure import filename eligibility rules shared by delivery adapters."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.domain.resource_adapters import ADAPTER_SPECS, file_extension

SUPPORTED_IMPORT_FILE_EXTENSIONS = frozenset(
    extension
    for spec in ADAPTER_SPECS
    if not spec.is_directory_adapter
    for extension in spec.file_extensions
)


def is_supported_import_filename(value: str | Path) -> bool:
    return file_extension(Path(value).name) in SUPPORTED_IMPORT_FILE_EXTENSIONS
