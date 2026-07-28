from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.engine import Engine

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


@dataclass(frozen=True)
class TableState:
    rows: int
    digest: str


@dataclass(frozen=True)
class ProbeResult:
    module: str
    method: str
    path_template: str
    request_path: str
    operation_id: str | None
    expected_statuses: tuple[int, ...]
    status_code: int
    passed: bool
    content_type: str
    documented_response: bool
    response_shape_ok: bool | None
    database_changes: dict[str, dict[str, object]]
    note: str
    response_excerpt: str


class RuntimeProbe:
    def __init__(
        self,
        *,
        base_url: str,
        database_url: str,
        output_path: Path,
    ) -> None:
        self.client = httpx.Client(base_url=base_url, timeout=30)
        self.engine = create_engine(database_url)
        self.output_path = output_path
        self.openapi = self.client.get("/openapi.json").json()
        self.results: list[ProbeResult] = []
        if output_path.exists():
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            self.results = [ProbeResult(**item) for item in existing]

    def close(self) -> None:
        self.client.close()
        self.engine.dispose()

    def login(self, email: str, password: str) -> None:
        response = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        response.raise_for_status()

    def call(
        self,
        module: str,
        method: str,
        path_template: str,
        request_path: str | None = None,
        *,
        expected_statuses: tuple[int, ...] = (200,),
        note: str = "",
        **request_kwargs: Any,
    ) -> ProbeResult:
        actual_path = request_path or path_template
        before = _snapshot(self.engine)
        response = self.client.request(method, actual_path, **request_kwargs)
        after = _snapshot(self.engine)
        operation = self.openapi["paths"].get(path_template, {}).get(method.lower())
        documented_response = bool(
            operation and str(response.status_code) in operation.get("responses", {})
        )
        result = ProbeResult(
            module=module,
            method=method.upper(),
            path_template=path_template,
            request_path=actual_path,
            operation_id=operation.get("operationId") if operation else None,
            expected_statuses=expected_statuses,
            status_code=response.status_code,
            passed=response.status_code in expected_statuses,
            content_type=response.headers.get("content-type", ""),
            documented_response=documented_response,
            response_shape_ok=_response_shape_ok(response),
            database_changes=_database_changes(before, after),
            note=note,
            response_excerpt=_response_excerpt(response),
        )
        self.results.append(result)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(
                [asdict(item) for item in self.results],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return result


def _snapshot(engine: Engine) -> dict[str, TableState]:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    result: dict[str, TableState] = {}
    with engine.connect() as connection:
        for table in metadata.sorted_tables:
            rows = connection.execute(select(table)).mappings().all()
            digest = hashlib.sha256()
            for row in rows:
                normalized = {
                    key: _digest_value(value) for key, value in sorted(row.items())
                }
                digest.update(
                    json.dumps(
                        normalized,
                        ensure_ascii=False,
                        sort_keys=True,
                    ).encode("utf-8")
                )
            result[table.name] = TableState(
                rows=len(rows),
                digest=digest.hexdigest(),
            )
    return result


def _digest_value(value: object) -> object:
    if isinstance(value, bytes):
        return {
            "bytes": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    return value


def _database_changes(
    before: dict[str, TableState],
    after: dict[str, TableState],
) -> dict[str, dict[str, object]]:
    changes: dict[str, dict[str, object]] = {}
    for table_name in sorted(before.keys() | after.keys()):
        old = before.get(table_name, TableState(rows=0, digest=""))
        new = after.get(table_name, TableState(rows=0, digest=""))
        if old != new:
            changes[table_name] = {
                "rowsBefore": old.rows,
                "rowsAfter": new.rows,
                "contentChanged": old.digest != new.digest,
            }
    return changes


def _response_shape_ok(response: httpx.Response) -> bool | None:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return None
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict) or not isinstance(body.get("ok"), bool):
        return False
    if body["ok"]:
        return "data" in body
    error = body.get("error")
    return isinstance(error, dict) and (
        isinstance(error.get("code"), str) or isinstance(error.get("message"), str)
    )


def _response_excerpt(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if any(
        binary_type in content_type
        for binary_type in ("image/", "application/epub+zip", "application/zip")
    ):
        return f"<binary {len(response.content)} bytes>"
    text = response.text.replace("\n", "\\n")
    return text[:1000]
