"""Bounded local release-gate performance precheck.

The runner writes only to a unique evidence directory. It imports the repository's
existing smoke lifecycle and calls the real API, worker and scan owners.
Generated files are valid EPUB, PDF and CBZ resources; no database rows are
inserted by this runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from itertools import islice
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

RELEASE_ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT_PARENT = Path(
    os.environ.get(
        "PRECHECK_EVIDENCE_ROOT",
        str(RELEASE_ROOT / "artifacts/releases/1.0/local-load"),
    )
).resolve()
API_ROOT = RELEASE_ROOT / "apps" / "api-python"

import httpx
import psutil

sys.path.insert(0, str(RELEASE_ROOT / "scripts"))
sys.path.insert(0, str(API_ROOT))

from app.core.config import Settings
from app.db.sqlite import create_sqlite_engine
from app.models import (
    LibraryBook,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.library.public import (
    InvalidSourceNodeRelativePathError,
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    is_resource_anchor_within_book_scope,
)
from app.modules.reader.presentation.v5_schemas import (
    ReaderV5ProgressPut,
    ReaderV5ProgressSnapshot,
    ReaderV5ProgressStateResponse,
    ReaderV5ProgressWriteResponse,
)
from python_backend_sample_smoke import (
    create_fixture_library,
    expect_ok,
    free_port,
    sha256_file,
    wait_for_health,
    wait_for_worker,
)
from python_smoke_process import LoggedProcess, start_logged_process
from sqlalchemy import and_, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, aliased

SUPPORTED_TOTAL_FILES = (10_000, 100_000, 300_000)
INITIAL_PERCENT = 20
FORMAT_WEIGHTS = (("epub", 4), ("pdf", 3), ("cbz", 3))
FileSpec = tuple[str, int, str, str, Path]
REQUEST_ENDPOINTS = ("list", "detail", "search", "v5_save")
logger = logging.getLogger(__name__)
RELEASE_THRESHOLDS_MS = {
    "list": 2_000.0,
    "detail": 2_000.0,
    "search": 3_000.0,
    "v5_save": 2_000.0,
}
PRECHECK_LIMITATIONS = (
    "Local precheck only: corpus size and configured windows do not establish the full release LOAD gate.",
    "Generated media remain compact single-file EPUB/PDF/CBZ; representative heavy media and audio are not covered.",
    "Actual Web/Android/iOS media clients, reading, playback interruptions, engine positions and proxy/network paths are not verified.",
    "Long-duration sustained parsing/import activity is not verified: sampled queued/running tasks do not prove continuous parser work.",
    "Serial endpoint clients back off under latency: actual rate and scan coverage must be assessed, not configured rate.",
    "Lists rotate through the first 20 pages; growth requests use the initial resource pool, so newly imported readability is not verified.",
    "CPU samples are system-wide only; per-service CPU, I/O, DB lock waits, cache/swap and runner memory are not measured.",
    "Cold/hot media paths, continuous foreground unavailability, service restart and client reconnect recovery are not verified.",
    "Integrity checks cover manifest-listed single-file originals and this isolated library outside load windows; unrelated directories are not inspected.",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def append_jsonl(path: Path, value: object) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
        stream.write("\n")


@dataclass(frozen=True)
class FileRecord:
    relative_path: str
    format: str
    title: str
    ordinal: int
    size_class: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class CorpusConfig:
    total_files: int = SUPPORTED_TOTAL_FILES[0]

    def __post_init__(self) -> None:
        if (
            type(self.total_files) is not int
            or self.total_files not in SUPPORTED_TOTAL_FILES
        ):
            raise ValueError(f"total files must be one of {SUPPORTED_TOTAL_FILES}")

    @property
    def initial_files(self) -> int:
        return self.total_files * INITIAL_PERCENT // 100

    @property
    def format_counts(self) -> dict[str, int]:
        total_weight = sum(weight for _, weight in FORMAT_WEIGHTS)
        return {
            name: self.total_files * weight // total_weight
            for name, weight in FORMAT_WEIGHTS
        }

    @property
    def initial_format_counts(self) -> dict[str, int]:
        return {
            name: count * INITIAL_PERCENT // 100
            for name, count in self.format_counts.items()
        }

    @property
    def scale_label(self) -> str:
        return f"{self.total_files // 1000}k"

    def evidence(self) -> dict[str, object]:
        return {
            "totalFiles": self.total_files,
            "initialFiles": self.initial_files,
            "initialPercent": INITIAL_PERCENT,
            "formatCounts": self.format_counts,
            "initialFormatCounts": self.initial_format_counts,
        }


def _png_bytes(seed: str, edge: int) -> bytes:
    from PIL import Image

    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    pixels = bytearray()
    for index in range(edge * edge * 3):
        pixels.append(digest[index % len(digest)] ^ (index * 17 & 0xFF))
    image = Image.frombytes("RGB", (edge, edge), bytes(pixels))
    output = BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def _write_epub(path: Path, title: str, ordinal: int, size_class: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    repeat = {"small": 16, "medium": 96, "large": 320}[size_class]
    body = "".join(
        f"<p>{escape(title)} paragraph {line} contains readable test material "
        "for the local release precheck.</p>"
        for line in range(repeat)
    )
    chapter = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
        f"<title>{escape(title)}</title></head><body><h1>{escape(title)}</h1>"
        f"{body}</body></html>"
    )
    identifier = f"urn:uuid:precheck-epub-{ordinal:05d}"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        mimetype.date_time = (1980, 1, 1, 0, 0, 0)
        archive.writestr(mimetype, "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
            'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:identifier>{identifier}</dc:identifier>"
            f"<dc:title>{escape(title)}</dc:title>"
            f"<dc:creator>Local precheck {ordinal:05d}</dc:creator>"
            '</metadata><manifest><item id="chapter" href="chapter.xhtml" '
            'media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="chapter"/></spine></package>',
        )
        archive.writestr("OEBPS/chapter.xhtml", chapter)


def _write_pdf(
    path: Path,
    title: str,
    ordinal: int,
    size_class: str,
    seed_pdf: Path,
) -> None:
    from pypdf import PdfReader, PdfWriter

    path.parent.mkdir(parents=True, exist_ok=True)
    page_count = {"small": 1, "medium": 4, "large": 12}[size_class]
    reader = PdfReader(str(seed_pdf), strict=False)
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    while len(writer.pages) < page_count:
        writer.add_blank_page(width=612, height=792)
    writer.add_metadata(
        {
            "/Title": title,
            "/Author": f"Local precheck {ordinal:05d}",
            "/Subject": "Valid generated release precheck PDF",
        }
    )
    with path.open("wb") as stream:
        writer.write(stream)


def _write_cbz(path: Path, title: str, ordinal: int, size_class: str) -> None:
    edge = {"small": 64, "medium": 96, "large": 128}[size_class]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for page_index in (1, 2):
            archive.writestr(
                f"page-{page_index:03d}.png",
                _png_bytes(f"{title}:{page_index}", edge),
            )
        archive.writestr(
            "meta/precheck.txt",
            f"{title}\nGenerated valid CBZ sample {ordinal:05d}\n",
        )


def _file_specs(corpus: CorpusConfig) -> Iterator[FileSpec]:
    seed_pdf = RELEASE_ROOT / "test-data" / "library" / "pdf" / "reading-notes.pdf"
    initial_counts = corpus.initial_format_counts
    total_counts = corpus.format_counts
    # Keep the initial mixed library as a prefix; generate each specification once.
    for lower_counts, upper_counts in (
        (dict.fromkeys(total_counts, 0), initial_counts),
        (initial_counts, total_counts),
    ):
        for format_name, upper in upper_counts.items():
            for ordinal in range(lower_counts[format_name] + 1, upper + 1):
                size_class = ("small", "medium", "large")[(ordinal - 1) % 3]
                base = {"epub": "reflowable", "pdf": "documents", "cbz": "comics"}[
                    format_name
                ]
                shard = (ordinal - 1) // 100
                relative = (
                    Path(base)
                    / f"shard-{shard:02d}"
                    / f"precheck-{format_name}-{ordinal:05d}.{format_name}"
                )
                yield format_name, ordinal, size_class, relative.as_posix(), seed_pdf


def _write_one_spec(
    root: Path,
    spec: FileSpec,
) -> FileRecord:
    format_name, ordinal, size_class, relative, seed_pdf = spec
    title = f"Precheck {format_name.upper()} {ordinal:05d}"
    path = root / Path(relative)
    if format_name == "epub":
        _write_epub(path, title, ordinal, size_class)
    elif format_name == "pdf":
        _write_pdf(path, title, ordinal, size_class, seed_pdf)
    else:
        _write_cbz(path, title, ordinal, size_class)
    digest = sha256_file(path)
    return FileRecord(
        relative_path=relative,
        format=format_name,
        title=title,
        ordinal=ordinal,
        size_class=size_class,
        size_bytes=path.stat().st_size,
        sha256=digest,
    )


def _validate_file(record: FileRecord, root: Path) -> None:
    path = root / Path(record.relative_path)
    if path.stat().st_size != record.size_bytes:
        raise RuntimeError(f"generated file changed during validation: {path}")
    if sha256_file(path) != record.sha256:
        raise RuntimeError(f"generated file hash changed during validation: {path}")
    if record.format in {"epub", "cbz"}:
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise RuntimeError(f"invalid ZIP member in generated file: {path}")
        if record.format == "epub":
            with zipfile.ZipFile(path) as archive:
                if not {"mimetype", "META-INF/container.xml"}.issubset(
                    set(archive.namelist())
                ):
                    raise RuntimeError(f"invalid EPUB structure: {path}")
    else:
        from pypdf import PdfReader

        if len(PdfReader(str(path), strict=False).pages) < 1:
            raise RuntimeError(f"invalid PDF page count: {path}")


def generate_dataset(
    root: Path,
    limit: int,
    *,
    corpus: CorpusConfig,
    log_path: Path,
    start_index: int = 0,
) -> list[FileRecord]:
    if not 0 <= start_index <= limit <= corpus.total_files:
        raise ValueError("dataset slice is outside the configured corpus")
    records: list[FileRecord] = []
    specs = islice(_file_specs(corpus), start_index, limit)
    selected_count = limit - start_index
    with log_path.open("a", encoding="utf-8") as log:
        for index, spec in enumerate(specs, start=1):
            record = _write_one_spec(root, spec)
            _validate_file(record, root)
            records.append(record)
            if index == 1 or index % 250 == 0 or index == selected_count:
                message = f"generated_valid_files={index}/{selected_count}"
                print(message, flush=True)
                log.write(f"{utc_now()} {message}\n")
                log.flush()
    return records


def _validate_dataset_records(
    records: list[FileRecord], expected_counts: dict[str, int]
) -> None:
    expected_total = sum(expected_counts.values())
    if len(records) != expected_total:
        raise RuntimeError(
            f"corpus must contain {expected_total} records, found {len(records)}"
        )
    if Counter(record.format for record in records) != expected_counts:
        raise RuntimeError("corpus format distribution does not match configuration")
    paths: set[Path] = set()
    for record in records:
        # Reuse the public path contract; Path equality also catches case aliases
        # on the Windows filesystem used by this local runner.
        try:
            SourceNodeRelativePath(record.relative_path)
        except InvalidSourceNodeRelativePathError as error:
            raise ValueError("corpus relative path is invalid") from error
        path = Path(record.relative_path)
        if path in paths:
            raise RuntimeError("corpus relative paths must be unique")
        paths.add(path)


def _load_prepared_corpus(
    prepared_root: Path, corpus: CorpusConfig
) -> tuple[Path, list[FileRecord]]:
    requested_root = prepared_root.resolve()
    manifest_candidates = (
        requested_root / "dataset-manifest.json",
        requested_root.parent / "dataset-manifest.json",
    )
    manifest_path = next(
        (candidate for candidate in manifest_candidates if candidate.is_file()),
        None,
    )
    if manifest_path is None:
        raise RuntimeError(
            f"prepared corpus manifest is missing under {requested_root}"
        )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "corpus-ready":
        raise RuntimeError(f"prepared corpus is not corpus-ready: {manifest_path}")
    root_value = payload.get("root")
    records_value = payload.get("records")
    validation_value = payload.get("validation")
    if not isinstance(root_value, str) or not isinstance(records_value, list):
        raise TypeError(f"prepared corpus manifest is malformed: {manifest_path}")
    if not isinstance(validation_value, dict):
        raise TypeError(f"prepared corpus validation is missing: {manifest_path}")
    if validation_value.get("allFilesWrittenAndReopened") is not True:
        raise RuntimeError(f"prepared corpus was not fully reopened: {manifest_path}")
    if validation_value.get("databaseRowsWritten") is not False:
        raise RuntimeError(f"prepared corpus has database-backed data: {manifest_path}")

    source_root = Path(root_value).resolve()
    if not source_root.is_dir():
        if requested_root.name == "library" and requested_root.is_dir():
            source_root = requested_root
        else:
            raise RuntimeError(f"prepared corpus files are missing: {source_root}")

    records: list[FileRecord] = []
    for item in records_value:
        if not isinstance(item, dict):
            raise TypeError(f"prepared corpus record is malformed: {manifest_path}")
        try:
            records.append(
                FileRecord(
                    relative_path=str(item["relative_path"]),
                    format=str(item["format"]),
                    title=str(item["title"]),
                    ordinal=int(item["ordinal"]),
                    size_class=str(item["size_class"]),
                    size_bytes=int(item["size_bytes"]),
                    sha256=str(item["sha256"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"prepared corpus record is malformed: {manifest_path}"
            ) from exc

    _validate_dataset_records(records, corpus.format_counts)
    _validate_dataset_records(
        records[: corpus.initial_files], corpus.initial_format_counts
    )
    for key, expected in corpus.evidence().items():
        if key in payload and payload[key] != expected:
            raise RuntimeError(f"prepared corpus configuration mismatch: {key}")
    if dataset_summary(records) != payload.get("summary"):
        raise RuntimeError(
            f"prepared corpus summary does not match records: {manifest_path}"
        )
    return source_root, records


def stage_dataset(
    source_root: Path,
    destination_root: Path,
    records: list[FileRecord],
    *,
    start_index: int,
    end_index: int,
    log_path: Path,
) -> list[FileRecord]:
    selected = records[start_index:end_index]
    staged: list[FileRecord] = []
    with log_path.open("a", encoding="utf-8") as log:
        for index, record in enumerate(selected, start=1):
            source = (source_root / record.relative_path).resolve()
            destination = (destination_root / record.relative_path).resolve()
            if not source.is_relative_to(
                source_root.resolve()
            ) or not destination.is_relative_to(destination_root.resolve()):
                raise ValueError("corpus path escapes its configured root")
            if not source.is_file():
                raise RuntimeError(f"prepared corpus file is missing: {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if destination.stat().st_size != record.size_bytes:
                raise RuntimeError(f"staged file size changed: {destination}")
            if sha256_file(destination) != record.sha256:
                raise RuntimeError(f"staged file hash changed: {destination}")
            staged.append(record)
            if index == 1 or index % 250 == 0 or index == len(selected):
                message = f"staged_valid_files={index}/{len(selected)}"
                print(message, flush=True)
                log.write(f"{utc_now()} {message}\n")
                log.flush()
    return staged


def _verify_source_hashes(
    root: Path, records: list[FileRecord], report_path: Path
) -> None:
    """Read only manifest-listed originals, never enumerate the library tree."""
    owned_root = root.resolve()
    failures: list[dict[str, object]] = []
    verified = 0
    for record in records:
        observation: dict[str, object] = {"relativePath": record.relative_path}
        try:
            relative = Path(record.relative_path)
            path = (owned_root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(owned_root):
                raise ValueError("corpus path escapes its configured root")
            if not path.is_file():
                raise FileNotFoundError("corpus file is missing")
            size = path.stat().st_size
            digest = sha256_file(path)
            if size == record.size_bytes and digest == record.sha256:
                verified += 1
                continue
            observation.update(
                expectedSizeBytes=record.size_bytes,
                actualSizeBytes=size,
                expectedSha256=record.sha256,
                actualSha256=digest,
            )
        except (OSError, ValueError, RuntimeError) as error:
            # Retain failed observations without exposing a resolved private path.
            observation["errorType"] = type(error).__name__
        failures.append(observation)
    passed = (
        bool(records)
        and len({record.relative_path for record in records}) == len(records)
        and not failures
    )
    write_json(
        report_path,
        {
            "capturedAt": utc_now(),
            "status": "verified" if passed else "failed",
            "expectedFiles": len(records),
            "verifiedFiles": verified,
            "failures": failures,
        },
    )
    if not passed:
        raise RuntimeError(f"source hash integrity failed; see {report_path}")


def dataset_summary(records: list[FileRecord]) -> dict[str, object]:
    by_format: dict[str, list[FileRecord]] = defaultdict(list)
    for record in records:
        by_format[record.format].append(record)
    distribution: dict[str, object] = {}
    for format_name, values in sorted(by_format.items()):
        sizes = sorted(record.size_bytes for record in values)
        distribution[format_name] = {
            "files": len(values),
            "percent": round(len(values) * 100 / max(len(records), 1), 2),
            "bytes": sum(sizes),
            "sizeBytes": {
                "min": sizes[0],
                "p50": sizes[len(sizes) // 2],
                "p95": sizes[max(0, math.ceil(len(sizes) * 0.95) - 1)],
                "max": sizes[-1],
            },
            "sizeClasses": dict(Counter(record.size_class for record in values)),
            "uniqueHashes": len({record.sha256 for record in values}),
        }
    return {
        "files": len(records),
        "bytes": sum(record.size_bytes for record in records),
        "uniqueHashes": len({record.sha256 for record in records}),
        "formats": distribution,
        "relativePathCount": len({record.relative_path for record in records}),
    }


def _machine_snapshot(root: Path) -> dict[str, object]:
    usage = shutil.disk_usage(root.anchor or "D:\\")
    snapshot: dict[str, object] = {
        "capturedAt": utc_now(),
        "os": platform.platform(),
        "python": sys.version,
        "pythonExecutable": str(sys.executable),
        "cpuCountLogical": os.cpu_count(),
        "processor": platform.processor(),
        "disk": {
            "root": root.anchor or "D:\\",
            "totalBytes": usage.total,
            "freeBytes": usage.free,
            "usedBytes": usage.used,
        },
    }
    command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "$os = Get-CimInstance Win32_OperatingSystem; "
        "$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1; "
        "[pscustomobject]@{"
        "osCaption=$os.Caption; osVersion=$os.Version; "
        "cpuName=$cpu.Name; logicalProcessors=$cpu.NumberOfLogicalProcessors; "
        "physicalMemoryBytes=$os.TotalVisibleMemorySize * 1024; "
        "availableMemoryBytes=$os.FreePhysicalMemory * 1024"
        "} | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        snapshot["windows"] = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        snapshot["windowsError"] = f"{type(exc).__name__}: {exc}"
    return snapshot


class PhaseState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.phase = "startup"
        self.scan_active = False
        self._active_start: float | None = None
        self._intervals: list[tuple[float, float]] = []

    def set(self, phase: str, *, scan_active: bool) -> None:
        with self._lock:
            now = time.perf_counter()
            if scan_active and not self.scan_active:
                self._active_start = now
            elif self.scan_active and not scan_active:
                if self._active_start is not None:
                    self._intervals.append((self._active_start, now))
                self._active_start = None
            self.phase = phase
            self.scan_active = scan_active

    def active_seconds(self, start: float, end: float) -> float:
        with self._lock:
            intervals = list(self._intervals)
            if self._active_start is not None:
                intervals.append((self._active_start, end))
            return sum(
                max(0.0, min(end, right) - max(start, left))
                for left, right in intervals
            )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {"phase": self.phase, "scanActive": self.scan_active}


class ResourceSampler:
    def __init__(
        self,
        path: Path,
        *,
        api: LoggedProcess,
        worker: LoggedProcess,
        state_provider: Callable[[], dict[str, object]],
        root: Path,
        abort_event: threading.Event,
    ) -> None:
        self.path = path
        self.api = api
        self.worker = worker
        self.state_provider = state_provider
        self.root = root
        self.abort_event = abort_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.abort_reason: str | None = None

    @staticmethod
    def _rss(pid: int) -> tuple[int, list[int]]:
        parent = psutil.Process(pid)
        processes = [parent, *parent.children(recursive=True)]
        measured: list[int] = []
        rss = 0
        for process in processes:
            try:
                rss += process.memory_info().rss
                measured.append(process.pid)
            except psutil.NoSuchProcess:
                if process.pid == pid:
                    raise
        return rss, measured

    def _cpu_percent(self) -> float:
        return psutil.cpu_percent(interval=None)

    @staticmethod
    def _available_memory() -> int:
        return psutil.virtual_memory().available

    def _sample(self) -> None:
        api_rss, api_pids = self._rss(self.api.process.pid)
        worker_rss, worker_pids = self._rss(self.worker.process.pid)
        combined = (api_rss or 0) + (worker_rss or 0)
        available = self._available_memory()
        state = self.state_provider()
        usage = shutil.disk_usage(self.root.anchor or "D:\\")
        append_jsonl(
            self.path,
            {
                "capturedAt": utc_now(),
                "epochMillis": int(time.time() * 1000),
                "phase": state.get("phase"),
                "scanActive": state.get("scanActive"),
                "apiPid": self.api.process.pid,
                "apiProcessTreePids": api_pids,
                "workerProcessTreePids": worker_pids,
                "workerPid": self.worker.process.pid,
                "apiRssBytes": api_rss,
                "workerRssBytes": worker_rss,
                "combinedRssBytes": combined,
                "availableMemoryBytes": available,
                "cpuTotalPercent": self._cpu_percent(),
                "diskFreeBytes": usage.free,
            },
        )
        if combined >= 12 * 1024**3:
            self.abort_reason = "isolated API+worker RSS reached hard 12 GiB guardrail"
            self.abort_event.set()
        if available is not None and available < 768 * 1024**2:
            self.abort_reason = "available physical memory fell below 768 MiB guardrail"
            self.abort_event.set()
        if usage.free < 20 * 1024**3:
            self.abort_reason = "D: free space fell below 20 GiB guardrail"
            self.abort_event.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample()
            except (psutil.Error, OSError) as error:
                self.abort_reason = (
                    f"resource observation failed: {type(error).__name__}"
                )
                self.abort_event.set()
                append_jsonl(
                    self.path,
                    {"capturedAt": utc_now(), "observerError": self.abort_reason},
                )
                return
            self._stop.wait(5)

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="resource-sampler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)


def _db_snapshot(engine: Engine, library_id: str) -> dict[str, object]:
    with Session(engine) as db:
        task_rows = db.execute(
            select(
                LibraryImportTask.kind,
                LibraryImportTask.state,
                func.count(LibraryImportTask.id),
            )
            .where(LibraryImportTask.library_id == library_id)
            .group_by(LibraryImportTask.kind, LibraryImportTask.state)
        ).all()
        tasks = {f"{kind}:{state}": int(count) for kind, state, count in task_rows}
        failed = list(
            db.scalars(
                select(LibraryImportTask.error_summary)
                .where(
                    LibraryImportTask.library_id == library_id,
                    LibraryImportTask.state == "FAILED",
                )
                .limit(5)
            ).all()
        )
        counts = {
            "sourceNodes": int(
                db.scalar(
                    select(func.count(LibrarySourceNode.id)).where(
                        LibrarySourceNode.library_id == library_id
                    )
                )
                or 0
            ),
            "books": int(
                db.scalar(
                    select(func.count(LibraryBook.id)).where(
                        LibraryBook.library_id == library_id
                    )
                )
                or 0
            ),
            "resources": int(
                db.scalar(
                    select(func.count(LibraryReadableResource.id)).where(
                        LibraryReadableResource.library_id == library_id,
                        LibraryReadableResource.import_state == "READY",
                    )
                )
                or 0
            ),
            "assets": int(
                db.scalar(
                    select(func.count(LibraryResourceAsset.id)).where(
                        LibraryResourceAsset.library_id == library_id,
                        LibraryResourceAsset.import_state == "READY",
                    )
                )
                or 0
            ),
        }
        queued = sum(count for key, count in tasks.items() if key.endswith(":QUEUED"))
        running = sum(count for key, count in tasks.items() if key.endswith(":RUNNING"))
        completed = sum(
            count for key, count in tasks.items() if key.endswith(":SUCCEEDED")
        )
        failed_count = sum(
            count for key, count in tasks.items() if key.endswith(":FAILED")
        )
        return {
            **counts,
            "tasks": tasks,
            "queued": queued,
            "running": running,
            "completed": completed,
            "failed": failed_count,
            "failedExamples": [item for item in failed if item],
            "scanActive": queued > 0 or running > 0,
        }


def _wait_for_scan(
    engine: Engine,
    library_id: str,
    task_id: str,
    expected_resources: int,
    *,
    phase: str,
    state: PhaseState,
    progress_path: Path,
    abort_event: threading.Event,
    timeout_seconds: float,
) -> dict[str, object]:
    started = time.monotonic()
    last: dict[str, object] = {}
    settled_since: float | None = None
    while time.monotonic() - started < timeout_seconds:
        if abort_event.is_set():
            raise RuntimeError("resource guardrail requested an abort")
        last = _db_snapshot(engine, library_id)
        with Session(engine) as db:
            task = db.get(LibraryImportTask, task_id)
            task_state = task.state if task is not None else None
            task_error = task.error_summary if task is not None else None
        append_jsonl(
            progress_path,
            {
                "capturedAt": utc_now(),
                "phase": phase,
                "taskId": task_id,
                "taskState": task_state,
                "taskError": task_error,
                **last,
            },
        )
        if task_state == "FAILED" or last["failed"]:
            raise RuntimeError(
                f"scan/import failed in {phase}: {task_error or last['failedExamples']}"
            )
        if (
            task_state == "SUCCEEDED"
            and last["queued"] == 0
            and last["running"] == 0
            and int(last["resources"]) >= expected_resources
            and int(last["assets"]) >= expected_resources
        ):
            state.set(phase, scan_active=False)
            if settled_since is None:
                settled_since = time.monotonic()
            # Observe a full coordinator refresh before accepting quiescence.
            if time.monotonic() - settled_since < 6:
                time.sleep(1)
                continue
            return {
                "phase": phase,
                "taskId": task_id,
                "durationSeconds": round(time.monotonic() - started, 3),
                "final": last,
            }
        settled_since = None
        state.set(phase, scan_active=bool(last["scanActive"]))
        time.sleep(1)
    raise TimeoutError(f"scan did not settle in {timeout_seconds}s: {last}")


def _trigger_scan(client: httpx.Client, library_id: str) -> str:
    payload = expect_ok(client.post(f"/api/libraries/{library_id}/scan"))
    task_id = payload.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError(f"scan endpoint did not return taskId: {payload}")
    return task_id


def _resource_pool(engine: Engine, library_id: str) -> dict[str, object]:
    with Session(engine) as db:
        rows = db.execute(
            select(
                LibraryBook.id,
                LibraryReadableResource.id,
                LibraryReadableResource.format,
            )
            .join(
                LibraryReadableResource,
                and_(
                    LibraryReadableResource.book_id == LibraryBook.id,
                    LibraryReadableResource.library_id == LibraryBook.library_id,
                ),
            )
            .where(
                LibraryBook.library_id == library_id,
                LibraryReadableResource.import_state == "READY",
            )
            .order_by(LibraryBook.id.asc())
        ).all()
    return {
        "bookIds": [str(row[0]) for row in rows],
        "resourceIds": [str(row[1]) for row in rows],
        "formats": [str(row[2]).lower() for row in rows],
    }


def _v5_sanity(
    client: httpx.Client,
    pool: dict[str, object],
    *,
    output_path: Path,
) -> None:
    by_format: dict[str, str] = {}
    for resource_id, format_name in zip(
        pool["resourceIds"], pool["formats"], strict=True
    ):
        if format_name not in by_format:
            by_format[format_name] = str(resource_id)
    results: dict[str, object] = {}
    for format_name, resource_id in sorted(by_format.items()):
        response = client.get(
            f"/api/reader/v5/resources/{quote(resource_id, safe='')}/bootstrap"
        )
        data = expect_ok(response)
        if data.get("schemaVersion") != 5:
            raise RuntimeError(f"Reader v5 bootstrap schema mismatch: {data}")
        result: dict[str, object] = {
            "resourceId": resource_id,
            "readerType": data.get("readerType"),
            "sourceFormat": data.get("sourceFormat"),
            "schemaVersion": data.get("schemaVersion"),
        }
        publication = data.get("publication")
        if format_name in {"cbz", "zip", "cbr", "rar"} and isinstance(
            publication, dict
        ):
            manifest_url = publication.get("manifestUrl")
            if not isinstance(manifest_url, str):
                raise RuntimeError(f"comic v5 manifest URL missing: {data}")
            manifest_response = client.get(manifest_url)
            if manifest_response.status_code != 200:
                raise RuntimeError(
                    f"comic v5 manifest failed: {manifest_response.status_code}"
                )
            manifest = manifest_response.json()
            result["manifestSchemaVersion"] = manifest.get("data", {}).get(
                "schemaVersion"
            )
            result["manifestPageCount"] = manifest.get("data", {}).get("pageCount")
        results[format_name] = result
    write_json(output_path, {"capturedAt": utc_now(), "formats": results})


def _validated_acknowledgement(
    response: httpx.Response, payload: dict[str, object]
) -> ReaderV5ProgressSnapshot:
    response.raise_for_status()
    request = ReaderV5ProgressPut.model_validate(payload)
    acknowledgement = ReaderV5ProgressWriteResponse.model_validate(response.json()).data
    snapshot = acknowledgement.current_snapshot
    if (
        acknowledgement.accepted_mutation_id != request.mutation_id
        or acknowledgement.accepted_revision != snapshot.revision
        or snapshot.mutation_id != request.mutation_id
        or snapshot.client_id != request.client_id
        or snapshot.captured_at_epoch_millis != request.captured_at_epoch_millis
        or snapshot.position != request.position
    ):
        raise ValueError("acknowledged progress does not match the submitted position")
    return snapshot


def _verify_progress(
    client: httpx.Client,
    acknowledged: dict[str, ReaderV5ProgressSnapshot],
    abort_event: threading.Event,
) -> dict[str, int]:
    for resource_id, expected in acknowledged.items():
        if abort_event.is_set():
            raise RuntimeError("progress verification aborted")
        response = client.get(
            f"/api/reader/v5/resources/{quote(resource_id, safe='')}/progress"
        )
        response.raise_for_status()
        actual = ReaderV5ProgressStateResponse.model_validate(
            response.json()
        ).data.progress_snapshot
        if actual != expected:
            raise RuntimeError("acknowledged progress is missing, changed or replaced")
    return {"resourcesVerified": len(acknowledged), "lostAcknowledgedWrites": 0}


class LoadDriver:
    def __init__(
        self,
        *,
        base_url: str,
        cookies: dict[str, str],
        pool: dict[str, object],
        phase: str,
        state: PhaseState,
        output_path: Path,
        abort_event: threading.Event,
        duration_seconds: float,
        requests_per_second: float,
    ) -> None:
        self.base_url = base_url
        self.cookies = cookies
        self.pool = pool
        self.phase = phase
        self.state = state
        self.output_path = output_path
        self.abort_event = abort_event
        self.duration_seconds = duration_seconds
        self.requests_per_second = requests_per_second
        self._write_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self.acknowledged: dict[str, ReaderV5ProgressSnapshot] = {}
        self.windows: dict[str, tuple[float, float]] = {}

    def _append(self, record: dict[str, object]) -> None:
        with self._write_lock:
            append_jsonl(self.output_path, record)

    def _request(
        self, client: httpx.Client, endpoint: str, index: int
    ) -> dict[str, object]:
        book_ids = self.pool["bookIds"]
        resource_ids = self.pool["resourceIds"]
        if not book_ids or not resource_ids:
            raise RuntimeError("load pool is empty")
        start = time.perf_counter()
        status: int | None = None
        success = False
        error_code: str | None = None
        error_type: str | None = None
        try:
            if endpoint == "list":
                response = client.get(
                    "/api/books",
                    params={
                        "page": (index % 20) + 1,
                        "pageSize": 50,
                        "visibility": "active",
                        "sort": "recent_read",
                        "view": "bookshelf",
                    },
                )
            elif endpoint == "detail":
                book_id = book_ids[index % len(book_ids)]
                response = client.get(f"/api/books/{quote(book_id, safe='')}")
            elif endpoint == "search":
                keyword = "Precheck" if index % 5 else f"no-such-precheck-{index:08d}"
                response = client.get(
                    "/api/books",
                    params={
                        "pageSize": 5,
                        "visibility": "active",
                        "sort": "recent_read",
                        "view": "search",
                        "search": keyword,
                    },
                )
            else:
                resource_id = resource_ids[index % len(resource_ids)]
                payload = {
                    "schemaVersion": 5,
                    "clientId": "local-perf-precheck",
                    "mutationId": str(uuid.uuid4()),
                    "capturedAtEpochMillis": int(time.time() * 1000),
                    "position": {
                        "locator": {
                            "source": "local-perf-precheck",
                            "sequence": index,
                        },
                        "presentation": {
                            "displayPercent": float((index % 100) + 1),
                            "totalProgression": float((index % 100) + 1) / 100,
                            "currentHref": None,
                            "chapter": None,
                            "page": None,
                            "playback": None,
                        },
                    },
                }
                response = client.put(
                    f"/api/reader/v5/resources/{quote(resource_id, safe='')}/progress",
                    json=payload,
                )
            status = response.status_code
            body = response.json()
            success = (
                response.status_code == 200
                and isinstance(body, dict)
                and body.get("ok") is True
            )
            if success and endpoint == "v5_save":
                success = False
                self.acknowledged[resource_id] = _validated_acknowledgement(
                    response, payload
                )
                success = True
            if not success and isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict) and isinstance(error.get("code"), str):
                    error_code = error["code"]
        except (httpx.HTTPError, ValueError, OSError) as exc:
            error_type = type(exc).__name__
        end = time.perf_counter()
        elapsed = (end - start) * 1000
        return {
            "capturedAt": utc_now(),
            "epochMillis": int(time.time() * 1000),
            "phase": self.phase,
            "endpoint": endpoint,
            "sequence": index,
            "status": status,
            "success": success,
            "errorCode": error_code,
            "errorType": error_type,
            "elapsedMs": round(elapsed, 3),
            "startedMonotonic": start,
            "endedMonotonic": end,
            "scanActive": self.state.active_seconds(start, end) > 0,
        }

    def _run_endpoint(self, endpoint: str) -> None:
        with httpx.Client(
            base_url=self.base_url,
            cookies=self.cookies,
            timeout=10,
            follow_redirects=False,
        ) as client:
            interval = 1.0 / self.requests_per_second
            started = time.perf_counter()
            deadline = time.monotonic() + self.duration_seconds
            next_at = time.monotonic()
            sequence = 0
            while time.monotonic() < deadline and not self.abort_event.is_set():
                if time.monotonic() < next_at:
                    time.sleep(min(0.02, next_at - time.monotonic()))
                    continue
                try:
                    self._append(self._request(client, endpoint, sequence))
                except Exception as exc:
                    logger.exception("load_driver.failed")
                    self.abort_event.set()
                    self._append(
                        {
                            "capturedAt": utc_now(),
                            "epochMillis": int(time.time() * 1000),
                            "phase": self.phase,
                            "endpoint": endpoint,
                            "sequence": sequence,
                            "status": None,
                            "success": False,
                            "errorType": type(exc).__name__,
                            "errorCode": "LOAD_DRIVER_FAILURE",
                            "elapsedMs": None,
                            "scanActive": self.state.snapshot()["scanActive"],
                        }
                    )
                sequence += 1
                next_at = max(next_at + interval, time.monotonic())
            self.windows[endpoint] = (started, time.perf_counter())

    def run(self) -> None:
        for endpoint in REQUEST_ENDPOINTS:
            thread = threading.Thread(
                target=self._run_endpoint,
                args=(endpoint,),
                name=f"load-{endpoint}",
            )
            self._threads.append(thread)
            thread.start()

    def join(self) -> None:
        deadline = time.monotonic() + self.duration_seconds + 15
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self._threads):
            self.abort_event.set()
            raise TimeoutError(
                "load threads exceeded their window; supervisor will terminate the owned process tree"
            )
        if set(self.windows) != set(REQUEST_ENDPOINTS):
            raise RuntimeError(
                "one or more endpoint load threads failed before completing"
            )

    def verify_acknowledged(self, client: httpx.Client) -> dict[str, int]:
        """Read back each latest acknowledged write after load has stopped."""
        return _verify_progress(client, self.acknowledged, self.abort_event)


def _run_load_phase(
    *,
    client: httpx.Client,
    engine: Engine,
    library_id: str,
    task_expected_resources: int,
    phase: str,
    pool: dict[str, object],
    state: PhaseState,
    requests_path: Path,
    progress_path: Path,
    abort_event: threading.Event,
    duration_seconds: float,
    requests_per_second: float,
    scan: bool,
    scan_timeout_seconds: float,
) -> dict[str, object]:
    state.set(phase, scan_active=False)
    phase_started = time.perf_counter()
    driver = LoadDriver(
        base_url=str(client.base_url),
        cookies=dict(client.cookies),
        pool=pool,
        phase=phase,
        state=state,
        output_path=requests_path,
        abort_event=abort_event,
        duration_seconds=duration_seconds,
        requests_per_second=requests_per_second,
    )
    driver.run()
    scan_result: dict[str, object] | None = None
    progress_integrity: dict[str, object] = {"status": "not_verified"}
    failure: Exception | None = None
    load_finished = phase_started
    try:
        if scan:
            # Include the queue-request boundary, before the first polling result.
            state.set(phase, scan_active=True)
            task_id = _trigger_scan(client, library_id)
            scan_result = _wait_for_scan(
                engine,
                library_id,
                task_id,
                task_expected_resources,
                phase=phase,
                state=state,
                progress_path=progress_path,
                abort_event=abort_event,
                timeout_seconds=scan_timeout_seconds,
            )
        while any(thread.is_alive() for thread in driver._threads):
            if abort_event.is_set():
                raise RuntimeError("load phase aborted")
            if time.perf_counter() - phase_started > duration_seconds + 15:
                abort_event.set()
                raise TimeoutError(
                    "load phase exceeded bounded request completion time"
                )
            observation = _db_snapshot(engine, library_id)
            append_jsonl(
                progress_path, {"capturedAt": utc_now(), "phase": phase, **observation}
            )
            state.set(phase, scan_active=bool(observation["scanActive"]))
            if not scan and observation["scanActive"]:
                abort_event.set()
                raise RuntimeError("idle baseline contaminated by an automatic scan")
            time.sleep(0.5)
        driver.join()
        load_finished = time.perf_counter()
        progress_integrity = driver.verify_acknowledged(client)
    except Exception as error:
        logger.exception("load_phase.failed", extra={"phase": phase})
        failure = error
        if load_finished == phase_started:
            load_finished = time.perf_counter()
    finally:
        state.set(phase, scan_active=False)
        for thread in driver._threads:
            if thread.is_alive():
                abort_event.set()
                thread.join(timeout=10)
    result = {
        "phase": phase,
        "status": "failed" if failure is not None else "completed",
        "failureType": type(failure).__name__ if failure is not None else None,
        "durationSeconds": duration_seconds,
        "actualPhaseSeconds": time.perf_counter() - phase_started,
        "scanActiveSeconds": state.active_seconds(phase_started, load_finished),
        "scanCoverageByEndpoint": {
            endpoint: {
                "loadSeconds": end - start,
                "coveredScanSeconds": state.active_seconds(start, end),
                "scanCoverageRatio": (
                    state.active_seconds(start, end)
                    / state.active_seconds(phase_started, load_finished)
                    if state.active_seconds(phase_started, load_finished) > 0
                    else None
                ),
            }
            for endpoint, (start, end) in driver.windows.items()
        },
        "coverageLimit": "queue observations every 0.5-1s; queue activity is not proof of sustained parsing; uncovered scan time is not measured",
        "requestRatePerEndpoint": requests_per_second,
        "scan": scan_result,
        "progressIntegrity": progress_integrity,
    }
    append_jsonl(progress_path.parent / "phases.jsonl", result)
    if failure is not None and not (
        isinstance(failure, httpx.TimeoutException)
        and not abort_event.is_set()
        and set(driver.windows) == set(REQUEST_ENDPOINTS)
    ):
        raise failure
    return result


def _identity_snapshot(engine: Engine, library_id: str) -> dict[str, object]:
    with Session(engine) as db:
        paths = list(
            db.scalars(
                select(LibrarySourceNode.relative_path).where(
                    LibrarySourceNode.library_id == library_id
                )
            ).all()
        )
        book_bindings = (
            db.execute(
                select(LibraryBook.id, LibraryBook.source_node_id)
                .where(LibraryBook.library_id == library_id)
                .order_by(LibraryBook.id)
            )
            .tuples()
            .all()
        )
        book_ids = [book_id for book_id, _ in book_bindings]
        resource_ids = list(
            db.scalars(
                select(LibraryReadableResource.id).where(
                    LibraryReadableResource.library_id == library_id
                )
            ).all()
        )
        asset_ids = list(
            db.scalars(
                select(LibraryResourceAsset.id).where(
                    LibraryResourceAsset.library_id == library_id
                )
            ).all()
        )

    def digest(values: Iterable[object]) -> str:
        content = "\n".join(sorted(str(value) for value in values)).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    return {
        "capturedAt": utc_now(),
        "sourceNodeCount": len(paths),
        "sourceNodeUniqueRelativePaths": len(set(paths)),
        "bookCount": len(book_ids),
        "bookUniqueIds": len(set(book_ids)),
        "resourceCount": len(resource_ids),
        "resourceUniqueIds": len(set(resource_ids)),
        "assetCount": len(asset_ids),
        "assetUniqueIds": len(set(asset_ids)),
        "relativePathDigest": digest(paths),
        "bookIdDigest": digest(book_ids),
        "bookBindings": dict(book_bindings),
        "resourceIdDigest": digest(resource_ids),
        "assetIdDigest": digest(asset_ids),
    }


@dataclass(frozen=True)
class SourceAssociation:
    resource_id: str
    resource_node_id: str
    format: str
    resource_state: str
    book_id: str | None
    book_node_id: str | None
    book_path: str | None
    book_kind: str | None
    asset_id: str | None
    asset_node_id: str | None
    asset_role: str | None
    asset_state: str | None
    relative_path: str | None
    physical_kind: str | None


@dataclass(frozen=True)
class ScanIntegritySnapshot:
    identity: dict[str, object]
    associations: tuple[SourceAssociation, ...]


def _source_associations(
    engine: Engine, library_id: str
) -> tuple[SourceAssociation, ...]:
    """Project the existing ORM relationships, including broken/absent links."""
    book_node = aliased(LibrarySourceNode)
    with Session(engine) as db:
        rows = db.execute(
            select(
                LibraryReadableResource.id,
                LibraryReadableResource.source_node_id,
                LibraryReadableResource.format,
                LibraryReadableResource.import_state,
                LibraryBook.id,
                book_node.id,
                book_node.relative_path,
                book_node.physical_kind,
                LibraryResourceAsset.id,
                LibraryResourceAsset.source_node_id,
                LibraryResourceAsset.role,
                LibraryResourceAsset.import_state,
                LibrarySourceNode.relative_path,
                LibrarySourceNode.physical_kind,
            )
            .select_from(LibraryReadableResource)
            .outerjoin(LibraryReadableResource.book)
            .outerjoin(LibraryBook.source_node.of_type(book_node))
            .outerjoin(LibraryReadableResource.assets)
            .outerjoin(LibraryResourceAsset.source_node)
            .where(LibraryReadableResource.library_id == library_id)
            .order_by(LibraryReadableResource.id, LibraryResourceAsset.id)
        ).tuples()
        return tuple(SourceAssociation(*row) for row in rows)


def _verify_scan_integrity(
    engine: Engine,
    library_id: str,
    records: list[FileRecord],
    report_path: Path,
    *,
    previous: ScanIntegritySnapshot | None = None,
) -> ScanIntegritySnapshot:
    """Check this single-file corpus, reusing the public Book scope policy."""
    write_json(report_path, {"status": "not_verified", "capturedAt": utc_now()})
    identity = _identity_snapshot(engine, library_id)
    associations = _source_associations(engine, library_id)
    expected = {record.relative_path: record for record in records}
    invalid: list[SourceAssociation] = []
    for binding in associations:
        record = expected.get(binding.relative_path or "")
        if (
            record is None
            or binding.format.lower() != record.format
            or binding.resource_state != "READY"
            or binding.book_id is None
            or binding.book_node_id is None
            or binding.book_path is None
            or binding.book_kind is None
            or binding.asset_id is None
            or binding.asset_node_id != binding.resource_node_id
            or binding.relative_path is None
            or binding.physical_kind != "REGULAR_FILE"
            or binding.asset_role != "PRIMARY"
            or binding.asset_state != "READY"
        ):
            invalid.append(binding)
            continue
        try:
            valid = is_resource_anchor_within_book_scope(
                book_anchor=SourceNodeRelativePath(binding.book_path),
                book_anchor_kind=SourceNodePhysicalKind(binding.book_kind),
                resource_anchor=SourceNodeRelativePath(binding.relative_path),
            )
        except (InvalidSourceNodeRelativePathError, ValueError):
            valid = False
        if not valid:
            invalid.append(binding)
    lost_bindings = (
        set(previous.associations) - set(associations)
        if previous is not None
        else set()
    )
    checks = {
        "countsMatchExpected": (
            bool(records)
            and len(associations)
            == identity["bookCount"]
            == identity["resourceCount"]
            == identity["assetCount"]
            == len(records)
        ),
        "pathsMatchManifest": (
            len(expected) == len(records)
            and {binding.relative_path for binding in associations} == set(expected)
        ),
        "resourceIdsUnique": len({b.resource_id for b in associations}) == len(records),
        "bookIdsUnique": len({b.book_id for b in associations}) == len(records),
        "assetIdsUnique": len({b.asset_id for b in associations}) == len(records),
        "bindingsValid": not invalid,
        "previousBindingsPreserved": not lost_bindings,
        "previousBookIdentitiesPreserved": previous is None
        or all(
            identity["bookBindings"].get(book_id) == source_node_id
            for book_id, source_node_id in previous.identity["bookBindings"].items()
        ),
    }
    passed = all(checks.values())
    write_json(
        report_path,
        {
            "capturedAt": utc_now(),
            "status": "verified" if passed else "failed",
            "checks": checks,
            "identity": identity,
            "associations": [asdict(binding) for binding in associations],
            "invalidBindings": [asdict(binding) for binding in invalid],
            "lostOrChangedBindings": [
                asdict(binding)
                for binding in sorted(lost_bindings, key=lambda b: b.resource_id)
            ],
        },
    )
    if not passed:
        raise RuntimeError(f"resource association integrity failed; see {report_path}")
    return ScanIntegritySnapshot(identity, associations)


def _freeze_scan_settings(client: httpx.Client) -> dict[str, object]:
    expected = {"watchEnabled": False, "intervalMinutes": 1440}
    expect_ok(client.put("/api/system-settings/library-scan", json=expected))
    actual = expect_ok(client.get("/api/system-settings/library-scan"))
    if any(actual.get(key) != value for key, value in expected.items()):
        raise RuntimeError("isolated scan settings were not persisted")
    return actual


def _seed_rescan_sentinels(
    client: httpx.Client,
    pool: dict[str, object],
    state: PhaseState,
    path: Path,
    abort_event: threading.Event,
) -> tuple[dict[str, ReaderV5ProgressSnapshot], dict[str, object]]:
    selected: dict[str, int] = {}
    for index, format_name in enumerate(pool["formats"]):
        selected.setdefault(format_name, index)
    sentinel_indices = set(selected.values())
    sentinels: dict[str, ReaderV5ProgressSnapshot] = {}
    for index in sentinel_indices:
        driver = LoadDriver(
            base_url=str(client.base_url),
            cookies=dict(client.cookies),
            pool={key: [values[index]] for key, values in pool.items()},
            phase="rescan_sentinel",
            state=state,
            output_path=path,
            abort_event=abort_event,
            duration_seconds=1,
            requests_per_second=1,
        )
        result = driver._request(client, "v5_save", 0)
        if result["success"] is not True:
            raise RuntimeError(f"rescan sentinel write failed: {result}")
        sentinels.update(driver.acknowledged)
    _verify_progress(client, sentinels, abort_event)
    write_json(
        path,
        {
            key: value.model_dump(mode="json", by_alias=True)
            for key, value in sentinels.items()
        },
    )
    filtered = {
        key: [
            value for index, value in enumerate(values) if index not in sentinel_indices
        ]
        for key, values in pool.items()
    }
    return sentinels, filtered


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * percentile) - 1))
    return round(ordered[index], 3)


@dataclass
class RequestStatistics:
    sample_count: int = 0
    success_count: int = 0
    durations: list[float] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    first_start: float | None = None
    last_end: float | None = None

    def observe(self, record: dict[str, object]) -> None:
        self.sample_count += 1
        if record.get("success"):
            self.success_count += 1
        else:
            error = (
                record.get("errorCode")
                or record.get("errorType")
                or record.get("status")
            )
            self.errors[str(error)] += 1
        duration = record.get("elapsedMs")
        if isinstance(duration, (int, float)):
            self.durations.append(float(duration))
        if "startedMonotonic" in record:
            start_value = record["startedMonotonic"]
            if not isinstance(start_value, (int, float, str)):
                raise TypeError("request start time must be numeric")
            start = float(start_value)
            self.first_start = (
                min(self.first_start, start)
                if self.first_start is not None
                else float(start)
            )
        if "endedMonotonic" in record:
            end_value = record["endedMonotonic"]
            if not isinstance(end_value, (int, float, str)):
                raise TypeError("request end time must be numeric")
            end = float(end_value)
            self.last_end = (
                max(self.last_end, end) if self.last_end is not None else float(end)
            )


def _request_summaries(requests_path: Path) -> list[dict[str, object]]:
    # Keep exact percentile values and scalar counters, not every request object.
    grouped: dict[tuple[str, str, str], RequestStatistics] = defaultdict(
        RequestStatistics
    )
    with requests_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise TypeError("request evidence must be a JSON object")
                phase, endpoint = record.get("phase"), record.get("endpoint")
                if not isinstance(phase, str) or not isinstance(endpoint, str):
                    raise TypeError(
                        "request evidence must identify its phase and endpoint"
                    )
                scan_label = "scan_active" if record.get("scanActive") else "scan_idle"
                grouped[(phase, endpoint, scan_label)].observe(record)
    summaries: list[dict[str, object]] = []
    for (phase, endpoint, scan_label), statistics in sorted(grouped.items()):
        durations = statistics.durations
        observed_seconds = (
            statistics.last_end - statistics.first_start
            if statistics.last_end is not None and statistics.first_start is not None
            else None
        )
        summaries.append(
            {
                "phase": phase,
                "endpoint": endpoint,
                "scanState": scan_label,
                "sampleCount": statistics.sample_count,
                "successCount": statistics.success_count,
                "failureCount": statistics.sample_count - statistics.success_count,
                "successRate": round(
                    statistics.success_count / statistics.sample_count, 6
                ),
                "observedSeconds": observed_seconds,
                "achievedRequestsPerSecond": statistics.sample_count / observed_seconds
                if observed_seconds
                else None,
                "sampleEvidenceSufficient": statistics.sample_count >= 1000,
                "loadModel": "one serial client per endpoint; configured rate is a ceiling, unsent requests are not successes",
                "latencyMs": {
                    "p50": _percentile(durations, 0.50),
                    "p95": _percentile(durations, 0.95),
                    "p99": _percentile(durations, 0.99),
                    "max": round(max(durations), 3) if durations else None,
                },
                "errors": dict(statistics.errors),
                "releaseP95TargetMs": RELEASE_THRESHOLDS_MS.get(endpoint),
            }
        )
    return summaries


def _resource_summaries(metrics_path: Path) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    with metrics_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                record = json.loads(line)
                grouped[str(record.get("phase"))].append(record)
    summaries: list[dict[str, object]] = []
    for phase, records in sorted(grouped.items()):

        def values(name: str, rows: list[dict[str, object]]) -> list[float]:
            return [
                float(record[name])
                for record in rows
                if isinstance(record.get(name), (int, float))
            ]

        summaries.append(
            {
                "phase": phase,
                "samples": len(records),
                "cpuTotalPercent": {
                    "p50": _percentile(values("cpuTotalPercent", records), 0.50),
                    "p95": _percentile(values("cpuTotalPercent", records), 0.95),
                    "max": max(values("cpuTotalPercent", records), default=None),
                },
                "apiRssBytes": {
                    "p50": _percentile(values("apiRssBytes", records), 0.50),
                    "p95": _percentile(values("apiRssBytes", records), 0.95),
                    "max": max(values("apiRssBytes", records), default=None),
                },
                "workerRssBytes": {
                    "p50": _percentile(values("workerRssBytes", records), 0.50),
                    "p95": _percentile(values("workerRssBytes", records), 0.95),
                    "max": max(values("workerRssBytes", records), default=None),
                },
                "combinedRssBytes": {
                    "p50": _percentile(values("combinedRssBytes", records), 0.50),
                    "p95": _percentile(values("combinedRssBytes", records), 0.95),
                    "max": max(values("combinedRssBytes", records), default=None),
                },
                "availableMemoryBytesMin": min(
                    values("availableMemoryBytes", records), default=None
                ),
                "diskFreeBytesMin": min(values("diskFreeBytes", records), default=None),
            }
        )
    return summaries


def _integrity_evidence(run_root: Path) -> dict[str, object]:
    evidence: dict[str, object] = {}
    for path in sorted((run_root / "integrity").glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        evidence[path.stem] = {
            "path": str(path),
            **{key: value for key, value in report.items() if key != "associations"},
        }
    return evidence


def _write_failure_evidence(run_root: Path, error_type: str) -> dict[str, object]:
    """Summarize an incomplete run without treating missing checks as passing."""
    logs = run_root / "logs"
    config_path = run_root / "run-config.json"
    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path.is_file()
        else {}
    )
    observations = (
        (logs / "scan-progress.jsonl").read_text(encoding="utf-8").splitlines()
        if (logs / "scan-progress.jsonl").is_file()
        else []
    )
    phases = (
        (logs / "phases.jsonl").read_text(encoding="utf-8").splitlines()
        if (logs / "phases.jsonl").is_file()
        else []
    )
    rescan_path = run_root / "rescan-integrity.json"
    summary = {
        "status": "failed",
        "releaseGateStatus": "not_verified",
        "limitations": list(PRECHECK_LIMITATIONS),
        "errorType": error_type,
        "capturedAt": utc_now(),
        "runConfig": config,
        "requestSummaries": _request_summaries(logs / "requests.jsonl")
        if (logs / "requests.jsonl").is_file()
        else [],
        "resourceSummaries": _resource_summaries(logs / "resources.jsonl")
        if (logs / "resources.jsonl").is_file()
        else [],
        "lastScanObservation": json.loads(observations[-1]) if observations else None,
        "phases": [json.loads(line) for line in phases],
        "integrityChecks": _integrity_evidence(run_root),
        "rescan": json.loads(rescan_path.read_text(encoding="utf-8"))
        if rescan_path.is_file()
        else {"status": "not_verified"},
        "missingEvidence": [
            "Only persisted phase records establish progress verification and scan coverage; absent records are unknown.",
            "Only persisted integrity checkpoints establish source hashes and resource associations; absent checkpoints are not verified.",
            "An incomplete run cannot establish the full release LOAD gate.",
        ],
    }
    write_json(run_root / "failure-summary.json", summary)
    return summary


def _backend_source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted((API_ROOT / "app").rglob("*.py")):
        digest.update(path.relative_to(API_ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    for filename in ("pyproject.toml", "uv.lock"):
        path = API_ROOT / filename
        if path.is_file():
            digest.update(filename.encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(RELEASE_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _summary_markdown(summary: dict[str, object], *, run_root: Path) -> str:
    rescan = summary["rescan"]
    if not isinstance(rescan, dict):
        raise TypeError("rescan evidence must be an object")
    compact_rescan = {
        key: {
            identity_key: identity_value
            for identity_key, identity_value in value.items()
            if identity_key != "bookBindings"
        }
        if key in {"before", "after"} and isinstance(value, dict)
        else value
        for key, value in rescan.items()
    }
    lines = [
        "# Local performance precheck",
        "",
        f"- Run root: {run_root}",
        f"- Captured: {summary['capturedAt']}",
        f"- Release commit: {summary['releaseCommit']}",
        "- Scope: isolated API + Worker + real scan; no production process was targeted.",
        "- Result type: precheck evidence only; no release-gate PASS is asserted.",
        "",
        "## Dataset",
        "",
        "| format | files | share | bytes | unique hashes | sizes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    dataset = summary["dataset"]
    for format_name, value in dataset["formats"].items():
        lines.append(
            f"| {format_name} | {value['files']} | {value['percent']}% | "
            f"{value['bytes']} | {value['uniqueHashes']} | {value['sizeBytes']} |"
        )
    lines.extend(
        [
            "",
            f"Total valid files: {dataset['files']}; unique SHA-256 values: {dataset['uniqueHashes']}.",
            "",
            "## API samples",
            "",
            "| phase | scan state | endpoint | n | success | p95 ms | p99 ms | target p95 ms |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in summary["requestSummaries"]:
        latency = item["latencyMs"]
        lines.append(
            f"| {item['phase']} | {item['scanState']} | {item['endpoint']} | "
            f"{item['sampleCount']} | {item['successRate']} | "
            f"{latency['p95']} | {latency['p99']} | {item['releaseP95TargetMs']} |"
        )
    lines.extend(
        [
            "",
            "## Rescan identity",
            "",
            json.dumps(compact_rescan, ensure_ascii=False, indent=2),
            "",
            (
                "Full book bindings and identity evidence: "
                "[rescan-integrity.json](rescan-integrity.json); full report: [summary.json](summary.json)."
            ),
            "",
            "## Evidence paths",
            "",
        ]
    )
    for key, value in summary["evidence"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {value}" for value in summary["limitations"])
    lines.extend(
        [
            "",
            "## Actual load and scan coverage",
            "",
            json.dumps(summary["phases"], ensure_ascii=False, indent=2),
        ]
    )
    return "\n".join(lines) + "\n"


def _start_service_processes(
    run_root: Path,
    env: dict[str, str],
    port: int,
) -> tuple[LoggedProcess, LoggedProcess]:
    prestart_log = run_root / "logs" / "prestart.log"
    with prestart_log.open("w", encoding="utf-8") as stream:
        subprocess.run(
            [sys.executable, "-m", "app.bootstrap.prestart"],
            cwd=API_ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=30,
        )
    api = start_logged_process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=API_ROOT,
        env=env,
        log_path=run_root / "logs" / "api.log",
    )
    worker: LoggedProcess | None = None
    try:
        wait_for_health(f"http://127.0.0.1:{port}", api)
        worker = start_logged_process(
            [sys.executable, "-m", "app.worker.main"],
            cwd=API_ROOT,
            env=env,
            log_path=run_root / "logs" / "worker.log",
        )
        wait_for_worker(Path(env["IMPORT_WORKER_READY_FILE"]), worker)
        return api, worker
    except BaseException:
        if worker is not None:
            worker.stop(timeout=12)
        api.stop(timeout=12)
        raise


def _stop_services(
    api: LoggedProcess | None,
    worker: LoggedProcess | None,
) -> list[str]:
    errors: list[str] = []
    if worker is not None:
        try:
            worker.stop(timeout=12)
        except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
            errors.append(f"worker stop: {type(exc).__name__}: {exc}")
    if api is not None:
        try:
            api.stop(timeout=12)
        except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
            errors.append(f"api stop: {type(exc).__name__}: {exc}")
    return errors


def _new_run_root(label: str) -> Path:
    RUN_ROOT_PARENT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_root = RUN_ROOT_PARENT / f"{label}-{stamp}"
    run_root.mkdir(parents=True, exist_ok=False)
    (run_root / "logs").mkdir()
    return run_root


def run_small_smoke(corpus: CorpusConfig) -> Path:
    run_root = _new_run_root("fixture-smoke")
    source_root = run_root / "library"
    source_root.mkdir()
    selected: dict[str, FileSpec] = {}
    for spec in _file_specs(corpus):
        selected.setdefault(spec[0], spec)
        if len(selected) == len(corpus.format_counts):
            break
    records: list[FileRecord] = []
    for spec in selected.values():
        record = _write_one_spec(source_root, spec)
        _validate_file(record, source_root)
        records.append(record)
    summary = {
        "capturedAt": utc_now(),
        "status": "small-smoke-ok",
        "corpusConfig": corpus.evidence(),
        "files": [asdict(record) for record in records],
        "summary": dataset_summary(records),
        "releaseRoot": str(RELEASE_ROOT),
        "releaseCommit": _git_commit(),
    }
    write_json(run_root / "small-smoke.json", summary)
    print(f"small smoke complete: {run_root}", flush=True)
    return run_root


def run_prepare_only(corpus: CorpusConfig) -> Path:
    run_root = _new_run_root(f"corpus-{corpus.scale_label}")
    source_root = run_root / "library"
    source_root.mkdir()
    records = generate_dataset(
        source_root,
        corpus.total_files,
        corpus=corpus,
        log_path=run_root / "logs" / "dataset-generation.log",
    )
    _validate_dataset_records(records, corpus.format_counts)
    summary = {
        "capturedAt": utc_now(),
        "status": "corpus-ready",
        **corpus.evidence(),
        "root": str(source_root),
        "releaseRoot": str(RELEASE_ROOT),
        "releaseCommit": _git_commit(),
        "records": [asdict(record) for record in records],
        "summary": dataset_summary(records),
        "validation": {
            "allFilesWrittenAndReopened": True,
            "databaseRowsWritten": False,
            "formats": [name.upper() for name in corpus.format_counts],
        },
    }
    write_json(run_root / "dataset-manifest.json", summary)
    print(f"{corpus.scale_label} corpus ready: {run_root}", flush=True)
    return run_root


def run_measurement(args: argparse.Namespace) -> Path:
    corpus = CorpusConfig(args.total_files)
    source_commit = _git_commit()
    backend_digest = _backend_source_digest()
    if not RELEASE_ROOT.is_dir():
        raise RuntimeError(f"release worktree is missing: {RELEASE_ROOT}")
    prepared_source: Path | None = None
    prepared_records: list[FileRecord] | None = None
    if args.prepared_corpus_root is not None:
        prepared_source, prepared_records = _load_prepared_corpus(
            args.prepared_corpus_root, corpus
        )

    run_root = _new_run_root("measurement")
    logs_root = run_root / "logs"
    source_root = run_root / "library"
    storage_root = run_root / "storage"
    source_root.mkdir()
    storage_root.mkdir()
    generation_log = logs_root / "dataset-generation.log"
    dataset_manifest = run_root / "dataset-manifest.json"
    progress_path = logs_root / "scan-progress.jsonl"
    requests_path = logs_root / "requests.jsonl"
    metrics_path = logs_root / "resources.jsonl"
    machine = _machine_snapshot(run_root)
    budget = {
        "releaseGateTargets": {
            "listP95Ms": 2_000,
            "detailP95Ms": 2_000,
            "searchP95Ms": 3_000,
            "v5SaveP95Ms": 2_000,
            "coreApiSuccessRate": 0.999,
            "p99": "recorded; release-gate.md contains no numeric P99 threshold",
        },
        "localSafetyGuardrails": {
            "combinedApiWorkerRssSoftBytes": 8 * 1024**3,
            "combinedApiWorkerRssHardBytes": 12 * 1024**3,
            "minimumAvailablePhysicalMemoryBytes": 768 * 1024**2,
            "minimumDDriveFreeBytes": 20 * 1024**3,
        },
        "machineAtStart": machine,
    }
    write_json(run_root / "machine.json", machine)
    write_json(run_root / "budget.json", budget)
    write_json(
        run_root / "run-config.json",
        {
            "capturedAt": utc_now(),
            "releaseRoot": str(RELEASE_ROOT),
            "releaseCommit": source_commit,
            "backendSourceSha256": backend_digest,
            "python": sys.executable,
            "psutilVersion": psutil.__version__,
            "runnerSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            **corpus.evidence(),
            "idleWindowSeconds": args.idle_window_seconds,
            "activeWindowSeconds": args.active_window_seconds,
            "requestRatePerEndpoint": args.request_rate,
            "scanTimeoutSeconds": args.scan_timeout_seconds,
            "overallTimeoutSeconds": args.overall_timeout_seconds,
            "overallTimeoutOwner": "supervisor",
            "launcher": "direct sys.executable -m uvicorn / -m app.worker.main",
            "preparedCorpusRoot": (
                str(args.prepared_corpus_root.resolve())
                if args.prepared_corpus_root is not None
                else None
            ),
            "datasetMode": "prepared-copy"
            if prepared_records is not None
            else "generate",
        },
    )

    print(f"measurement run root: {run_root}", flush=True)
    if prepared_records is None or prepared_source is None:
        print(
            f"generating and validating initial {corpus.initial_files:,} real files",
            flush=True,
        )
        initial_records = generate_dataset(
            source_root,
            corpus.initial_files,
            corpus=corpus,
            log_path=generation_log,
        )
    else:
        print(
            f"staging and hash-validating initial {corpus.initial_files:,} prepared real files",
            flush=True,
        )
        initial_records = stage_dataset(
            prepared_source,
            source_root,
            prepared_records,
            start_index=0,
            end_index=corpus.initial_files,
            log_path=generation_log,
        )
    write_json(
        dataset_manifest,
        {
            "capturedAt": utc_now(),
            "stage": "initial",
            "corpusConfig": corpus.evidence(),
            "root": str(source_root),
            "records": [asdict(record) for record in initial_records],
            "summary": dataset_summary(initial_records),
        },
    )

    api: LoggedProcess | None = None
    worker: LoggedProcess | None = None
    sampler: ResourceSampler | None = None
    abort_event = threading.Event()
    phase_state = PhaseState()
    scan_results: list[dict[str, object]] = []
    phase_results: list[dict[str, object]] = []
    engine = None
    cleanup_errors: list[str] = []
    failure: Exception | None = None
    try:
        _verify_source_hashes(
            source_root,
            initial_records,
            run_root / "integrity/source-initial-before.json",
        )
        _validate_dataset_records(initial_records, corpus.initial_format_counts)
        api_port = free_port()
        worker_ready = run_root / "import-worker-ready"
        env = {
            **os.environ,
            "SESSION_SECRET": "local-perf-precheck-session-secret-32chars",
            "STORAGE_ROOT": str(storage_root),
            "DOWNLOAD_INBOX_PATH": str(run_root / "downloads" / "inbox"),
            "IMPORT_WORKER_READY_FILE": str(worker_ready),
            "IMPORT_QUEUE_INTERVAL_SECONDS": "1",
            "DOWNLOAD_QUEUE_ENABLED": "false",
            "KINDLE_SEND_QUEUE_ENABLED": "false",
            "PYTHONIOENCODING": "utf-8",
        }
        (run_root / "downloads" / "inbox").mkdir(parents=True)
        api, worker = _start_service_processes(run_root, env, api_port)
        write_json(
            run_root / "process-config.json",
            {
                "apiPort": api_port,
                "storageRoot": str(storage_root),
                "libraryRoot": str(source_root),
                "workerReadyFile": str(worker_ready),
                "apiPid": api.process.pid,
                "workerPid": worker.process.pid,
                "preExistingServicesUntouched": True,
            },
        )
        sampler = ResourceSampler(
            metrics_path,
            api=api,
            worker=worker,
            state_provider=phase_state.snapshot,
            root=run_root,
            abort_event=abort_event,
        )
        sampler.start()
        time.sleep(15)

        settings = Settings(storage_root=str(storage_root))
        engine = create_sqlite_engine(settings.database_path)
        base_url = f"http://127.0.0.1:{api_port}"
        with httpx.Client(
            base_url=base_url,
            follow_redirects=False,
            timeout=15,
        ) as client:
            setup_status = expect_ok(client.get("/api/auth/setup/status"))
            if setup_status.get("initialized") is not False:
                raise RuntimeError(f"isolated setup was not fresh: {setup_status}")
            setup = expect_ok(
                client.post(
                    "/api/auth/setup",
                    json={
                        "name": "Local performance precheck",
                        "email": f"perf-precheck-{run_root.name}@example.com",
                        "password": "local-perf-precheck-password",
                    },
                )
            )
            if setup.get("initialized") is not True:
                raise RuntimeError(f"isolated setup failed: {setup}")
            scan_settings = _freeze_scan_settings(client)
            write_json(run_root / "scan-settings.json", scan_settings)
            # Coordinator polls settings every five seconds; freeze before new files exist.
            time.sleep(6)
            library_id = create_fixture_library(client, source_root)

            phase_state.set("active_initial_scan", scan_active=True)
            initial_task_id = _trigger_scan(client, library_id)
            initial_scan = _wait_for_scan(
                engine,
                library_id,
                initial_task_id,
                corpus.initial_files,
                phase="active_initial_scan",
                state=phase_state,
                progress_path=progress_path,
                abort_event=abort_event,
                timeout_seconds=args.scan_timeout_seconds,
            )
            scan_results.append(initial_scan)
            _verify_source_hashes(
                source_root,
                initial_records,
                run_root / "integrity/source-initial-after.json",
            )
            initial_integrity = _verify_scan_integrity(
                engine,
                library_id,
                initial_records,
                run_root / "integrity/associations-initial-after.json",
            )

            phase_state.set("dataset_expand", scan_active=False)
            if prepared_records is None or prepared_source is None:
                print(
                    f"generating and validating the remaining {corpus.total_files - corpus.initial_files:,} real files",
                    flush=True,
                )
                remaining_records = generate_dataset(
                    source_root,
                    corpus.total_files,
                    corpus=corpus,
                    start_index=corpus.initial_files,
                    log_path=generation_log,
                )
            else:
                print(
                    f"staging and hash-validating the remaining {corpus.total_files - corpus.initial_files:,} prepared real files",
                    flush=True,
                )
                remaining_records = stage_dataset(
                    prepared_source,
                    source_root,
                    prepared_records,
                    start_index=corpus.initial_files,
                    end_index=corpus.total_files,
                    log_path=generation_log,
                )
            records = initial_records + remaining_records
            _validate_dataset_records(records, corpus.format_counts)
            write_json(
                dataset_manifest,
                {
                    "capturedAt": utc_now(),
                    "stage": "complete",
                    "corpusConfig": corpus.evidence(),
                    "root": str(source_root),
                    "records": [asdict(record) for record in records],
                    "summary": dataset_summary(records),
                    "validFiles": len(records) == corpus.total_files,
                },
            )
            if len(records) != corpus.total_files:
                raise RuntimeError(
                    f"expected {corpus.total_files} files, found {len(records)}"
                )

            pool_initial = _resource_pool(engine, library_id)
            if len(pool_initial["resourceIds"]) != corpus.initial_files:
                raise RuntimeError(
                    "initial scan resource count mismatch: "
                    f"{len(pool_initial['resourceIds'])}"
                )
            _v5_sanity(
                client,
                pool_initial,
                output_path=run_root / "v5-sanity-initial.json",
            )

            _verify_source_hashes(
                source_root, records, run_root / "integrity/source-growth-before.json"
            )
            growth_phase = _run_load_phase(
                client=client,
                engine=engine,
                library_id=library_id,
                task_expected_resources=corpus.total_files,
                phase="active_growth_scan",
                pool=pool_initial,
                state=phase_state,
                requests_path=requests_path,
                progress_path=progress_path,
                abort_event=abort_event,
                duration_seconds=args.active_window_seconds,
                requests_per_second=args.request_rate,
                scan=True,
                scan_timeout_seconds=args.scan_timeout_seconds,
            )
            phase_results.append(growth_phase)
            if growth_phase["scan"] is not None:
                scan_results.append(growth_phase["scan"])
            _verify_source_hashes(
                source_root, records, run_root / "integrity/source-growth-after.json"
            )
            growth_integrity = _verify_scan_integrity(
                engine,
                library_id,
                records,
                run_root / "integrity/associations-growth-after.json",
                previous=initial_integrity,
            )

            pool_full = _resource_pool(engine, library_id)
            if len(pool_full["resourceIds"]) != corpus.total_files:
                raise RuntimeError(
                    f"full scan did not produce {corpus.total_files} resources: "
                    f"{len(pool_full['resourceIds'])}"
                )
            _v5_sanity(client, pool_full, output_path=run_root / "v5-sanity-full.json")

            idle_phase = _run_load_phase(
                client=client,
                engine=engine,
                library_id=library_id,
                task_expected_resources=corpus.total_files,
                phase=f"idle_{corpus.scale_label}",
                pool=pool_full,
                state=phase_state,
                requests_path=requests_path,
                progress_path=progress_path,
                abort_event=abort_event,
                duration_seconds=args.idle_window_seconds,
                requests_per_second=args.request_rate,
                scan=False,
                scan_timeout_seconds=args.scan_timeout_seconds,
            )
            phase_results.append(idle_phase)

            _verify_source_hashes(
                source_root, records, run_root / "integrity/source-rescan-before.json"
            )
            before_integrity = _verify_scan_integrity(
                engine,
                library_id,
                records,
                run_root / "integrity/associations-rescan-before.json",
                previous=growth_integrity,
            )
            before_rescan = before_integrity.identity
            sentinels, rescan_pool = _seed_rescan_sentinels(
                client,
                pool_full,
                phase_state,
                run_root / "rescan-sentinels.json",
                abort_event,
            )
            rescan_phase = _run_load_phase(
                client=client,
                engine=engine,
                library_id=library_id,
                task_expected_resources=corpus.total_files,
                phase="active_rescan",
                pool=rescan_pool,
                state=phase_state,
                requests_path=requests_path,
                progress_path=progress_path,
                abort_event=abort_event,
                duration_seconds=args.active_window_seconds,
                requests_per_second=args.request_rate,
                scan=True,
                scan_timeout_seconds=args.scan_timeout_seconds,
            )
            phase_results.append(rescan_phase)
            if rescan_phase["scan"] is not None:
                scan_results.append(rescan_phase["scan"])
            _verify_source_hashes(
                source_root, records, run_root / "integrity/source-rescan-after.json"
            )
            after_integrity = _verify_scan_integrity(
                engine,
                library_id,
                records,
                run_root / "integrity/associations-rescan-after.json",
                previous=before_integrity,
            )
            after_rescan = after_integrity.identity
            sentinel_integrity = _verify_progress(client, sentinels, abort_event)
            rescan_integrity = {
                "sentinelProgress": sentinel_integrity,
                "sourceHashesAfterScanVerified": True,
                "resourceAssociationIntegrityVerified": True,
                "before": before_rescan,
                "after": after_rescan,
                "countsUnchanged": all(
                    before_rescan[key] == after_rescan[key]
                    for key in (
                        "sourceNodeCount",
                        "bookCount",
                        "resourceCount",
                        "assetCount",
                    )
                ),
                "relativePathsUniqueAfter": (
                    after_rescan["sourceNodeCount"]
                    == after_rescan["sourceNodeUniqueRelativePaths"]
                ),
                "idsUniqueAfter": all(
                    after_rescan[f"{kind}Count"] == after_rescan[f"{kind}UniqueIds"]
                    for kind in ("book", "resource", "asset")
                ),
                "identityDigestsUnchanged": all(
                    before_rescan[key] == after_rescan[key]
                    for key in (
                        "relativePathDigest",
                        "bookIdDigest",
                        "resourceIdDigest",
                        "assetIdDigest",
                    )
                ),
            }
            write_json(run_root / "rescan-integrity.json", rescan_integrity)
            if any(
                rescan_integrity[key] is not True
                for key in (
                    "countsUnchanged",
                    "relativePathsUniqueAfter",
                    "idsUniqueAfter",
                    "identityDigestsUnchanged",
                    "sourceHashesAfterScanVerified",
                    "resourceAssociationIntegrityVerified",
                )
            ):
                raise RuntimeError(
                    "rescan changed resource identity or introduced duplicates"
                )
        if abort_event.is_set():
            raise RuntimeError(
                f"local safety guardrail reached: "
                f"{sampler.abort_reason if sampler else 'unknown'}"
            )
    except Exception as error:
        logger.exception("measurement.failed")
        failure = error
    finally:
        if sampler is not None:
            sampler.stop()
        if engine is not None:
            engine.dispose()
        cleanup_errors = _stop_services(api, worker)

    if failure is not None:
        _write_failure_evidence(run_root, type(failure).__name__)
        raise failure
    if backend_digest != _backend_source_digest():
        raise RuntimeError(
            "backend source changed during measurement; evidence invalid"
        )
    request_summaries = _request_summaries(requests_path)
    resource_summaries = _resource_summaries(metrics_path)
    rescan_integrity = json.loads(
        (run_root / "rescan-integrity.json").read_text(encoding="utf-8")
    )
    summary: dict[str, object] = {
        "capturedAt": utc_now(),
        "releaseGateStatus": "not_verified",
        "corpusConfig": corpus.evidence(),
        "releaseCommit": source_commit,
        "backendSourceSha256": backend_digest,
        "dataset": dataset_summary(records),
        "scanResults": scan_results,
        "phases": phase_results,
        "requestSummaries": request_summaries,
        "performanceTargetViolations": [
            {
                "phase": row["phase"],
                "scanState": row["scanState"],
                "endpoint": row["endpoint"],
            }
            for row in request_summaries
            if row["successRate"] < 0.999
            or row["latencyMs"]["p95"] is None
            or row["latencyMs"]["p95"] > row["releaseP95TargetMs"]
        ],
        "resourceSummaries": resource_summaries,
        "rescan": rescan_integrity,
        "integrityChecks": _integrity_evidence(run_root),
        "budget": budget,
        "cleanupErrors": cleanup_errors,
        "limitations": list(PRECHECK_LIMITATIONS),
        "evidence": {
            "machine": str(run_root / "machine.json"),
            "budget": str(run_root / "budget.json"),
            "runConfig": str(run_root / "run-config.json"),
            "processConfig": str(run_root / "process-config.json"),
            "datasetManifest": str(dataset_manifest),
            "preparedCorpusManifest": (
                str(prepared_source.parent / "dataset-manifest.json")
                if prepared_source is not None
                else None
            ),
            "generationLog": str(generation_log),
            "prestartLog": str(logs_root / "prestart.log"),
            "apiLog": str(logs_root / "api.log"),
            "workerLog": str(logs_root / "worker.log"),
            "scanProgress": str(progress_path),
            "requests": str(requests_path),
            "resources": str(metrics_path),
            "rescanIntegrity": str(run_root / "rescan-integrity.json"),
            "integrityChecks": str(run_root / "integrity"),
            "v5SanityInitial": str(run_root / "v5-sanity-initial.json"),
            "v5SanityFull": str(run_root / "v5-sanity-full.json"),
        },
    }
    write_json(run_root / "summary.json", summary)
    (run_root / "summary.md").write_text(
        _summary_markdown(summary, run_root=run_root),
        encoding="utf-8",
    )
    write_json(
        run_root / "complete.json",
        {
            "capturedAt": utc_now(),
            "releaseGateStatus": "not_verified",
            "status": "completed_with_failures"
            if summary["performanceTargetViolations"]
            or any(phase.get("status") == "failed" for phase in phase_results)
            or cleanup_errors
            else "completed",
            "summary": str(run_root / "summary.json"),
            "markdown": str(run_root / "summary.md"),
        },
    )
    print(f"measurement complete: {run_root}", flush=True)
    if (
        summary["performanceTargetViolations"]
        or any(phase.get("status") == "failed" for phase in phase_results)
        or cleanup_errors
    ):
        raise RuntimeError(f"measurement evidence collected with failures: {run_root}")
    return run_root


def _supervise_measurement_process(
    process: LoggedProcess, state_path: Path, timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds
    descendants: dict[int, psutil.Process] = {}
    try:
        while process.poll() is None:
            try:
                for child in psutil.Process(process.process.pid).children(
                    recursive=True
                ):
                    descendants[child.pid] = child
            except psutil.NoSuchProcess:
                break
            if state_path.is_file():
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("status") == "failed":
                    raise RuntimeError(
                        f"measurement child failed; see {process.log_path}"
                    )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"measurement exceeded {timeout_seconds}s; see {process.log_path}"
                )
            time.sleep(0.2)
        if process.poll() != 0:
            raise RuntimeError(
                f"measurement child exited {process.poll()}; see {process.log_path}"
            )
    finally:
        try:
            process.stop(timeout=5)
        finally:
            # The API and worker own separate groups; retain their exact process
            # identities while the runner lives, including the Windows venv launcher.
            _, alive = psutil.wait_procs(list(descendants.values()), timeout=2)
            for child in alive:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    continue  # Child exited between wait and kill.
            _, survivors = psutil.wait_procs(alive, timeout=5)
            if survivors:
                raise TimeoutError(
                    f"owned measurement descendants remain: {[child.pid for child in survivors]}"
                )


def run_supervised_measurement(args: argparse.Namespace) -> None:
    corpus = CorpusConfig(args.total_files)
    root = _new_run_root("supervisor")
    state_path = root / "child-state.json"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--measure-window",
        "--measurement-child",
        "--supervisor-state",
        str(state_path),
        "--total-files",
        str(corpus.total_files),
        "--idle-window-seconds",
        str(args.idle_window_seconds),
        "--active-window-seconds",
        str(args.active_window_seconds),
        "--request-rate",
        str(args.request_rate),
        "--scan-timeout-seconds",
        str(args.scan_timeout_seconds),
        "--overall-timeout-seconds",
        str(args.overall_timeout_seconds),
    ]
    if args.prepared_corpus_root is not None:
        command.extend(
            ["--prepared-corpus-root", str(args.prepared_corpus_root.resolve())]
        )
    write_json(
        root / "supervisor-config.json",
        {
            **corpus.evidence(),
            "overallTimeoutSeconds": args.overall_timeout_seconds,
            "measurementCommand": command,
        },
    )
    print(f"supervisor evidence: {root}", flush=True)
    process = start_logged_process(
        command,
        cwd=RELEASE_ROOT,
        env=os.environ,
        log_path=root / "logs/measurement.log",
    )
    _supervise_measurement_process(process, state_path, args.overall_timeout_seconds)
    print(state_path.read_text(encoding="utf-8"), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare local corpus or run an explicitly enabled measurement window."
    )
    parser.add_argument(
        "--total-files",
        type=int,
        choices=SUPPORTED_TOTAL_FILES,
        default=SUPPORTED_TOTAL_FILES[0],
        help="total compact real files; the initial library is always 20 percent",
    )
    parser.add_argument(
        "--small-smoke",
        action="store_true",
        help="write and reopen one valid EPUB/PDF/CBZ in an isolated directory",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="generate and validate the selected corpus without services",
    )
    parser.add_argument(
        "--measure-window",
        action="store_true",
        help="run local precheck idle/active windows in an isolated test library",
    )
    parser.add_argument(
        "--prepared-corpus-root",
        type=Path,
        help=(
            "reuse a validated corpus directory of the selected size (or its library directory) "
            "and stage it into the isolated measurement run"
        ),
    )
    parser.add_argument("--idle-window-seconds", type=float, default=135)
    parser.add_argument("--active-window-seconds", type=float, default=180)
    parser.add_argument("--request-rate", type=float, default=10)
    parser.add_argument("--scan-timeout-seconds", type=float, default=2_700)
    parser.add_argument("--overall-timeout-seconds", type=float, default=3600)
    parser.add_argument(
        "--summarize-failed-run",
        type=Path,
        help="summarize existing incomplete evidence without starting services",
    )
    parser.add_argument(
        "--measurement-child", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--supervisor-state", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    for value in (
        args.idle_window_seconds,
        args.active_window_seconds,
        args.request_rate,
        args.scan_timeout_seconds,
        args.overall_timeout_seconds,
    ):
        if not math.isfinite(value) or value <= 0:
            parser.error(
                "window durations, request rate and scan timeout must be finite and positive"
            )
    modes = sum(
        bool(value)
        for value in (args.small_smoke, args.prepare_only, args.measure_window)
    )
    if args.summarize_failed_run is not None:
        if modes:
            parser.error("offline summary cannot be combined with an execution mode")
        _write_failure_evidence(
            args.summarize_failed_run.resolve(), "See supervisor log"
        )
        return 0
    if modes > 1:
        parser.error("choose at most one execution mode")
    if args.measure_window:
        if args.measurement_child:
            if args.supervisor_state is None:
                parser.error("measurement child requires supervisor state")
            try:
                run_root = run_measurement(args)
            except BaseException:
                write_json(args.supervisor_state, {"status": "failed"})
                raise
            write_json(
                args.supervisor_state, {"status": "completed", "runRoot": str(run_root)}
            )
        else:
            run_supervised_measurement(args)
    elif args.prepare_only:
        run_prepare_only(CorpusConfig(args.total_files))
    else:
        run_small_smoke(CorpusConfig(args.total_files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
