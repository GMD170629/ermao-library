#!/usr/bin/env python3
"""Generate deterministic EPUB fixtures for monitored-import performance tests.

Files are written with an unsupported ``.part`` suffix and atomically renamed
only after the EPUB archive is complete, so the import watcher never observes a
half-written book.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import time
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape


MARKER_NAME = ".shuku-import-performance-fixture"
DEFAULT_COUNT = 5_000
MIN_PAYLOAD_BYTES = 12 * 1024


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def deterministic_payload(index: int, size: int = MIN_PAYLOAD_BYTES) -> bytes:
    chunks: list[bytes] = []
    sequence = 0
    while sum(map(len, chunks)) < size:
        chunks.append(
            hashlib.sha256(f"shuku-import-perf:{index}:{sequence}".encode()).digest()
        )
        sequence += 1
    return b"".join(chunks)[:size]


def epub_entries(index: int) -> dict[str, str | bytes]:
    number = f"{index:05d}"
    title = f"导入压测{number}"
    author = "压测作者"
    identifier = f"urn:uuid:shuku-import-performance-{number}"
    chapter = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="zh-CN">
  <head><title>{escape(title)}</title></head>
  <body><h1>{escape(title)}</h1><p>这是第 {index} 本导入性能测试电子书。</p></body>
</html>
"""
    return {
        "META-INF/container.xml": """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
""",
        "OEBPS/content.opf": f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id" xml:lang="zh-CN">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">{identifier}</dc:identifier>
    <dc:title>{escape(title)}</dc:title>
    <dc:creator>{escape(author)}</dc:creator>
    <dc:language>zh-CN</dc:language>
    <dc:publisher>书库性能测试出版社</dc:publisher>
    <dc:description>用于监控导入吞吐量测试的第 {index} 本电子书。</dc:description>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="chapter"/></spine>
</package>
""",
        "OEBPS/nav.xhtml": f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <head><title>目录</title></head>
  <body><nav epub:type="toc"><ol><li><a href="chapter.xhtml">{escape(title)}</a></li></ol></nav></body>
</html>
""",
        "OEBPS/chapter.xhtml": chapter,
        "OEBPS/performance-payload.bin": deterministic_payload(index),
    }


def write_epub(path: Path, index: int) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        for name, content in epub_entries(index).items():
            archive.writestr(name, content, compress_type=zipfile.ZIP_STORED)
    temporary.replace(path)


def clean_output(output: Path) -> int:
    marker = output / MARKER_NAME
    if not output.exists():
        print(f"无需清理：{output} 不存在")
        return 0
    if not marker.is_file():
        print(f"拒绝清理：{output} 缺少安全标记 {MARKER_NAME}", file=sys.stderr)
        return 2
    shutil.rmtree(output)
    print(f"已清理性能测试目录：{output}")
    return 0


def show_status(output: Path, database: Path) -> int:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        print(f"找不到性能测试清单：{manifest_path}", file=sys.stderr)
        return 2
    if not database.is_file():
        print(f"找不到数据库：{database}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    epub_files = list(output.glob("*.epub"))
    started_at = min((item.stat().st_mtime for item in epub_files), default=time.time())
    elapsed = max(time.time() - started_at, 0.001)
    path_pattern = f"{output.resolve()}/%"

    connection = sqlite3.connect(
        f"file:{database.resolve()}?mode=ro", uri=True, timeout=10
    )
    try:
        statuses = dict(
            connection.execute(
                "SELECT status, COUNT(1) FROM ImportTask WHERE sourcePath LIKE ? GROUP BY status",
                (path_pattern,),
            ).fetchall()
        )
        completed, average_ms, maximum_ms = connection.execute(
            "SELECT COUNT(1), COALESCE(AVG(duration), 0), COALESCE(MAX(duration), 0) "
            "FROM ImportTask WHERE sourcePath LIKE ? AND status = 'COMPLETED'",
            (path_pattern,),
        ).fetchone()
        failures = connection.execute(
            "SELECT sourcePath, errorSummary FROM ImportTask "
            "WHERE sourcePath LIKE ? AND status = 'FAILED' ORDER BY createdAt DESC LIMIT 5",
            (path_pattern,),
        ).fetchall()
    finally:
        connection.close()

    expected = int(manifest.get("requestedCount") or len(epub_files))
    observed = sum(int(value) for value in statuses.values())
    report = {
        "expectedFiles": expected,
        "epubFiles": len(epub_files),
        "tasksObserved": observed,
        "statuses": statuses,
        "completed": int(completed),
        "failed": int(statuses.get("FAILED", 0)),
        "averageImportDurationMs": round(float(average_ms), 2),
        "maximumImportDurationMs": int(maximum_ms),
        "elapsedSeconds": round(elapsed, 1),
        "observedTasksPerSecond": round(observed / elapsed, 2),
        "remainingUndiscoveredFiles": max(0, expected - observed),
        "recentFailures": [
            {"path": source_path, "error": error_summary}
            for source_path, error_summary in failures
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def generate(output: Path, count: int) -> int:
    if count <= 0:
        raise ValueError("--count 必须大于 0")
    output.mkdir(parents=True, exist_ok=True)
    marker = output / MARKER_NAME
    marker.touch(exist_ok=True)

    started = time.perf_counter()
    created = 0
    existing = 0
    for index in range(1, count + 1):
        filename = f"导入压测{index:05d} - 压测作者.epub"
        target = output / filename
        if target.is_file():
            existing += 1
        else:
            write_epub(target, index)
            created += 1
        if index % 500 == 0 or index == count:
            elapsed = max(time.perf_counter() - started, 0.001)
            print(
                f"进度 {index}/{count}，新建 {created}，已存在 {existing}，{index / elapsed:.1f} 本/秒",
                flush=True,
            )

    elapsed = time.perf_counter() - started
    files = list(output.glob("*.epub"))
    total_bytes = sum(item.stat().st_size for item in files)
    manifest = {
        "kind": "shuku-import-performance-fixture",
        "requestedCount": count,
        "epubCount": len(files),
        "createdThisRun": created,
        "existingThisRun": existing,
        "totalBytes": total_bytes,
        "generationDurationSeconds": round(elapsed, 3),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))
    print(f"生成完成：{output}")
    print(f"清理命令：python3 {Path(__file__).name} --output {output} --clean")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成书库监控导入性能测试 EPUB")
    parser.add_argument(
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"生成数量，默认 {DEFAULT_COUNT}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=project_root() / "books" / "import-performance-5000",
        help="输出目录",
    )
    parser.add_argument(
        "--clean", action="store_true", help="只清理带安全标记的输出目录"
    )
    parser.add_argument(
        "--status", action="store_true", help="读取数据库并报告这批文件的导入状态"
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=project_root() / "storage" / "database" / "shuku.sqlite3",
        help="--status 使用的 SQLite 数据库路径",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    if args.clean:
        return clean_output(output)
    if args.status:
        return show_status(output, args.database.expanduser().resolve())
    return generate(output, args.count)


if __name__ == "__main__":
    raise SystemExit(main())
