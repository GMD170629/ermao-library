from __future__ import annotations

import pytest

_METHODS = ("get", "post", "put", "patch", "delete", "options", "head")
_PATHS = (
    "/api/reader/v4",
    "/api/reader/v4/",
    "/api/reader/v4/resources/example/progress",
    "/api/reader/v4/resources/example/progress/",
    "/api/reader/v4/resources/example/publication/OEBPS/chapter.xhtml",
)


@pytest.mark.parametrize("method", _METHODS)
@pytest.mark.parametrize("path", _PATHS)
def test_reader_v4_any_route_is_retired(client, method: str, path: str) -> None:
    request = getattr(client, method)
    kwargs = (
        {"json": {"legacy": "payload"}} if method in {"post", "put", "patch"} else {}
    )

    response = request(path, follow_redirects=False, **kwargs)

    assert response.status_code == 410
    if method != "head":
        assert response.json()["error"]["code"] == "READER_PROTOCOL_RETIRED"


def test_reader_v4_success_router_is_not_mounted(client) -> None:
    endpoints = {
        route.endpoint.__module__
        for route in client.app.routes
        if getattr(route, "path", "").startswith("/api/reader/v4")
    }

    assert endpoints == {"app.modules.reader.presentation.v4_tombstone"}
