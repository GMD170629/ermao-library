"""One Book's bounded work stays separate across a claimed execution."""

import pytest

from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    BookWorkState,
    decode_book_work,
    encode_book_work,
)
from app.modules.imports.domain.scan_policy import ScanScope


def test_request_during_active_run_stays_pending_after_completion() -> None:
    initial = BookWork(resource_ids=("resource-a",), reasons=("RESOURCE_CHANGED",))
    claimed = BookWorkState().request(initial).claim_new()
    changed = claimed.request(
        BookWork(resource_ids=("resource-b",), reasons=("RESOURCE_CHANGED",))
    )

    assert changed.active.resource_ids == ("resource-a",)
    assert changed.pending.resource_ids == ("resource-b",)
    restored = decode_book_work(encode_book_work(changed))
    assert restored == changed
    assert restored.finish_active().pending.resource_ids == ("resource-b",)


def test_work_merge_removes_covered_scopes_and_duplicate_resources() -> None:
    first = BookWork(
        scan_scopes=(ScanScope("book/part", False),),
        resource_ids=("resource-a",),
    )
    second = BookWork(
        scan_scopes=(ScanScope("book", True),),
        resource_ids=("resource-a", "resource-b"),
        identify=True,
    )

    merged = first.merge(second)
    assert merged.scan_scopes == (ScanScope("book", True),)
    assert merged.resource_ids == ("resource-a", "resource-b")
    assert merged.identify


def test_too_many_resource_requests_promote_to_paged_book_resources() -> None:
    work = BookWork()
    for index in range(129):
        work = work.merge(BookWork(resource_ids=(f"resource-{index:03d}",)))
    assert work.scan_scopes == ()
    assert work.resource_ids is None
    assert decode_book_work(encode_book_work(BookWorkState(pending=work))).pending == work


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        '{"active":{},"pending":{}}',
        '{"active":{"scanScopes":[],"resourceIds":[1],"identify":false,"reasons":[]},"pending":{"scanScopes":[],"resourceIds":[],"identify":false,"reasons":[]}}',
    ],
)
def test_corrupt_persisted_work_is_rejected(payload: str) -> None:
    with pytest.raises(ValueError, match="INVALID_BOOK_WORK"):
        decode_book_work(payload)
