import io
import json
from argparse import Namespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts.benchmark_nas_import import Benchmark


class FakeClient:
    def __init__(self, state="SUCCEEDED", successful=2):
        self.state = state
        self.successful = successful
        self.calls = []
        self.failed = [
            {"id": "historic", "state": "FAILED", "errorSummary": "WORKER_INTERRUPTED"}
        ]

    def api(self, path, method="GET", data=None):
        self.calls.append((method, path))
        if path == "/api/auth/login":
            return {}
        if method == "POST":
            assert path == "/api/libraries/lib/scan"
            return {"taskId": "rescan"}
        if path.startswith("/api/library-import-tasks/"):
            return {
                "task": {
                    "id": path.rsplit("/", 1)[1],
                    "libraryId": "lib",
                    "state": self.state,
                    "errorSummary": "original failure",
                }
            }
        if "/import-tasks?" in path:
            return {
                "tasks": self.failed,
                "totalPages": 1,
                "queued": 0,
                "running": 0,
                "completed": 999999,
                "failed": len(self.failed),
            }
        if path.startswith("/api/books?"):
            params = parse_qs(urlsplit(path).query)
            assert params.get("view", [""])[0] != "full"
            rules = json.loads(params["filters"][0])
            assert rules["conditions"] == [
                {"field": "library", "operator": "equals", "value": "lib"}
            ]
            return {
                "total": 2,
                "totalPages": 1,
                "books": [
                    {
                        "id": str(i),
                        "libraryId": "lib",
                        "metadataState": "COMPLETED",
                        "resourceImportSummary": {
                            "ready": int(i < self.successful),
                            "pending": int(i >= self.successful),
                            "failed": 0,
                            "failedFiles": 0,
                        },
                    }
                    for i in range(2)
                ],
            }
        raise AssertionError(path)


@pytest.fixture()
def controller(tmp_path, monkeypatch):
    monkeypatch.setenv("NAS_PERF_EMAIL", "test@example.com")
    monkeypatch.setenv("NAS_PERF_PASSWORD", "test-only")
    benchmark = Benchmark(
        Namespace(
            output=tmp_path,
            library_id="lib",
            scan_id="scan",
            target_books=2,
            generated_books=2,
            seconds=0.01,
            poll_seconds=0.001,
            container=None,
        ),
        FakeClient(),
    )

    def measure(phase, clients):
        benchmark.results["measurements"].append(
            {
                "phase": phase,
                "clients": clients,
                "endpoints": {
                    "list": {"requests": 1, "errors": 0, "p95Ms": 1.0, "p99Ms": 2.0},
                },
            }
        )

    monkeypatch.setattr(benchmark, "measure", measure)
    return benchmark


def summary(benchmark):
    return json.loads(
        (benchmark.args.output / "summary.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("state", ["FAILED", "CANCELLED"])
def test_terminal_scan_fails_before_queue_drain_or_measurement(controller, state):
    controller.client.state = state
    assert controller.execute() == 1
    result = summary(controller)
    assert result["status"] == "failed"
    assert result["finalSnapshot"]["scan"]["state"] == state
    assert "original failure" in result["failure"]["message"]
    assert result["measurements"] == []
    assert not any(
        method == "POST" and path.endswith("/scan")
        for method, path in controller.client.calls
    )
    assert not any(
        "import-tasks?pageSize=1" in path for _, path in controller.client.calls
    )
    assert (controller.args.output / "failure.json").exists()
    assert (controller.args.output / "report.md").exists()


def test_pending_scan_is_rechecked_during_wait(controller, monkeypatch):
    controller.client.state = "RUNNING"

    def fail_after_first_poll():
        controller.client.state = "FAILED"

    monkeypatch.setattr(controller, "host_sample", fail_after_first_poll)
    assert controller.execute() == 1
    assert len(summary(controller)["measurements"]) == 1
    assert not any(
        method == "POST" and path.endswith("/scan")
        for method, path in controller.client.calls
    )


def test_historical_success_task_count_is_not_successful_book_count(controller):
    controller.client.successful = 1
    assert controller.execute() == 1
    result = summary(controller)
    assert result["successfulBooks"] == 1
    assert result["discoveredBooks"] == result["generatedBooks"] == 2
    assert len(result["measurements"]) == 1
    assert result["newFailedTasks"] == []


def test_complete_run_keeps_historical_failure_separate(controller):
    assert controller.execute() == 0
    result = summary(controller)
    assert result["status"] == "completed"
    assert result["successfulBooks"] == 2
    assert len(result["measurements"]) == 5
    assert len(result["baselineFailedTasks"]) == 1
    assert result["newFailedTasks"] == []
    assert (
        sum(
            method == "POST" and path.endswith("/scan")
            for method, path in controller.client.calls
        )
        == 1
    )
    assert any("12,000 PDFs" in line for line in result["limitations"])


@pytest.mark.parametrize(
    "error", [RuntimeError("controller broke"), KeyboardInterrupt()]
)
def test_controller_failure_keeps_prior_metrics(controller, monkeypatch, error):
    measure = controller.measure

    def fail(phase, clients):
        measure(phase, clients)
        raise error

    monkeypatch.setattr(controller, "measure", fail)
    assert controller.execute() == 1
    result = summary(controller)
    assert len(result["measurements"]) == 1
    assert result["failure"]["type"] == type(error).__name__
    assert "Traceback" in result["failure"]["traceback"]


def test_api_failure_keeps_full_body_and_metrics(controller, monkeypatch):
    measure = controller.measure

    def fail(phase, clients):
        measure(phase, clients)
        raise HTTPError(
            "http://test", 500, "error", {}, io.BytesIO(b"full original error\nstack")
        )

    monkeypatch.setattr(controller, "measure", fail)
    assert controller.execute() == 1
    result = summary(controller)
    assert result["failure"]["responseBody"] == "full original error\nstack"
    assert result["failure"]["status"] == 500
    assert len(result["measurements"]) == 1


def test_new_failure_is_not_hidden_by_baseline(controller, monkeypatch):
    measure = controller.measure

    def add_failure(phase, clients):
        measure(phase, clients)
        if not any(t["id"] == "new" for t in controller.client.failed):
            controller.client.failed = [
                *controller.client.failed,
                {"id": "new", "state": "FAILED"},
            ]

    monkeypatch.setattr(controller, "measure", add_failure)
    assert controller.execute() == 1
    result = summary(controller)
    assert result["status"] == "failed"
    assert result["newFailedTasks"] == [{"id": "new", "state": "FAILED"}]


def test_measurement_errors_fail_acceptance(controller, monkeypatch):
    measure = controller.measure

    def failed_request(phase, clients):
        measure(phase, clients)
        controller.results["measurements"][-1]["endpoints"]["list"]["errors"] = 1

    monkeypatch.setattr(controller, "measure", failed_request)
    assert controller.execute() == 1
    assert "HTTP measurement errors" in summary(controller)["failure"]["message"]


def test_final_diagnostic_failure_does_not_replace_original(controller, monkeypatch):
    controller.client.state = "FAILED"
    calls = [0]
    original = controller.failed_tasks

    def fail_final():
        calls[0] += 1
        if calls[0] > 1:
            raise RuntimeError("diagnostics unavailable")
        return original()

    monkeypatch.setattr(controller, "failed_tasks", fail_final)
    assert controller.execute() == 1
    result = summary(controller)
    assert "original failure" in result["failure"]["message"]
    assert result["failedTaskCollectionError"]["message"] == "diagnostics unavailable"


def test_missing_baseline_does_not_label_history_as_new(controller, monkeypatch):
    original = controller.failed_tasks
    calls = [0]

    def fail_baseline():
        calls[0] += 1
        if calls[0] == 1:
            raise HTTPError(
                "http://test", 500, "error", {}, io.BytesIO(b"baseline timeout")
            )
        return original()

    monkeypatch.setattr(controller, "failed_tasks", fail_baseline)
    assert controller.execute() == 1
    result = summary(controller)
    assert result["failure"]["responseBody"] == "baseline timeout"
    assert result["baselineCaptured"] is False
    assert result["newFailedTasks"] == []
    assert result["unclassifiedFailedTasks"][0]["id"] == "historic"
    assert "unverified (baseline unavailable)" in (
        controller.args.output / "report.md"
    ).read_text(encoding="utf-8")


class Response(io.BytesIO):
    def __init__(self, status, payload=b"PDF bytes"):
        super().__init__(payload)
        self.status = status
        self.headers = {"ETag": '"revision"'}


class MeasurementClient(FakeClient):
    def __init__(self, range_status=206, fail_during_load=False):
        super().__init__()
        self.range_status = range_status
        self.fail_during_load = fail_during_load
        self.scan_reads = 0
        self.range_requests = []

    def api(self, path, method="GET", data=None):
        if path.startswith("/api/books/"):
            return {
                "book": {
                    "resources": [
                        {
                            "id": "resource",
                            "format": "PDF",
                            "importStatus": "READY",
                            "assets": [{"id": "asset"}],
                        }
                    ]
                }
            }
        if path.startswith("/api/reader/v5/"):
            assert method == "PUT" and data["schemaVersion"] == 5
            return {}
        if path.startswith("/api/library-import-tasks/"):
            self.scan_reads += 1
            if self.fail_during_load and self.scan_reads >= 3:
                self.state = "FAILED"
        return super().api(path, method, data)

    def request(self, path, method="GET", data=None, headers=None):
        assert path == "/api/assets/asset"
        if method != "HEAD":
            self.range_requests.append(headers)
        return Response(200 if method == "HEAD" else self.range_status)


def test_real_measurement_loop_preserves_range_contract_and_metrics(
    controller, monkeypatch
):
    controller.client = MeasurementClient()
    controller.args.seconds = 0.15
    monkeypatch.setattr(controller, "measure", Benchmark.measure.__get__(controller))
    assert controller.execute() == 0
    result = summary(controller)
    assert len(result["measurements"]) == 5
    assert set(result["measurements"][0]["endpoints"]) == {
        "list",
        "deep_page",
        "detail",
        "search",
        "progress",
        "range",
    }
    assert controller.client.range_requests
    assert all(
        h == {"Range": "bytes=0-65535", "If-Range": '"revision"'}
        for h in controller.client.range_requests
    )
    assert (controller.args.output / "requests.jsonl").stat().st_size > 0
    rows = [
        json.loads(line)
        for line in (controller.args.output / "requests.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    terms = {
        parse_qs(urlsplit(row["path"]).query)["search"][0]
        for row in rows
        if row["endpoint"] == "search"
    }
    assert terms == {"NASPERF", "no-such-NASPERF"}


def test_failed_range_keeps_metrics_and_stops_before_rescan(controller, monkeypatch):
    controller.client = MeasurementClient(range_status=200)
    controller.args.seconds = 0.05
    monkeypatch.setattr(controller, "measure", Benchmark.measure.__get__(controller))
    assert controller.execute() == 1
    result = summary(controller)
    assert result["measurements"][0]["endpoints"]["range"]["errors"] > 0
    assert len(result["measurements"]) == 1
    assert not any(
        method == "POST" and path.endswith("/scan")
        for method, path in controller.client.calls
    )


def test_scan_failure_during_real_load_keeps_partial_phase(controller, monkeypatch):
    controller.client = MeasurementClient(fail_during_load=True)
    controller.args.seconds = 0.05
    monkeypatch.setattr(controller, "measure", Benchmark.measure.__get__(controller))
    assert controller.execute() == 1
    result = summary(controller)
    assert result["finalSnapshot"]["scan"]["state"] == "FAILED"
    assert len(result["measurements"]) == 1
    assert (controller.args.output / "performance-import-active-4.json").exists()
    assert not any(
        method == "POST" and path.endswith("/scan")
        for method, path in controller.client.calls
    )
