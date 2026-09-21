"""A durable result participates in the owning business command's transaction."""

from typing import Protocol, TypeVar

ResultT_contra = TypeVar("ResultT_contra", contravariant=True)


class MutationReceipt(Protocol[ResultT_contra]):
    def complete(self, result: ResultT_contra) -> None: ...
