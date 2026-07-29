import re
from collections import Counter
from pathlib import Path

from fastapi.routing import APIRoute

from app.main import create_app


HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _normalize(path: str) -> str:
    path = re.sub(r"\[[^\]]+\]", "{}", path)
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return path


def test_python_api_covers_next_api_route_contracts():
    repo_root = Path(__file__).resolve().parents[3]
    next_api_root = repo_root / "apps" / "web" / "app" / "api"
    expected: set[tuple[str, str]] = set()

    assert not next_api_root.exists(), "Next.js API routes should not contain backend logic; /api is served by Python."

    for route_file in next_api_root.rglob("route.ts"):
        source = route_file.read_text(encoding="utf-8")
        methods = set(re.findall(r"export\s+async\s+function\s+(GET|POST|PUT|PATCH|DELETE)\b", source))
        relative = route_file.parent.relative_to(next_api_root)
        route_path = "/api" if str(relative) == "." else "/api/" + "/".join(relative.parts)
        for method in methods:
            expected.add((method, _normalize(route_path)))

    app = create_app()
    actual: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        for method in methods & HTTP_METHODS:
            actual.add((method, _normalize(path)))

    missing = sorted(expected - actual)
    assert missing == []


def test_registered_api_endpoints_are_owned_by_capability_presentations() -> None:
    app = create_app()
    api_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api")
    ]

    assert len(api_routes) == 180
    legacy = [
        (next(iter(route.methods or ())), route.path, route.endpoint.__module__)
        for route in api_routes
        if route.endpoint.__module__.startswith("app.api.routes")
    ]
    assert legacy == []


def test_migrated_endpoint_sources_match_capability_ownership() -> None:
    app = create_app()
    migrated_modules = {
        "app.modules.auth.presentation.http": 14,
        "app.modules.auth.presentation.users": 8,
        "app.modules.kindle.presentation.http": 10,
        "app.modules.reader.presentation.v2": 6,
        "app.modules.system.presentation.health": 10,
    }
    counts = Counter(
        route.endpoint.__module__
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.endpoint.__module__ in migrated_modules
    )

    assert counts == migrated_modules
    assert sum(counts.values()) == 48


def test_registered_api_method_path_pairs_are_unique() -> None:
    app = create_app()
    pairs = [
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api")
        for method in route.methods or ()
        if method in HTTP_METHODS
    ]

    assert len(pairs) == 179
    assert len(pairs) == len(set(pairs))
