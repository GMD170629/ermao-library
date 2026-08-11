from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

FacetKind = Literal["AUTHOR", "TAG", "SERIES"]

FACET_KINDS = frozenset({"AUTHOR", "TAG", "SERIES"})
CURRENT_FACET_INDEX_VERSION = 1


@dataclass(frozen=True, slots=True)
class WorkFacetValue:
    kind: FacetKind
    name: str
    normalized_name: str
    sort_order: int


def normalize_facet_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(
        r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\]+",
        "",
        normalized,
    ).strip()


def unique_facet_names(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = re.sub(r"\s+", " ", value).strip()
        normalized = normalize_facet_name(name)
        if not name or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(name)
    return tuple(result)


def split_author_names(value: str | None) -> tuple[str, ...]:
    text_value = str(value or "").strip()
    if not text_value or text_value == "未知作者":
        return ()
    return unique_facet_names(
        re.split(
            r"\s*(?:,|，|;|；|、|/|&|\band\b)\s*",
            text_value,
            flags=re.IGNORECASE,
        )
    )


def build_work_facet_values(
    *,
    author: str | None,
    tags: tuple[str, ...],
    series_name: str | None,
) -> tuple[WorkFacetValue, ...]:
    values_by_kind: tuple[tuple[FacetKind, tuple[str, ...]], ...] = (
        ("AUTHOR", split_author_names(author)),
        ("TAG", unique_facet_names(tags)),
        ("SERIES", unique_facet_names((str(series_name or ""),))),
    )
    return tuple(
        WorkFacetValue(
            kind=kind,
            name=name,
            normalized_name=normalize_facet_name(name),
            sort_order=sort_order,
        )
        for kind, names in values_by_kind
        for sort_order, name in enumerate(names)
    )
