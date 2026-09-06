from __future__ import annotations

"""Run a bounded real-HTTP Reader v5 position acceptance probe.

The probe owns only its temporary storage root and process group.  It reuses
the release sample smoke's fresh-library/import helpers and the shared logged
process helper, while keeping the position scenarios separate from the
longer production sample smoke.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from typing import TypeAlias, TypedDict, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
SCRIPTS_ROOT = REPO_ROOT / "scripts"
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from app.core.config import Settings
from app.modules.reader.presentation.v5_schemas import (
    ReaderV5BootstrapResponse,
    ReaderV5ProgressPut,
    ReaderV5ProgressSnapshot,
    ReaderV5ProgressStateResponse,
    ReaderV5ProgressWriteResponse,
)
from python_backend_sample_smoke import (
    catalog_resources,
    create_fixture_library,
    free_port,
    wait_for_health,
    wait_for_import,
    wait_for_task_api,
    wait_for_worker,
    write_comic_fixture,
    write_epub_fixture,
    write_pdf_fixture,
)
from python_smoke_process import LoggedProcess, start_logged_process

MAX_REQUESTS_PER_CLIENT = 80
REQUEST_TIMEOUT_SECONDS = 15.0
HEALTH_TIMEOUT_SECONDS = 20
WORKER_TIMEOUT_SECONDS = 25

ADMIN_EMAIL = "position-http-admin@example.com"
ADMIN_PASSWORD = "position-http-admin-password"
MEMBER_EMAIL = "position-http-member@example.com"
MEMBER_PASSWORD = "position-http-member-password"

MUTATION_M = "00000000-0000-4000-8000-000000000101"
MUTATION_N = "00000000-0000-4000-8000-000000000102"
MUTATION_C = "00000000-0000-4000-8000-000000000103"
MUTATION_RACE_A = "00000000-0000-4000-8000-000000000104"
MUTATION_RACE_B = "00000000-0000-4000-8000-000000000105"

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

ModelT = TypeVar("ModelT", bound=BaseModel)


class RaceWriteResult(TypedDict):
    acceptedMutationId: str
    acceptedRevision: int
    _probeCompletedAtMonotonic: float


class CheckRecord(TypedDict):
    id: str
    pos: list[str]
    status: str
    details: JsonObject


class CoverageRecord(TypedDict):
    status: str
    evidenceChecks: list[str]
    remaining: str


class RequestBudget:
    """Bound request attempts on the native httpx client request hook."""

    def __init__(self, max_requests: int = MAX_REQUESTS_PER_CLIENT) -> None:
        self.max_requests = max_requests
        self.request_count = 0

    def on_request(self, request: httpx.Request) -> None:
        del request
        self.request_count += 1
        if self.request_count > self.max_requests:
            raise RuntimeError(
                f"position acceptance client exceeded {self.max_requests} requests"
            )


def _http_client(
    base_url: str,
    *,
    budget: RequestBudget,
    cookies: dict[str, str] | None = None,
) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        cookies=cookies,
        follow_redirects=False,
        timeout=REQUEST_TIMEOUT_SECONDS,
        event_hooks={"request": [budget.on_request]},
    )


def position_payload(
    mutation_id: str,
    *,
    client_id: str,
    display_percent: float,
    captured_at_epoch_millis: int,
    href: str,
) -> ReaderV5ProgressPut:
    """Build the same complete v5 request shape used by the Reader clients."""

    display_percent = float(display_percent)
    progression = display_percent / 100
    return ReaderV5ProgressPut(
        schemaVersion=5,
        clientId=client_id,
        mutationId=mutation_id,
        capturedAtEpochMillis=captured_at_epoch_millis,
        position={
            "locator": {
                "href": href,
                "locations": {"totalProgression": progression},
            },
            "presentation": {
                "displayPercent": display_percent,
                "totalProgression": progression,
                "currentHref": href,
                "chapter": None,
                "page": None,
                "playback": None,
            },
        },
    )


def _as_json_value(value: object, context: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list):
        return [_as_json_value(item, f"{context}[]") for item in value]
    if isinstance(value, dict):
        normalized: JsonObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{context} contains a non-string key")
            normalized[key] = _as_json_value(item, f"{context}.{key}")
        return normalized
    raise TypeError(f"{context} is not a JSON value")


def _as_json_object(value: object, context: str) -> JsonObject:
    normalized = _as_json_value(value, context)
    if not isinstance(normalized, dict):
        raise TypeError(f"{context} is not a JSON object")
    return normalized


def _field(data: JsonObject, name: str, context: str) -> JsonValue:
    if name not in data:
        raise TypeError(f"{context} is missing {name}")
    return data[name]


def _json_data(response: httpx.Response) -> JsonObject:
    request_label = f"HTTP {response.request.method} {response.request.url}"
    try:
        payload: object = response.json()
    except ValueError as error:
        raise AssertionError(f"{request_label} returned non-JSON") from error
    if not 200 <= response.status_code < 300:
        raise AssertionError(f"{request_label} returned {response.status_code}")
    payload_object = _as_json_object(payload, f"{request_label} response")
    if payload_object.get("ok") is not True:
        raise AssertionError(f"{request_label} returned an unexpected API envelope")
    return _as_json_object(
        _field(payload_object, "data", f"{request_label} response"),
        f"{request_label} data",
    )


def _validated_v5_response(
    response: httpx.Response, model_type: type[ModelT]
) -> ModelT:
    data = _json_data(response)
    try:
        return model_type.model_validate({"ok": True, "data": data})
    except ValidationError as error:
        request_label = f"HTTP {response.request.method} {response.request.url}"
        raise AssertionError(
            f"{request_label} failed v5 response validation"
        ) from error


def _progress_url(resource_id: str) -> str:
    return f"/api/reader/v5/resources/{resource_id}/progress"


def _status_url(resource_id: str) -> str:
    return f"/api/reader/v5/resources/{resource_id}/reading-status"


def _put_progress(
    client: httpx.Client,
    resource_id: str,
    payload: ReaderV5ProgressPut,
) -> tuple[ReaderV5ProgressWriteResponse, float]:
    started = time.monotonic()
    response = client.put(
        _progress_url(resource_id),
        json=payload.model_dump(mode="json", by_alias=True),
    )
    elapsed = time.monotonic() - started
    return _validated_v5_response(response, ReaderV5ProgressWriteResponse), elapsed


def _abandon_progress_response(
    client: httpx.Client,
    resource_id: str,
    payload: ReaderV5ProgressPut,
) -> float:
    """Send a real PUT and close after headers, abandoning its response body."""

    started = time.monotonic()
    with client.stream(
        "PUT",
        _progress_url(resource_id),
        json=payload.model_dump(mode="json", by_alias=True),
    ) as response:
        if response.status_code != 200:
            raise AssertionError(f"abandoned PUT returned {response.status_code}")
        # The route has already committed the current row and mutation receipt
        # before response headers are available.  Closing here models a lost
        # client response without adding a proxy or changing application code.
        response.close()
    return time.monotonic() - started


def _get_progress(
    client: httpx.Client,
    resource_id: str,
) -> ReaderV5ProgressSnapshot | None:
    response = _validated_v5_response(
        client.get(_progress_url(resource_id)), ReaderV5ProgressStateResponse
    )
    return response.data.progress_snapshot


def _get_bootstrap(
    client: httpx.Client,
    resource_id: str,
) -> ReaderV5BootstrapResponse:
    return _validated_v5_response(
        client.get(f"/api/reader/v5/resources/{resource_id}/bootstrap"),
        ReaderV5BootstrapResponse,
    )


def _snapshot_mutation(snapshot: ReaderV5ProgressSnapshot | None) -> str | None:
    return str(snapshot.mutation_id) if snapshot is not None else None


def _snapshot_summary(snapshot: ReaderV5ProgressSnapshot | None) -> str:
    if snapshot is None:
        return "none"
    return f"mutationId={str(snapshot.mutation_id)!r}, revision={snapshot.revision}"


def _write_summary(response: ReaderV5ProgressWriteResponse) -> str:
    data = response.data
    return (
        f"acceptedMutationId={str(data.accepted_mutation_id)!r}, "
        f"acceptedRevision={data.accepted_revision}, "
        f"currentSnapshot=({_snapshot_summary(data.current_snapshot)})"
    )


def _require_snapshot(
    snapshot: ReaderV5ProgressSnapshot | None,
    *,
    mutation_id: str,
    revision: int,
) -> ReaderV5ProgressSnapshot:
    if snapshot is None:
        raise AssertionError("expected a progress snapshot")
    if str(snapshot.mutation_id) != mutation_id:
        raise AssertionError(
            f"expected mutation {mutation_id!r}, got {_snapshot_summary(snapshot)}"
        )
    if snapshot.revision != revision:
        raise AssertionError(
            f"expected revision {revision}, got {_snapshot_summary(snapshot)}"
        )
    return snapshot


def _create_member(
    admin: httpx.Client,
    library_id: str,
) -> None:
    data = _json_data(
        admin.post(
            "/api/admin/users",
            json={
                "name": "Position HTTP member",
                "email": MEMBER_EMAIL,
                "password": MEMBER_PASSWORD,
                "role": "member",
                "libraryIds": [library_id],
            },
        )
    )
    user = _as_json_object(_field(data, "user", "member creation data"), "member user")
    if user.get("email") != MEMBER_EMAIL:
        raise AssertionError("member creation returned an unexpected user")


def _login(client: httpx.Client, email: str, password: str) -> None:
    _json_data(
        client.post("/api/auth/login", json={"email": email, "password": password})
    )


def _race_write(
    base_url: str,
    cookies: dict[str, str],
    resource_id: str,
    payload: ReaderV5ProgressPut,
    barrier: Barrier,
) -> RaceWriteResult:
    budget = RequestBudget(max_requests=4)
    with _http_client(base_url, cookies=cookies, budget=budget) as client:
        barrier.wait(timeout=REQUEST_TIMEOUT_SECONDS)
        response, _elapsed = _put_progress(client, resource_id, payload)
        data = response.data
        return {
            "acceptedMutationId": str(data.accepted_mutation_id),
            "acceptedRevision": data.accepted_revision,
            "_probeCompletedAtMonotonic": time.monotonic(),
        }


def _fresh_library(
    client: httpx.Client,
    sample_dir: Path,
    settings: Settings,
) -> tuple[str, str]:
    write_epub_fixture(sample_dir / "position-sample.epub")
    write_pdf_fixture(sample_dir / "position-sample.pdf")
    write_comic_fixture(sample_dir / "position-sample.cbz")
    library_id = create_fixture_library(client, sample_dir)
    wait_for_import(settings.database_path, library_id)
    wait_for_task_api(client, library_id)
    resources = catalog_resources(client)
    for _book, resource in resources:
        if str(resource.get("format", "")).lower() == "epub":
            resource_id = resource.get("id")
            if isinstance(resource_id, str) and resource_id:
                return library_id, resource_id
    formats = [str(resource.get("format", "unknown")) for _, resource in resources]
    raise AssertionError(
        f"fresh library did not produce an EPUB resource; formats={formats}"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata(evidence_dir: Path) -> dict[str, object]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status_lines = subprocess.run(
        ["git", "status", "--short", "--untracked-files=all"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    script_path = Path(__file__).resolve()
    focused_test_path = (
        REPO_ROOT / "scripts" / "test_python_reader_position_acceptance_smoke.py"
    )
    return {
        "commit": commit or "unknown",
        "worktree": {
            "dirty": bool(status_lines),
            "statusAtProbeStart": status_lines,
        },
        "source": {
            "positionScript": {
                "path": script_path.relative_to(REPO_ROOT).as_posix(),
                "sha256": _sha256(script_path),
            },
            "focusedTest": {
                "path": focused_test_path.relative_to(REPO_ROOT).as_posix(),
                "sha256": _sha256(focused_test_path),
            },
        },
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "startedAtUtc": datetime.now(UTC).isoformat(),
        "evidenceRoot": str(evidence_dir.resolve()),
        "runId": evidence_dir.name,
        "scope": "fresh temporary SQLite + real HTTP + one imported EPUB",
    }


def _record(
    checks: list[CheckRecord],
    check_id: str,
    pos_ids: tuple[str, ...],
    status: str,
    details: JsonObject,
) -> None:
    checks.append(
        {
            "id": check_id,
            "pos": list(pos_ids),
            "status": status,
            "details": details,
        }
    )


_POS_REMAINING: dict[str, tuple[str, str]] = {
    "POS-01": (
        "PARTIAL",
        "真实 Reader 引擎的文字/页/图片/轨时间语义、退出重开和排版变化未测",
    ),
    "POS-02": (
        "NOT_COVERED",
        "未测客户端捕获间隔、本地持久化、后台返回和确认延迟",
    ),
    "POS-03": (
        "PARTIAL",
        "已测服务重启后的服务端快照/receipt；未测客户端强杀各阶段",
    ),
    "POS-04": (
        "PARTIAL",
        "已测迟到首次 HTTP 写入；未测客户端离线 pending 持久化和重连队列",
    ),
    "POS-05": (
        "PARTIAL",
        "已测真实 HTTP 回包放弃后的重放；未测两个真实客户端的完整链路",
    ),
    "POS-06": (
        "NOT_COVERED",
        "未测客户端生成 N 后释放旧 HTTP ACK 的 pending 清理边界",
    ),
    "POS-07": (
        "PARTIAL",
        "已测并行 HTTP 和迟到首次写入；未能注入/证明服务端事务完成顺序的每种排列",
    ),
    "POS-08": (
        "PARTIAL",
        "已测同资源双账号 namespace；未测第二有效资源/库的真实无权路径",
    ),
    "POS-09": (
        "NOT_COVERED",
        "未测目录显式入口一次性生效、后续保存及重进",
    ),
    "POS-10": (
        "PARTIAL",
        "已测 API 重启后快照和 mutation receipt；未测活动 Reader 不被远端写入跳转",
    ),
    "POS-11": (
        "PARTIAL",
        "已测 HTTP reading-status 独立；未测首页/详情/目录/Reader 展示一致性",
    ),
}


def _build_pos_coverage(checks: list[CheckRecord]) -> dict[str, CoverageRecord]:
    coverage: dict[str, CoverageRecord] = {}
    for pos_id, (status, remaining) in _POS_REMAINING.items():
        evidence = [check["id"] for check in checks if pos_id in check["pos"]]
        coverage[pos_id] = {
            "status": status,
            "evidenceChecks": evidence,
            "remaining": remaining,
        }
    return coverage


def run_position_probe(evidence_dir: Path) -> dict[str, object]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    checks: list[CheckRecord] = []
    process_logs: dict[str, str] = {}
    api_process: LoggedProcess | None = None
    worker_process: LoggedProcess | None = None
    admin: httpx.Client | None = None
    member: httpx.Client | None = None
    base_url = ""
    resource_id = ""
    final_snapshot: ReaderV5ProgressSnapshot | None = None
    failure: Exception | None = None
    first_admin_request_count: int | None = None
    first_member_request_count: int | None = None
    admin_budget: RequestBudget | None = None
    member_budget: RequestBudget | None = None
    admin_after_restart_budget: RequestBudget | None = None
    member_after_restart_budget: RequestBudget | None = None
    report: dict[str, object] = {
        "metadata": _metadata(evidence_dir),
        "result": "RUNNING",
        "checks": checks,
        "posCoverage": {},
        "requestLimits": {
            "maxRequestsPerClient": MAX_REQUESTS_PER_CLIENT,
            "requestTimeoutSeconds": REQUEST_TIMEOUT_SECONDS,
        },
    }

    with TemporaryDirectory(prefix="shuku-python-position-http-") as temporary_root:
        root = Path(temporary_root)
        storage_root = root / "storage"
        inbox = root / "downloads" / "inbox"
        sample_dir = root / "library"
        for path in (storage_root, inbox, sample_dir):
            path.mkdir(parents=True, exist_ok=True)

        settings = Settings(storage_root=str(storage_root))
        api_port = free_port()
        worker_ready_file = root / "import-worker-ready"
        env = {
            **os.environ,
            "SESSION_SECRET": "position-http-session-secret-32chars",
            "STORAGE_ROOT": str(storage_root),
            "DOWNLOAD_INBOX_PATH": str(inbox),
            "IMPORT_WORKER_READY_FILE": str(worker_ready_file),
            "IMPORT_QUEUE_INTERVAL_SECONDS": "1",
            "DOWNLOAD_QUEUE_ENABLED": "false",
            "KINDLE_SEND_QUEUE_ENABLED": "false",
        }

        try:
            subprocess.run(
                [sys.executable, "-m", "app.bootstrap.prestart"],
                cwd=API_ROOT,
                env=env,
                check=True,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            api_process = start_logged_process(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                cwd=API_ROOT,
                env=env,
                log_path=root / "api-first.log",
            )
            base_url = f"http://127.0.0.1:{api_port}"
            wait_for_health(base_url, api_process)
            worker_process = start_logged_process(
                [sys.executable, "-m", "app.worker.main"],
                cwd=API_ROOT,
                env=env,
                log_path=root / "worker.log",
            )
            wait_for_worker(worker_ready_file, worker_process)

            admin_budget = RequestBudget()
            admin = _http_client(base_url, budget=admin_budget)
            setup = _json_data(
                admin.post(
                    "/api/auth/setup",
                    json={
                        "name": "Position HTTP admin",
                        "email": ADMIN_EMAIL,
                        "password": ADMIN_PASSWORD,
                    },
                )
            )
            if setup.get("initialized") is not True:
                raise AssertionError("fresh setup did not initialize")

            library_id, resource_id = _fresh_library(admin, sample_dir, settings)
            _create_member(admin, library_id)
            member_budget = RequestBudget()
            member = _http_client(base_url, budget=member_budget)
            _login(member, MEMBER_EMAIL, MEMBER_PASSWORD)

            initial_bootstrap = _get_bootstrap(admin, resource_id)
            if initial_bootstrap.data.progress_snapshot is not None:
                raise AssertionError("fresh resource unexpectedly had progress")
            _record(
                checks,
                "POS-01-bootstrap-fresh",
                ("POS-01",),
                "PARTIAL",
                {
                    "resourceId": resource_id,
                    "readerType": initial_bootstrap.data.reader_type,
                    "reason": "server bootstrap and persisted snapshot only; no UI locator restore",
                },
            )

            # Independent status remains separate from the progress aggregate.
            status_before = _json_data(admin.get(_status_url(resource_id)))
            if status_before.get("status") != "UNREAD":
                raise AssertionError(
                    f"fresh reading status was not UNREAD: {status_before.get('status')!r}"
                )
            status_write = _json_data(
                admin.put(_status_url(resource_id), json={"status": "FINISHED"})
            )
            if (
                status_write.get("status") != "FINISHED"
                or status_write.get("percent") != 0
            ):
                raise AssertionError(
                    "independent status write returned unexpected status or percent"
                )
            if _get_progress(admin, resource_id) is not None:
                raise AssertionError("reading-status created a progress snapshot")
            _record(
                checks,
                "POS-11-reading-status-independent",
                ("POS-11",),
                "PARTIAL",
                {
                    "freshStatus": status_before.get("status"),
                    "writtenStatus": status_write.get("status"),
                },
            )

            payload_m = position_payload(
                MUTATION_M,
                client_id="position-http-admin-client",
                display_percent=10,
                captured_at_epoch_millis=1_000,
                href="OEBPS/Text/chapter.xhtml#M",
            )
            abandoned_seconds = _abandon_progress_response(
                admin, resource_id, payload_m
            )
            payload_n = position_payload(
                MUTATION_N,
                client_id="position-http-admin-client",
                display_percent=40,
                captured_at_epoch_millis=2_000,
                href="OEBPS/Text/chapter.xhtml#N",
            )
            write_n, n_seconds = _put_progress(admin, resource_id, payload_n)
            if write_n.data.accepted_revision != 2:
                raise AssertionError(
                    f"N did not receive revision 2: {_write_summary(write_n)}"
                )
            replay_m, replay_seconds = _put_progress(admin, resource_id, payload_m)
            if replay_m.data.accepted_revision != 1:
                raise AssertionError(
                    f"M replay did not retain revision 1: {_write_summary(replay_m)}"
                )
            replay_snapshot = replay_m.data.current_snapshot
            n_snapshot = write_n.data.current_snapshot
            if replay_snapshot != n_snapshot:
                raise AssertionError(
                    "idempotent replay changed current snapshot: "
                    f"replay={_snapshot_summary(replay_snapshot)} "
                    f"current={_snapshot_summary(n_snapshot)}"
                )
            _record(
                checks,
                "POS-05-response-loss-idempotent-replay",
                ("POS-05",),
                "PASS",
                {
                    "abandonedResponseSeconds": round(abandoned_seconds, 4),
                    "nRequestSeconds": round(n_seconds, 4),
                    "replayRequestSeconds": round(replay_seconds, 4),
                    "replayAcceptedRevision": replay_m.data.accepted_revision,
                    "currentRevision": replay_snapshot.revision,
                },
            )

            reused_payload = position_payload(
                MUTATION_M,
                client_id="position-http-admin-client",
                display_percent=11,
                captured_at_epoch_millis=1_001,
                href="OEBPS/Text/chapter.xhtml#M-reused",
            )
            reuse_response = admin.put(
                _progress_url(resource_id),
                json=reused_payload.model_dump(mode="json", by_alias=True),
            )
            if reuse_response.status_code != 409:
                raise AssertionError(
                    f"mutation reuse did not return 409: {reuse_response.status_code}"
                )
            reuse_body = _as_json_object(
                reuse_response.json(), "mutation reuse response"
            )
            reuse_error = _as_json_object(
                _field(reuse_body, "error", "mutation reuse response"),
                "mutation reuse error",
            )
            if reuse_error.get("code") != "READER_PROGRESS_MUTATION_REUSE":
                raise AssertionError("unexpected mutation reuse error code")

            payload_c = position_payload(
                MUTATION_C,
                client_id="position-http-offline-client",
                display_percent=20,
                captured_at_epoch_millis=500,
                href="OEBPS/Text/chapter.xhtml#late-offline-C",
            )
            write_c, c_seconds = _put_progress(admin, resource_id, payload_c)
            c_snapshot = _require_snapshot(
                write_c.data.current_snapshot, mutation_id=MUTATION_C, revision=3
            )
            _record(
                checks,
                "POS-07-late-offline-first-submission",
                ("POS-04", "POS-07"),
                "PASS",
                {
                    "capturedAtEpochMillis": payload_c.captured_at_epoch_millis,
                    "receivedAfterRevision": 2,
                    "acceptedRevision": write_c.data.accepted_revision,
                    "currentMutation": str(c_snapshot.mutation_id),
                    "requestSeconds": round(c_seconds, 4),
                    "semantic": "late first submission becomes current by transaction order",
                },
            )

            member_before = _get_progress(member, resource_id)
            if member_before is not None:
                raise AssertionError(
                    "member saw admin progress before own write: "
                    f"{_snapshot_summary(member_before)}"
                )
            member_payload = position_payload(
                MUTATION_M,
                client_id="position-http-member-client",
                display_percent=70,
                captured_at_epoch_millis=7_000,
                href="OEBPS/Text/chapter.xhtml#member",
            )
            member_write, member_seconds = _put_progress(
                member, resource_id, member_payload
            )
            member_snapshot = _require_snapshot(
                member_write.data.current_snapshot,
                mutation_id=MUTATION_M,
                revision=1,
            )
            admin_after_member = _get_progress(admin, resource_id)
            _require_snapshot(admin_after_member, mutation_id=MUTATION_C, revision=3)
            member_missing = member.get(
                "/api/reader/v5/resources/not-a-real-resource/progress"
            )
            if member_missing.status_code != 404:
                raise AssertionError(
                    f"unauthorized/missing resource did not return 404: {member_missing.status_code}"
                )
            _record(
                checks,
                "POS-08-two-user-namespace-isolation",
                ("POS-08",),
                "PASS",
                {
                    "memberAcceptedRevision": member_write.data.accepted_revision,
                    "memberMutation": str(member_snapshot.mutation_id),
                    "adminMutationAfterMemberWrite": _snapshot_mutation(
                        admin_after_member
                    ),
                    "memberWriteSeconds": round(member_seconds, 4),
                    "missingResourceStatus": member_missing.status_code,
                },
            )

            race_barrier = Barrier(2)
            race_payloads = {
                MUTATION_RACE_A: position_payload(
                    MUTATION_RACE_A,
                    client_id="position-http-race-a",
                    display_percent=55,
                    captured_at_epoch_millis=5_500,
                    href="OEBPS/Text/chapter.xhtml#race-A",
                ),
                MUTATION_RACE_B: position_payload(
                    MUTATION_RACE_B,
                    client_id="position-http-race-b",
                    display_percent=65,
                    captured_at_epoch_millis=6_500,
                    href="OEBPS/Text/chapter.xhtml#race-B",
                ),
            }
            admin_cookies = admin.cookies
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        _race_write,
                        base_url,
                        admin_cookies,
                        resource_id,
                        race_payloads[mutation_id],
                        race_barrier,
                    )
                    for mutation_id in (MUTATION_RACE_A, MUTATION_RACE_B)
                ]
                race_results = [
                    future.result(timeout=REQUEST_TIMEOUT_SECONDS * 2)
                    for future in futures
                ]
            race_revisions = sorted(
                result["acceptedRevision"] for result in race_results
            )
            if race_revisions != [4, 5]:
                raise AssertionError(
                    "parallel HTTP writes did not allocate [4, 5]; "
                    f"acceptedRevisions={race_revisions}, "
                    f"mutations={[result['acceptedMutationId'] for result in race_results]}"
                )
            final_snapshot = _get_progress(admin, resource_id)
            _require_snapshot(
                final_snapshot,
                mutation_id=_snapshot_mutation(final_snapshot) or "",
                revision=5,
            )
            final_mutation = _snapshot_mutation(final_snapshot)
            if final_mutation not in race_payloads:
                raise AssertionError(
                    "race final snapshot is not a race write: "
                    f"{_snapshot_summary(final_snapshot)}"
                )
            completion_order = [
                result["acceptedMutationId"]
                for result in sorted(
                    race_results,
                    key=lambda result: float(result["_probeCompletedAtMonotonic"]),
                )
            ]
            _record(
                checks,
                "POS-07-real-http-concurrent-writes",
                ("POS-07",),
                "PASS",
                {
                    "acceptedRevisions": race_revisions,
                    "finalRevision": final_snapshot.revision
                    if final_snapshot is not None
                    else None,
                    "finalMutation": final_mutation,
                    "completionOrder": completion_order,
                    "semantic": "the later SQLite transaction is current; no max-percent selection",
                },
            )

            # Close client sockets before replacing the API process.  Cookies
            # are retained and reattached to a fresh HTTP client after restart.
            admin_cookies = admin.cookies
            member_cookies = member.cookies
            first_admin_request_count = (
                admin_budget.request_count if admin_budget is not None else None
            )
            first_member_request_count = (
                member_budget.request_count if member_budget is not None else None
            )
            admin.close()
            admin = None
            member.close()
            member = None
            first_api_output = api_process.stop()
            process_logs["api-first.log"] = first_api_output
            api_process = None

            api_process = start_logged_process(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(api_port),
                    "--log-level",
                    "warning",
                ],
                cwd=API_ROOT,
                env=env,
                log_path=root / "api-restart.log",
            )
            wait_for_health(base_url, api_process)
            admin_after_restart_budget = RequestBudget()
            member_after_restart_budget = RequestBudget()
            admin = _http_client(
                base_url,
                cookies=admin_cookies,
                budget=admin_after_restart_budget,
            )
            member = _http_client(
                base_url,
                cookies=member_cookies,
                budget=member_after_restart_budget,
            )
            restarted_snapshot = _get_progress(admin, resource_id)
            if restarted_snapshot != final_snapshot:
                raise AssertionError(
                    "progress changed across API restart: "
                    f"before={_snapshot_summary(final_snapshot)} "
                    f"after={_snapshot_summary(restarted_snapshot)}"
                )
            restarted_bootstrap = _get_bootstrap(admin, resource_id)
            if restarted_bootstrap.data.progress_snapshot != final_snapshot:
                raise AssertionError(
                    "bootstrap lost the persisted snapshot after API restart"
                )
            last_race_payload = race_payloads[final_mutation or MUTATION_RACE_A]
            replay_after_restart, restart_replay_seconds = _put_progress(
                admin, resource_id, last_race_payload
            )
            if replay_after_restart.data.accepted_revision != 5:
                raise AssertionError(
                    "post-restart replay lost mutation receipt: "
                    f"{_write_summary(replay_after_restart)}"
                )
            _record(
                checks,
                "POS-03-10-restart-persisted-ack",
                ("POS-03", "POS-10"),
                "PASS",
                {
                    "persistedRevision": restarted_snapshot.revision
                    if restarted_snapshot is not None
                    else None,
                    "persistedMutation": _snapshot_mutation(restarted_snapshot),
                    "replayAcceptedRevision": replay_after_restart.data.accepted_revision,
                    "replaySeconds": round(restart_replay_seconds, 4),
                },
            )
            _record(
                checks,
                "POS-06-client-ack-boundary",
                ("POS-06",),
                "NOT_COVERED",
                {
                    "reason": "server HTTP probe has no client pending store or held late ACK"
                },
            )
            _record(
                checks,
                "POS-02-capture-and-ack-timing",
                ("POS-02",),
                "NOT_COVERED",
                {
                    "reason": "measured request latency is not client capture/save interval evidence"
                },
            )
            _record(
                checks,
                "POS-09-explicit-entry-and-POS-UI",
                ("POS-09",),
                "NOT_COVERED",
                {
                    "reason": "no Reader UI, explicit TOC target, rotation, or re-entry in server probe"
                },
            )

            report["requestCounts"] = {
                "adminBeforeRestart": first_admin_request_count,
                "memberBeforeRestart": first_member_request_count,
                "adminAfterRestart": (
                    admin_after_restart_budget.request_count
                    if admin_after_restart_budget is not None
                    else None
                ),
                "memberAfterRestart": (
                    member_after_restart_budget.request_count
                    if member_after_restart_budget is not None
                    else None
                ),
            }
            report["result"] = "PASS"
        except Exception as error:  # noqa: BLE001
            report["result"] = "FAIL"
            report["error"] = str(error)
            report["traceback"] = traceback.format_exc()
            failure = error
        finally:
            if admin is not None:
                admin.close()
            if member is not None:
                member.close()
            if api_process is not None:
                process_logs["api-restart.log"] = api_process.stop()
            if worker_process is not None:
                process_logs["worker.log"] = worker_process.stop()

    report["posCoverage"] = _build_pos_coverage(checks)
    report["processLogs"] = {}
    for name, content in process_logs.items():
        log_path = evidence_dir / name
        log_path.write_text(content, encoding="utf-8")
        report["processLogs"][name] = str(log_path)
    report_path = evidence_dir / "position-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report["reportPath"] = str(report_path)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if failure is not None:
        raise failure
    return report


def _default_evidence_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "artifacts" / "releases" / "1.0" / "position-http" / stamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=None,
        help="persistent evidence directory; defaults to artifacts/releases/1.0/position-http-<UTC>",
    )
    args = parser.parse_args()
    evidence_dir = (args.evidence_dir or _default_evidence_dir()).resolve()
    try:
        report = run_position_probe(evidence_dir)
    except Exception as error:  # noqa: BLE001
        report_path = evidence_dir / "position-report.json"
        print(f"Reader v5 position HTTP probe FAILED: {error}", file=sys.stderr)
        if report_path.is_file():
            print(f"Evidence report: {report_path}", file=sys.stderr)
        return 1
    print("Reader v5 position HTTP probe PASS")
    print(f"Evidence report: {report['reportPath']}")
    for process_name, path in report.get("processLogs", {}).items():
        print(f"{process_name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
