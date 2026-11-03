"""Measure an existing NAS import through public APIs; never generate or repair data.

NAS_PERF_EMAIL / NAS_PERF_PASSWORD authenticate an existing test account.
See benchmark_nas_import.md for invocation and the evidence contract.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import math
import os
import subprocess
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from http.client import HTTPResponse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener


class AcceptanceFailure(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(
        self,
        path: str,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> HTTPResponse:
        request = Request(
            self.base_url + path,
            method=method,
            data=None if data is None else json.dumps(data).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        return self.opener.open(request, timeout=90)

    def api(
        self, path: str, method: str = "GET", data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self.request(path, method, data) as response:
            payload = json.load(response)
        if payload.get("ok") is not True:
            raise RuntimeError(payload)
        return payload["data"]


class Benchmark:
    def __init__(self, args: argparse.Namespace, client: Client) -> None:
        self.args = args
        self.client = client
        self.scan_id = args.scan_id
        self.results: dict[str, Any] = {
            "status": "running",
            "phase": "starting",
            "measurements": [],
            "libraryId": args.library_id,
            "scanId": args.scan_id,
            "generatedBooks": args.generated_books,
            "targetBooks": args.target_books,
            "baselineFailedTasks": [],
            "baselineCaptured": False,
            "newFailedTasks": [],
            "limitations": [
                "HTTP measurements do not validate rendering, decoding or playback.",
                "The existing corpus has 12,000 PDFs cloned from a broken-xref template; PDF reading is unverified.",
                "OS disk caches are not cleared; concurrency is closed-loop.",
            ],
        }
        self.lock = threading.Lock()

    def save(self, name: str, value: Any) -> None:
        path = self.args.output / name
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    def append(self, name: str, value: dict[str, Any]) -> None:
        with self.lock, (self.args.output / name).open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps({"time": time.time(), **value}, ensure_ascii=False) + "\n"
            )

    def books_path(self, **parameters: Any) -> str:
        parameters["filters"] = json.dumps(
            {
                "combinator": "ALL",
                "conditions": [
                    {
                        "field": "library",
                        "operator": "equals",
                        "value": self.args.library_id,
                    },
                ],
            }
        )
        return "/api/books?" + urlencode(parameters)

    def failed_tasks(self) -> list[dict[str, Any]]:
        tasks = []
        page = 1
        while True:
            data = self.client.api(
                f"/api/libraries/{self.args.library_id}/import-tasks?state=FAILED&pageSize=100&page={page}"
            )
            tasks.extend(data["tasks"])
            if page >= data["totalPages"]:
                return tasks
            page += 1

    def check_failed_tasks(self) -> None:
        final_failed = self.failed_tasks()
        if not self.results["baselineCaptured"]:
            self.results["unclassifiedFailedTasks"] = final_failed
            return
        baseline = {t["id"]: t for t in self.results["baselineFailedTasks"]}

        def signature(task: dict[str, Any]) -> tuple[Any, ...]:
            return tuple(
                task.get(key)
                for key in ("state", "errorSummary", "startedAt", "finishedAt")
            )

        self.results["newFailedTasks"] = [
            task
            for task in final_failed
            if task["id"] not in baseline
            or signature(task) != signature(baseline[task["id"]])
        ]
        if self.results["newFailedTasks"]:
            raise AcceptanceFailure(
                "New or changed failed tasks remain in the target library"
            )

    def snapshot(self) -> dict[str, Any]:
        # Read the target task first so a failed scan never waits for a queue drain.
        scan = self.client.api(f"/api/library-import-tasks/{self.scan_id}")["task"]
        self.results["finalSnapshot"] = {"scan": scan}
        if scan["libraryId"] != self.args.library_id:
            raise AcceptanceFailure("Scan belongs to another library")
        self.check_scan(scan)
        queue = self.client.api(
            f"/api/libraries/{self.args.library_id}/import-tasks?pageSize=1"
        )
        books = self.client.api(self.books_path(pageSize=1, view="bookshelf"))
        observed = {
            "scan": scan,
            "queue": {k: v for k, v in queue.items() if k != "tasks"},
            "discoveredBooks": books["total"],
        }
        self.results["finalSnapshot"] = observed
        self.save("import-progress.json", observed)
        self.append("timeline.jsonl", observed)
        return observed

    @staticmethod
    def check_scan(scan: dict[str, Any]) -> None:
        if scan["state"] in {"FAILED", "CANCELLED", "CANCELED"}:
            raise AcceptanceFailure(
                f"Scan {scan['id']} {scan['state']}: {scan.get('errorSummary')}"
            )

    def resources(self) -> list[dict[str, Any]]:
        sample: list[dict[str, Any]] = []
        page = 1
        while len(sample) < 30:
            data = self.client.api(
                self.books_path(pageSize=100, view="bookshelf", page=page)
            )
            for book in data["books"]:
                if not book["resourceImportSummary"]["ready"]:
                    continue
                detail = self.client.api("/api/books/" + book["id"])["book"]
                sample.extend(
                    r
                    for r in detail["resources"]
                    if r["importStatus"] == "READY" and r["assets"]
                )
                if len(sample) >= 30:
                    break
            if page >= data["totalPages"]:
                break
            page += 1
        if not sample:
            raise AcceptanceFailure(
                "No READY resources available for HTTP measurements"
            )
        return sample[:30]

    def host_sample(self) -> None:
        observed = {}
        for name in ("meminfo", "diskstats", "loadavg"):
            path = Path("/proc") / name
            if path.exists():
                observed[name] = path.read_text()
        if self.args.container:
            stats = subprocess.run(
                [
                    "sudo",
                    "-n",
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    self.args.container,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
            )
            observed["containerStats"] = json.loads(stats.stdout)
        self.append("resources.jsonl", observed)

    def measure(self, phase: str, clients: int) -> None:
        self.results["phase"] = phase
        self.snapshot()
        initial = self.client.api(self.books_path(pageSize=100, view="bookshelf"))
        ids = [b["id"] for b in initial["books"]]
        if not ids:
            raise AcceptanceFailure("No books available for HTTP measurements")
        resources = self.resources()
        range_headers = {}
        for resource in resources:
            headers = {"Range": "bytes=0-65535"}
            if resource["format"] == "PDF":
                with self.client.request(
                    "/api/assets/" + resource["assets"][0]["id"], "HEAD"
                ) as response:
                    etag = response.headers.get("ETag", "")
                if not etag.startswith('"') or not etag.endswith('"'):
                    raise AcceptanceFailure("PDF HEAD did not return a strong ETag")
                headers["If-Range"] = etag
            range_headers[resource["id"]] = headers
        rows: list[dict[str, Any]] = []
        stop = threading.Event()
        deadline = time.monotonic() + self.args.seconds

        def worker(index: int) -> None:
            n = 0
            while not stop.is_set() and time.monotonic() < deadline:
                endpoint = (
                    "list",
                    "deep_page",
                    "detail",
                    "search",
                    "progress",
                    "range",
                )[n % 6]
                path = self.books_path(pageSize=50, view="bookshelf", page=n % 20 + 1)
                method, body = "GET", None
                resource = resources[(n + index) % len(resources)]
                if endpoint == "deep_page":
                    path = self.books_path(
                        pageSize=50,
                        view="bookshelf",
                        page=max(1, math.ceil(initial["total"] / 50)),
                    )
                elif endpoint == "detail":
                    path = "/api/books/" + ids[(n + index) % len(ids)]
                elif endpoint == "search":
                    path = self.books_path(
                        pageSize=20,
                        view="search",
                        search="NASPERF" if (n // 6) % 2 else "no-such-NASPERF",
                    )
                elif endpoint == "progress":
                    path = "/api/reader/v5/resources/" + resource["id"] + "/progress"
                    method = "PUT"
                    body = {
                        "schemaVersion": 5,
                        "clientId": f"nas-perf-{index}",
                        "mutationId": str(uuid.uuid4()),
                        "capturedAtEpochMillis": int(time.time() * 1000),
                        "position": {
                            "locator": {"source": "nas-perf", "sequence": n},
                            "presentation": {
                                "displayPercent": 10.0,
                                "totalProgression": 0.1,
                                "currentHref": None,
                                "chapter": None,
                                "page": None,
                                "playback": None,
                            },
                        },
                    }
                elif endpoint == "range":
                    path = "/api/assets/" + resource["assets"][0]["id"]
                started = time.perf_counter()
                row: dict[str, Any] = {
                    "path": path,
                    "method": method,
                    "endpoint": endpoint,
                    "phase": phase,
                    "clients": clients,
                    "worker": index,
                    "success": False,
                }
                try:
                    if endpoint == "range":
                        with self.client.request(
                            path, headers=range_headers[resource["id"]]
                        ) as response:
                            payload = response.read(65537)
                            row["status"] = response.status
                            row["success"] = (
                                response.status == 206 and 0 < len(payload) <= 65536
                            )
                    else:
                        self.client.api(path, method, body)
                        row.update(status=200, success=True)
                except Exception as error:  # noqa: BLE001 - record each failed request without losing other samples.
                    row.update(
                        error=exception_record(error),
                        status=getattr(error, "code", None),
                    )
                row["elapsedMs"] = (time.perf_counter() - started) * 1000
                with self.lock:
                    rows.append(row)
                self.append("requests.jsonl", row)
                n += 1

        try:
            with ThreadPoolExecutor(max_workers=clients) as pool:
                futures = [pool.submit(worker, i) for i in range(clients)]
                try:
                    while not all(f.done() for f in futures):
                        self.snapshot()
                        self.host_sample()
                        wait(futures, timeout=self.args.poll_seconds)
                    for future in futures:
                        future.result()
                finally:
                    stop.set()
        finally:
            summary: dict[str, Any] = {
                "phase": phase,
                "clients": clients,
                "endpoints": {},
            }
            for endpoint in sorted({r["endpoint"] for r in rows}):
                selected = [r for r in rows if r["endpoint"] == endpoint]
                latencies = sorted(r["elapsedMs"] for r in selected)
                summary["endpoints"][endpoint] = {
                    "requests": len(selected),
                    "errors": sum(not r["success"] for r in selected),
                    **{
                        f"p{p}Ms": latencies[int((len(latencies) - 1) * p / 100)]
                        for p in (50, 95, 99)
                    },
                    "maxMs": max(latencies),
                }
            self.results["measurements"].append(summary)
            self.save(f"performance-{phase}-{clients}.json", summary)

        if any(row["errors"] for row in summary["endpoints"].values()):
            raise AcceptanceFailure(f"HTTP measurement errors in {phase}")

    def wait_for_import(self) -> None:
        self.results["phase"] = "waiting_for_import"
        while True:
            observed = self.snapshot()
            queue = observed["queue"]
            if (
                observed["scan"]["state"] == "SUCCEEDED"
                and queue["queued"] == 0
                and queue["running"] == 0
            ):
                return
            self.host_sample()
            time.sleep(self.args.poll_seconds)

    def verify_books(self) -> None:
        discovered, successful, page = 0, 0, 1
        seen = set()
        while True:
            data = self.client.api(
                self.books_path(
                    pageSize=100, view="import-status", sort="recent_import", page=page
                )
            )
            for book in data["books"]:
                if book["libraryId"] != self.args.library_id or book["id"] in seen:
                    raise AcceptanceFailure(
                        "Library membership or pagination changed during acceptance"
                    )
                seen.add(book["id"])
                summary = book["resourceImportSummary"]
                successful += int(
                    summary["ready"] > 0
                    and summary["pending"] == 0
                    and summary["failed"] == 0
                    and summary["failedFiles"] == 0
                    and book["metadataState"] == "COMPLETED"
                )
            discovered = data["total"]
            if page >= data["totalPages"]:
                break
            page += 1
        counts = {
            "discoveredBooks": discovered,
            "successfulBooks": successful,
            "enumeratedBooks": len(seen),
        }
        self.results.update(counts)
        if (
            len(seen) != discovered
            or discovered != self.args.target_books
            or successful != self.args.target_books
        ):
            raise AcceptanceFailure(
                f"Incomplete import: {counts}, target={self.args.target_books}"
            )

    def execute(self) -> int:
        self.args.output.mkdir(parents=True, exist_ok=True)
        code = 1
        try:
            self.client.api(
                "/api/auth/login",
                "POST",
                {
                    "email": os.environ["NAS_PERF_EMAIL"],
                    "password": os.environ["NAS_PERF_PASSWORD"],
                },
            )
            self.results["baselineFailedTasks"] = self.failed_tasks()
            self.results["baselineCaptured"] = True
            self.snapshot()
            self.measure("import-active", 4)
            self.wait_for_import()
            self.check_failed_tasks()
            self.verify_books()
            for clients in (1, 4, 8):
                self.measure("import-settled", clients)
            self.check_failed_tasks()
            request = self.client.api(
                f"/api/libraries/{self.args.library_id}/scan", "POST"
            )
            self.scan_id = request["taskId"]
            self.save("rescan-request.json", request)
            self.measure("rescan-active", 4)
            self.wait_for_import()
            self.verify_books()
            errors = sum(
                e["errors"]
                for m in self.results["measurements"]
                for e in m["endpoints"].values()
            )
            if errors:
                raise AcceptanceFailure(f"HTTP measurement errors: {errors}")
            self.results.update(status="completed", phase="completed")
            code = 0
        except (Exception, KeyboardInterrupt) as error:  # noqa: BLE001 - controller boundary persists full failure evidence.
            failure = exception_record(error)
            self.results.update(status="failed", failure=failure)
            self.append("errors.jsonl", failure)
            self.save("failure.json", failure)
        finally:
            try:
                self.check_failed_tasks()
            except Exception as error:  # noqa: BLE001 - retain evidence if the final diagnostic request also fails.
                key = (
                    "acceptanceError"
                    if isinstance(error, AcceptanceFailure)
                    else "failedTaskCollectionError"
                )
                self.results[key] = exception_record(error)
                self.results["status"] = "failed"
                self.append("errors.jsonl", self.results[key])
                if "failure" not in self.results:
                    self.results["failure"] = self.results[key]
                    self.save("failure.json", self.results["failure"])
                code = 1
            self.results["finishedAt"] = time.time()
            self.save("summary.json", self.results)
            self.save(
                "status.json",
                {k: v for k, v in self.results.items() if k != "measurements"},
            )
            self.write_report()
        return code

    def write_report(self) -> None:
        lines = [
            "# NAS 导入性能报告 / NAS import performance report",
            "",
            f"状态 / Status: {self.results['status']}",
            f"阶段 / Phase: {self.results['phase']}",
            f"生成 / Generated: {self.args.generated_books}",
            f"发现 / Discovered: {self.results.get('discoveredBooks', self.results.get('finalSnapshot', {}).get('discoveredBooks', 'unverified'))}",
            f"成功导入 / Successfully imported: {self.results.get('successfulBooks', 'unverified')}",
            "",
            "完整结果与错误 / Full results and errors: summary.json, errors.jsonl, requests.jsonl",
        ]
        if "failure" in self.results:
            failure = self.results["failure"]
            lines.extend(
                ["", f"失败原因 / Failure: {failure['type']}: {failure['message']}", ""]
            )
        lines.extend(
            [
                f"历史失败 / Baseline failures: {len(self.results['baselineFailedTasks'])}",
                f"新增或变化的失败 / New or changed failures: {len(self.results['newFailedTasks']) if self.results['baselineCaptured'] else 'unverified (baseline unavailable)'}",
                "",
                "| Phase | Clients | Endpoint | Requests | Errors | P95 ms | P99 ms |",
                "|---|---:|---|---:|---:|---:|---:|",
            ]
        )
        for measurement in self.results["measurements"]:
            for endpoint, row in measurement["endpoints"].items():
                lines.append(
                    f"| {measurement['phase']} | {measurement['clients']} | {endpoint} | {row['requests']} | {row['errors']} | {row['p95Ms']:.2f} | {row['p99Ms']:.2f} |"
                )
        lines.extend(["", *self.results["limitations"]])
        (self.args.output / "report.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


def exception_record(error: BaseException) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": type(error).__name__,
        "message": str(error),
        "traceback": traceback.format_exc(),
    }
    if isinstance(error, HTTPError):
        record.update(
            status=error.code, responseBody=error.read().decode("utf-8", "replace")
        )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--library-id", required=True)
    parser.add_argument("--scan-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-books", type=int, required=True)
    parser.add_argument("--generated-books", type=int, required=True)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument(
        "--container", help="Optional Docker container for sudo -n docker stats"
    )
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        args.output = args.output / (
            time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        )
    if (
        min(args.target_books, args.generated_books, args.seconds, args.poll_seconds)
        <= 0
    ):
        parser.error("counts and durations must be positive")
    return Benchmark(args, Client(args.base_url)).execute()


if __name__ == "__main__":
    raise SystemExit(main())
