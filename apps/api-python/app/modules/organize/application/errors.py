"""Application errors for organize workflows."""

from __future__ import annotations


class InvalidDuplicateActionError(ValueError):
    code = "INVALID_DUPLICATE_ACTION"

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__("不支持的重复项操作")
