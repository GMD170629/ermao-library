"""Assemble system-directory statistics and direct directory cleanup."""

from app.core.config import Settings
from app.modules.system.application.storage import StorageManagement
from app.modules.system.infrastructure.storage import FileSystemStorage


def storage_management(settings: Settings) -> StorageManagement:
    root = settings.resolved_storage_root
    return StorageManagement(FileSystemStorage(root))
