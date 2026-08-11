from __future__ import annotations

from types import TracebackType

from app.modules.download.application.ports import DownloadUnitOfWork


class DownloadWriteTransaction:
    def __init__(self, unit_of_work: DownloadUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    def __enter__(self) -> DownloadWriteTransaction:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exception, traceback
        if exception_type is None:
            self._unit_of_work.commit()
        else:
            self._unit_of_work.rollback()
        return False
