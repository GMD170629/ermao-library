import re
from pathlib import Path

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
