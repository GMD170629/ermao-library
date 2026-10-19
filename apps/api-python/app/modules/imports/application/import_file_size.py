"""The shared admission rule for new library source files."""

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    reader_safety_budget,
)
from app.modules.imports.application.errors import ImportFileTooLargeError


def validate_import_file_size(size_bytes: int) -> None:
    """Allow exactly the contract maximum; reject larger observed files."""
    if size_bytes < 0:
        raise ValueError("INVALID_IMPORT_FILE_SIZE")
    if size_bytes > reader_safety_budget(ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES):
        raise ImportFileTooLargeError()
