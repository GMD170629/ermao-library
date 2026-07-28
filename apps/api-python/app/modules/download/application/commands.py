from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from app.modules.download.application.ports import DownloadUnitOfWork

ResultT = TypeVar("ResultT")


def execute_download_write(
    unit_of_work: DownloadUnitOfWork,
    operation: Callable[[], ResultT],
) -> ResultT:
    try:
        result = operation()
        unit_of_work.commit()
    except Exception:
        unit_of_work.rollback()
        raise
    return result
