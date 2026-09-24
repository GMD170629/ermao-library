"""One Book task has an immutable validated work scope."""

import pytest

from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    decode_book_work,
    encode_book_work,
)


def test_work_round_trip_has_no_active_or_pending_state() -> None:
    work = BookWork(resource_ids=("resource-a",), reasons=("RESOURCE_CHANGED",))
    assert decode_book_work(encode_book_work(work)) == work
    assert "active" not in encode_book_work(work)
    assert "pending" not in encode_book_work(work)


def test_explicit_scope_is_bounded_and_full_book_has_own_marker() -> None:
    with pytest.raises(ValueError, match="BOOK_WORK_TOO_MANY_RESOURCES"):
        BookWork(resource_ids=tuple(f"resource-{index:03d}" for index in range(129)))
    work = BookWork(resource_ids=None, identify=True)
    assert decode_book_work(encode_book_work(work)) == work


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
