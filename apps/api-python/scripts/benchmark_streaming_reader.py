"""Measure original-source parsing and one requested chapter; never client acceptance."""

from __future__ import annotations

import argparse
import json
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter

from app.contracts.publication_sources import PublicationSource
from app.modules.publications.infrastructure.epub_adapter import EpubPublicationAdapter
from app.modules.publications.infrastructure.txt_adapter import TxtPublicationAdapter


def measure(
    path: Path, source_format: str, href: str | None = None
) -> dict[str, str | int | float | None]:
    path = path.resolve(strict=True)
    stat = path.stat()
    source = PublicationSource(
        "benchmark-resource",
        "benchmark-asset",
        source_format,
        str(path),
        stat.st_size,
        int(stat.st_mtime * 1000),
        path.stem,
        None,
        str(path.parent),
    )
    adapter = (
        EpubPublicationAdapter(path.parent)
        if source_format == "epub"
        else TxtPublicationAdapter(path.parent)
    )
    tracemalloc.start()
    try:
        started = perf_counter()
        publication = adapter.open(source)
        parsed = perf_counter()
        first_href = href or publication.reading_order[0].href
        resource = adapter.read_resource(source, first_href)
        received = perf_counter()
        _, peak = tracemalloc.get_traced_memory()
        warm_started = perf_counter()
        adapter.open(source)
        warm_ms = (perf_counter() - warm_started) * 1000
        return {
            "format": source_format,
            "sample": path.name,
            "originalBytes": stat.st_size,
            "readingUnits": len(publication.reading_order),
            "firstHref": first_href,
            "serverParseMs": round((parsed - started) * 1000, 2),
            "serverFirstBodyAfterParseMs": round((received - parsed) * 1000, 2),
            "firstBodyBytes": len(resource.content),
            "serverPythonPeakBytes": peak,
            "warmMetadataMs": round(warm_ms, 2),
            "clientFirstReadableMs": None,
            "networkTransferredBytes": None,
            "clientCachePeakBytes": None,
        }
    finally:
        adapter.close()
        tracemalloc.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epub", type=Path, required=True)
    parser.add_argument("--epub-href")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="reader-streaming-benchmark-") as temporary:
        sample = Path(temporary) / "independent-chapters.txt"
        with sample.open("w", encoding="utf-8", newline="\n") as output:
            for chapter in range(1, 1001):
                output.write(f"第{chapter}章 独立流式验证\n")
                output.write(
                    "这是独立生成的测试文本，用于验证完整章节按需读取。\n" * 100
                )
        samples = [
            measure(arguments.epub, "epub", arguments.epub_href),
            measure(sample, "txt"),
        ]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(
            {
                "scope": "server adapter measurements; not client/network or physical-device acceptance",
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
