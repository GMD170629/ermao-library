from __future__ import annotations

from copy import deepcopy
from typing import Literal, TypedDict
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.library.presentation.schemas import (
    BookResponse,
    BooksResponse,
    BookView,
    BulkBookOperationPayload,
    BulkBookOperationResponse,
    ManagementBookListSummary,
    ResourcesResponse,
    ResourceView,
)
from app.modules.reader.application.dto import ReaderReadingStatus
from app.modules.reader.presentation.common_schemas import (
    ReaderReadingStatusData,
    ReaderReadingStatusResponse,
)
from app.modules.reader.presentation.v5_schemas import (
    ReaderV5BootstrapResponse,
    ReaderV5ProgressStateData,
    ReaderV5ProgressStateResponse,
    ReaderV5ProgressWriteData,
    ReaderV5ProgressWriteResponse,
)
from tests.contract.api.test_reader_v5_progress import (
    _payload,
    _progress_url,
    _seed_reader_resource,
)

_BULK_STATUS_URL = "/api/library/operations/books/reading-status"
_BOOKS_URL = "/api/books"
_MID_PROGRESS_MUTATION_ID = UUID("00000000-0000-4000-8000-000000000003")
_POST_UNREAD_PROGRESS_MUTATION_ID = UUID("00000000-0000-4000-8000-000000000004")


class ResourceProjection(TypedDict):
    progress: float
    resource_completed: bool


class BookProjection(TypedDict):
    completed: bool
    resource: ResourceProjection


class PublicProjection(TypedDict):
    detail: BookProjection
    full_list: BookProjection
    resource_list: ResourceProjection
    management_status: Literal["UNREAD", "READING", "FINISHED"]


def _mid_progress_payload() -> dict[str, object]:
    return _payload(
        str(_MID_PROGRESS_MUTATION_ID),
        presentation={
            "displayPercent": 37,
            "totalProgression": 0.37,
            "currentHref": "OEBPS/Text/chapter.xhtml",
            "chapter": None,
            "page": None,
            "playback": None,
        },
    )


def _post_unread_progress_payload() -> dict[str, object]:
    return _payload(
        str(_POST_UNREAD_PROGRESS_MUTATION_ID),
        locator={
            "href": "OEBPS/Text/chapter.xhtml",
            "locations": {"totalProgression": 0.37, "vendor": None},
            "text": {"highlight": ""},
            "unknownExtension": {"empty": [], "nullable": None},
        },
        presentation={
            "displayPercent": 37,
            "totalProgression": 0.37,
            "currentHref": "OEBPS/Text/chapter.xhtml",
            "chapter": None,
            "page": None,
            "playback": None,
        },
    )


def _resource_projection(resource: ResourceView) -> ResourceProjection:
    return {
        "progress": resource.progress,
        "resource_completed": resource.resource_completed,
    }


def _book_projection(book: BookView) -> BookProjection:
    return {
        "completed": book.completed,
        "resource": _resource_projection(book.resources[0]),
    }


def _public_projection(client: TestClient, book_id: str) -> PublicProjection:
    detail_response = client.get(f"{_BOOKS_URL}/{book_id}")
    full_list_response = client.get(_BOOKS_URL, params={"pageSize": 100})
    resource_list_response = client.get(f"{_BOOKS_URL}/{book_id}/resources")
    management_list_response = client.get(
        _BOOKS_URL,
        params={"pageSize": 100, "view": "management"},
    )

    for label, response in (
        ("detail", detail_response),
        ("full_list", full_list_response),
        ("resource_list", resource_list_response),
        ("management_list", management_list_response),
    ):
        assert response.status_code == 200, f"{label}: {response.text}"

    detail_book = BookResponse.model_validate(detail_response.json()).data.book
    full_list = BooksResponse.model_validate(full_list_response.json()).data
    full_book = next(book for book in full_list.books if book.id == book_id)
    assert isinstance(full_book, BookView)

    resource_list = ResourcesResponse.model_validate(resource_list_response.json()).data
    management_list = BooksResponse.model_validate(management_list_response.json()).data
    management_book = next(book for book in management_list.books if book.id == book_id)
    assert isinstance(management_book, ManagementBookListSummary)

    return {
        "detail": _book_projection(detail_book),
        "full_list": _book_projection(full_book),
        "resource_list": _resource_projection(resource_list.resources[0]),
        "management_status": management_book.status_value,
    }


def _reader_status(client: TestClient, resource_id: str) -> ReaderReadingStatusData:
    response = client.get(f"/api/reader/v5/resources/{resource_id}/reading-status")
    assert response.status_code == 200, response.text
    return ReaderReadingStatusResponse.model_validate(response.json()).data


def _progress_state(client: TestClient, resource_id: str) -> ReaderV5ProgressStateData:
    response = client.get(_progress_url(resource_id))
    assert response.status_code == 200, response.text
    return ReaderV5ProgressStateResponse.model_validate(response.json()).data


def _write_book_status(
    client: TestClient,
    *,
    book_id: str,
    status: ReaderReadingStatus,
) -> BulkBookOperationPayload:
    response = client.post(
        _BULK_STATUS_URL,
        json={"ids": [book_id], "status": status},
    )
    assert response.status_code == 200, response.text
    result = BulkBookOperationResponse.model_validate(response.json()).data
    assert result.updated == 1
    assert result.changed_values == 1
    return result


def _write_progress(
    client: TestClient,
    resource_id: str,
) -> ReaderV5ProgressWriteData:
    response = client.put(
        _progress_url(resource_id),
        json=_mid_progress_payload(),
    )
    assert response.status_code == 200, response.text
    return ReaderV5ProgressWriteResponse.model_validate(response.json()).data


def test_finished_without_progress_updates_public_projections(
    client: TestClient,
    db_session: Session,
) -> None:
    _user, resource = _seed_reader_resource(client, db_session)
    book_id = str(resource.book_id)
    resource_id = str(resource.id)

    initial = _progress_state(client, resource_id)
    assert initial.progress_snapshot is None

    _write_book_status(client, book_id=book_id, status="FINISHED")

    status = _reader_status(client, resource_id)
    assert status.resource_id == resource_id
    assert status.status == "FINISHED"
    assert status.percent == 0

    bootstrap_response = client.get(f"/api/reader/v5/resources/{resource_id}/bootstrap")
    assert bootstrap_response.status_code == 200
    bootstrap = ReaderV5BootstrapResponse.model_validate(bootstrap_response.json()).data
    assert bootstrap.resource.resource_completed is True
    assert bootstrap.available_resources[0].resource_completed is True

    after = _progress_state(client, resource_id)
    assert after.progress_snapshot is None
    assert _public_projection(client, book_id) == {
        "detail": {
            "completed": True,
            "resource": {"progress": 0, "resource_completed": True},
        },
        "full_list": {
            "completed": True,
            "resource": {"progress": 0, "resource_completed": True},
        },
        "resource_list": {"progress": 0, "resource_completed": True},
        "management_status": "FINISHED",
    }


def test_unread_preserves_mid_progress_and_public_status(
    client: TestClient,
    db_session: Session,
) -> None:
    _user, resource = _seed_reader_resource(client, db_session)
    book_id = str(resource.book_id)
    resource_id = str(resource.id)

    first_write = _write_progress(client, resource_id)
    replay_response = client.put(
        _progress_url(resource_id),
        json=deepcopy(_mid_progress_payload()),
    )
    assert replay_response.status_code == 200, replay_response.text
    replay_write = ReaderV5ProgressWriteResponse.model_validate(
        replay_response.json()
    ).data
    assert replay_write.accepted_revision == first_write.accepted_revision
    if replay_write.current_snapshot != first_write.current_snapshot:
        pytest.fail("replayed progress snapshot changed")

    before_unread = _progress_state(client, resource_id)
    assert before_unread.progress_snapshot is not None

    _write_book_status(client, book_id=book_id, status="UNREAD")

    status = _reader_status(client, resource_id)
    assert status.resource_id == resource_id
    assert status.status == "UNREAD"
    assert status.percent == 37

    after_unread = _progress_state(client, resource_id)
    if before_unread.progress_snapshot != after_unread.progress_snapshot:
        pytest.fail("UNREAD changed progress snapshot")

    post_unread_write_response = client.put(
        _progress_url(resource_id),
        json=_post_unread_progress_payload(),
    )
    assert post_unread_write_response.status_code == 200, (
        post_unread_write_response.text
    )
    post_unread_write = ReaderV5ProgressWriteResponse.model_validate(
        post_unread_write_response.json()
    ).data
    assert post_unread_write.current_snapshot is not None
    assert (
        post_unread_write.accepted_revision
        == after_unread.progress_snapshot.revision + 1
    )

    status_after_new_progress = _reader_status(client, resource_id)
    assert status_after_new_progress.resource_id == resource_id
    assert status_after_new_progress.status == "UNREAD"
    assert status_after_new_progress.percent == 37

    assert _public_projection(client, book_id) == {
        "detail": {
            "completed": False,
            "resource": {"progress": 37, "resource_completed": False},
        },
        "full_list": {
            "completed": False,
            "resource": {"progress": 37, "resource_completed": False},
        },
        "resource_list": {"progress": 37, "resource_completed": False},
        "management_status": "UNREAD",
    }
