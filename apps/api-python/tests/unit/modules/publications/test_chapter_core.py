"""All language bindings consume this corpus through the actual C ABI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.publications.infrastructure.chapter_core import (
    ChapterCore,
    MobiChapterNode,
    XmlChapterEvent,
)

_FIXTURE = (
    Path(__file__).resolve().parents[6]
    / "packages/reader-contracts/fixtures/chapters-v1/manifest.json"
)
_CASES = json.loads(_FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _CASES, ids=[case["id"] for case in _CASES])
def test_shared_chapter_fixture(case) -> None:
    core = ChapterCore.load()
    if case["format"] == "txt":
        result = core.parse_txt(case["input"])
        assert result.text.decode() == case["expected"]["normalizedText"]
    elif case["format"] == "mobi":
        result = core.from_mobi(
            tuple(
                MobiChapterNode(
                    parent_index=node["parentIndex"],
                    title=node["title"],
                    target_href=node.get("targetHref"),
                )
                for node in case["nodes"]
            )
        )
    else:
        result = core.parse_xml(
            {"epub-nav": 1, "epub-ncx": 2, "fb2": 3}[case["format"]],
            tuple(
                XmlChapterEvent(
                    kind={"start": 1, "text": 2, "end": 3}[event["kind"]],
                    name=event.get("name", ""),
                    text=event.get("text", ""),
                    attributes=tuple(
                        (attr["name"], attr["value"])
                        for attr in event.get("attributes", [])
                    ),
                    target_href=event.get("targetHref"),
                )
                for event in case["events"]
            ),
        )
    actual = [
        {
            "index": entry.index,
            "parentIndex": entry.parent_index,
            "key": entry.key,
            "navigable": entry.href is not None,
            "title": entry.title,
            **({"href": entry.href} if entry.href is not None else {}),
            "sourceStart": entry.source_start,
            "sourceEnd": entry.source_end,
            "contentStart": entry.content_start,
        }
        for entry in result.entries
    ]
    assert actual == case["expected"]["entries"]
