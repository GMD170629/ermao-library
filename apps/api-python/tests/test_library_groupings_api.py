from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User
from app.models.library import LibraryWork
from app.services.library_management import sync_work_facets


def _login(client: TestClient, db: Session) -> User:
    user = User(
        email="grouping-api@example.com",
        name="分组接口用户",
        password_hash=hash_password("starshipnas"),
        role="admin",
    )
    db.add(user)
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "starshipnas"},
    )
    assert response.status_code == 200
    return user


def _work(
    work_id: str,
    title: str,
    author: str,
    *,
    series: str | None = None,
    series_index: float | None = None,
    hidden: bool = False,
) -> LibraryWork:
    return LibraryWork(
            library_id="test-library", 
        id=work_id,
        title=title,
        normalized_title=title.casefold(),
        author=author,
        normalized_author=author.casefold(),
        tags="[]",
        series_name=series,
        series_index=series_index,
        hidden=hidden,
    )


def test_grouping_api_and_exact_facet_work_filter(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)
    db_session.add_all(
        [
            _work(
                "volume-2",
                "第二卷",
                "林川、周禾",
                series="星海丛书",
                series_index=2,
            ),
            _work(
                "volume-1",
                "第一卷",
                "林川",
                series="星海丛书",
                series_index=1,
            ),
            _work("similar-author", "相似作者作品", "小林川"),
            _work("unknown-author", "佚名作品", "未知作者"),
            _work(
                "hidden-volume",
                "隐藏卷",
                "秘密作者",
                series="隐藏系列",
                hidden=True,
            ),
        ]
    )
    db_session.commit()
    for work_id in (
        "volume-2",
        "volume-1",
        "similar-author",
        "unknown-author",
        "hidden-volume",
    ):
        sync_work_facets(db_session, work_id)

    shelves = client.get("/api/shelves")
    assert shelves.status_code == 200
    assert shelves.json()["data"]["shelves"] == []

    authors = client.get(
        "/api/library/groupings",
        params={"kind": "AUTHOR", "page": 1, "pageSize": 20},
    )
    assert authors.status_code == 200
    author_groups = authors.json()["data"]["groups"]
    assert [(group["name"], group["bookCount"]) for group in author_groups] == [
        ("周禾", 1),
        ("小林川", 1),
        ("林川", 2),
    ]
    assert all(group["name"] not in {"未知作者", "秘密作者"} for group in author_groups)

    lin_chuan = next(group for group in author_groups if group["name"] == "林川")
    assert {work["id"] for work in lin_chuan["representativeWorks"]} == {
        "volume-1",
        "volume-2",
    }
    assert all(
        work["coverUrl"].startswith("/api/works/")
        for work in lin_chuan["representativeWorks"]
    )
    author_works = client.get(
        "/api/works",
        params={"facetKind": "AUTHOR", "facetId": lin_chuan["id"]},
    )
    assert author_works.status_code == 200
    assert {book["id"] for book in author_works.json()["data"]["books"]} == {
        "volume-1",
        "volume-2",
    }
    assert author_works.json()["data"]["appliedFacet"] == {
        "id": lin_chuan["id"],
        "kind": "AUTHOR",
        "name": "林川",
    }

    detail = client.get("/api/works/volume-1")
    assert detail.status_code == 200
    detail_book = detail.json()["data"]["book"]
    assert detail_book["seriesFacet"]["name"] == "星海丛书"
    assert detail_book["authorFacets"] == [
        {"id": lin_chuan["id"], "kind": "AUTHOR", "name": "林川"}
    ]

    series = client.get(
        "/api/library/groupings",
        params={"kind": "SERIES", "search": "星海"},
    )
    assert series.status_code == 200
    series_groups = series.json()["data"]["groups"]
    assert [(group["name"], group["bookCount"]) for group in series_groups] == [
        ("星海丛书", 2)
    ]
    series_works = client.get(
        "/api/works",
        params={
            "facetKind": "SERIES",
            "facetId": series_groups[0]["id"],
            "sort": "series_index",
            "sortDirection": "asc",
        },
    )
    assert series_works.status_code == 200
    assert [book["id"] for book in series_works.json()["data"]["books"]] == [
        "volume-1",
        "volume-2",
    ]

    missing = client.get(
        "/api/works",
        params={"facetKind": "AUTHOR", "facetId": "missing-facet"},
    )
    assert missing.status_code == 200
    assert missing.json()["data"]["books"] == []
    assert missing.json()["data"]["total"] == 0
    assert missing.json()["data"]["appliedFacet"] is None


def test_grouping_filter_rejects_invalid_parameter_pairs(
    client: TestClient,
    db_session: Session,
) -> None:
    _login(client, db_session)

    for params in (
        {"facetKind": "AUTHOR"},
        {"facetId": "author-id"},
        {"facetKind": "TAG", "facetId": "tag-id"},
    ):
        response = client.get("/api/works", params=params)
        assert response.status_code == 400

    invalid_grouping = client.get(
        "/api/library/groupings",
        params={"kind": "TAG"},
    )
    assert invalid_grouping.status_code == 400
