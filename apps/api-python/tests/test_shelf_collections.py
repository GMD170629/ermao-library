from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import LibraryWork


def _login(client: TestClient, db: Session) -> User:
    user = User(
        email="collection-owner@example.com",
        name="合集用户",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={
            "email": "collection-owner@example.com",
            "password": "starshipnas",
        },
    )
    assert response.status_code == 200
    return user


def _create_shelf(
    client: TestClient,
    *,
    name: str,
    kind: str = "STATIC",
    member_shelf_ids: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"name": name, "kind": kind}
    if member_shelf_ids is not None:
        payload["memberShelfIds"] = member_shelf_ids
    response = client.post("/api/shelves", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["data"]["shelf"]


def test_collection_membership_is_many_to_many_and_exposed_in_views(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    static_shelf = _create_shelf(client, name="普通书架")
    smart_shelf = _create_shelf(client, name="智能书架", kind="SMART")
    first_collection = _create_shelf(
        client,
        name="第一合集",
        kind="COLLECTION",
        member_shelf_ids=[str(static_shelf["id"]), str(smart_shelf["id"])],
    )
    second_collection = _create_shelf(
        client,
        name="第二合集",
        kind="COLLECTION",
        member_shelf_ids=[str(static_shelf["id"])],
    )

    listed = client.get("/api/shelves").json()["data"]["shelves"]
    by_id = {shelf["id"]: shelf for shelf in listed}
    assert by_id[first_collection["id"]]["kind"] == "COLLECTION"
    assert by_id[first_collection["id"]]["shelfCount"] == 2
    assert by_id[static_shelf["id"]]["collectionIds"] == [
        first_collection["id"],
        second_collection["id"],
    ]
    assert by_id[smart_shelf["id"]]["collectionIds"] == [first_collection["id"]]

    detail = client.get(f"/api/shelves/{first_collection['id']}?page=1&pageSize=1")
    assert detail.status_code == 200
    collection = detail.json()["data"]["shelf"]
    assert collection["memberShelfIds"] == [
        static_shelf["id"],
        smart_shelf["id"],
    ]
    assert collection["shelfCount"] == 2
    assert collection["totalPages"] == 2
    assert len(collection["shelves"]) == 1
    assert "books" not in collection

    updated = client.patch(
        f"/api/shelves/{static_shelf['id']}",
        json={"collectionIds": [second_collection["id"]]},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["shelf"]["collectionIds"] == [second_collection["id"]]
    first_detail = client.get(f"/api/shelves/{first_collection['id']}").json()["data"][
        "shelf"
    ]
    assert first_detail["memberShelfIds"] == [smart_shelf["id"]]


def test_collection_rejects_books_nesting_and_nonempty_deletion(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    member = _create_shelf(client, name="成员书架")

    with_books = client.post(
        "/api/shelves",
        json={
            "name": "非法合集",
            "kind": "COLLECTION",
            "bookIds": ["work-does-not-matter"],
        },
    )
    assert with_books.status_code == 400
    assert with_books.json()["error"]["code"] == "COLLECTION_CANNOT_CONTAIN_WORKS"

    collection = _create_shelf(
        client,
        name="有效合集",
        kind="COLLECTION",
        member_shelf_ids=[str(member["id"])],
    )
    nested = client.post(
        "/api/shelves",
        json={
            "name": "嵌套合集",
            "kind": "COLLECTION",
            "memberShelfIds": [collection["id"]],
        },
    )
    assert nested.status_code == 400
    assert nested.json()["error"]["code"] == "INVALID_COLLECTION_MEMBER"

    blocked = client.delete(f"/api/shelves/{collection['id']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "SHELF_COLLECTION_NOT_EMPTY"

    db_session.add(
        LibraryWork(
            id="collection-guard-work",
            title="不能加入合集",
            normalized_title="不能加入合集",
            tags="[]",
        )
    )
    db_session.commit()
    bulk_add = client.post(
        "/api/works/bulk",
        json={
            "ids": ["collection-guard-work"],
            "action": "add_to_shelf",
            "shelfId": collection["id"],
        },
    )
    assert bulk_add.status_code == 400

    member_deleted = client.delete(f"/api/shelves/{member['id']}")
    assert member_deleted.status_code == 200
    emptied = client.get(f"/api/shelves/{collection['id']}").json()["data"]["shelf"]
    assert emptied["shelfCount"] == 0
    assert emptied["memberShelfIds"] == []
    deleted = client.delete(f"/api/shelves/{collection['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
