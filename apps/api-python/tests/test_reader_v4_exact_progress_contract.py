from __future__ import annotations


def test_reader_v4_is_absent_from_public_openapi(client) -> None:
    paths = client.app.openapi()["paths"]

    assert not any(path.startswith("/api/reader/v4") for path in paths)
    assert "/api/reader/v5/resources/{resource_id}/progress" in paths


def test_reader_v4_does_not_reuse_v5_or_legacy_success_handlers(client) -> None:
    v4_routes = [
        route
        for route in client.app.routes
        if getattr(route, "path", "").startswith("/api/reader/v4")
    ]

    assert v4_routes
    assert all(
        route.endpoint.__name__ in {"reader_v4_root", "reader_v4_path"}
        for route in v4_routes
    )
