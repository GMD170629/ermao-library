from __future__ import annotations


class ShelfCollectionPolicyError(ValueError):
    """A stable, locale-neutral shelf collection policy failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
