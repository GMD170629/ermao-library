"""Persistent idempotency keys scoped to a credential and canonical request."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from app.modules.automation.domain.access import AutomationAccessError


class ReceiptStore(Protocol):
    def claim(
        self,
        grant_id: str,
        request_id: str,
        tool: str,
        fingerprint: str,
        created_at_ms: int,
    ) -> dict[str, object] | None: ...
    def complete(
        self, grant_id: str, request_id: str, result: dict[str, object]
    ) -> None: ...


def request_fingerprint(
    tool: str, arguments: dict[str, object], request_id: str
) -> str:
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id) is None:
        raise AutomationAccessError("INVALID_REQUEST_ID")
    canonical = json.dumps(
        [tool, arguments],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


T = TypeVar("T")


@dataclass(frozen=True)
class CompleteReceipt(Generic[T]):
    store: ReceiptStore
    grant_id: str
    request_id: str
    project: Callable[[T], dict[str, object]]

    def complete(self, result: T) -> None:
        self.store.complete(self.grant_id, self.request_id, self.project(result))
