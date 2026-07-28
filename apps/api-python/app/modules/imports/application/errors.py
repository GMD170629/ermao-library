"""Named import application errors."""

from __future__ import annotations


class MonitorFolderDeletedDuringImportError(RuntimeError):
    """The monitor-folder configuration disappeared while its task was running."""

    def __init__(self) -> None:
        super().__init__("监控文件夹已在导入期间被删除")
