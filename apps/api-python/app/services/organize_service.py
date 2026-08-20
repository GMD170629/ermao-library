from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from html import unescape
from time import time_ns
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from sqlalchemy.orm import Session

from app.core.database_errors import is_database_busy_error
from app.core.time import now_timestamp_ms
from app.modules.metadata.application.commands import MetadataWriteTransaction
from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.infrastructure import external_cache as metadata_cache
from app.modules.metadata.infrastructure.short_writes import (
    metadata_short_write_session,
)
from app.modules.organize.infrastructure import review as organize_review
LOGGER = logging.getLogger(__name__)


def now() -> datetime:
    return datetime.now(UTC)


def has_table(db: Session, table: str) -> bool:
    return organize_review.has_table(db, table)


def parse_json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            first = next(
                (
                    str(
                        item.get("name", item) if isinstance(item, dict) else item
                    ).strip()
                    for item in value
                    if str(
                        item.get("name", item) if isinstance(item, dict) else item
                    ).strip()
                ),
                None,
            )
            if first:
                return first
    return None


def string_array(value: Any) -> list[str]:
    if isinstance(value, list):
        return [
            item
            for item in (
                str(item.get("name", item) if isinstance(item, dict) else item).strip()
                for item in value
            )
            if item
        ]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[,，;/]", value) if item.strip()]
    return []


def extract_year(value: Any) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", str(value or ""))
    return int(match.group(1)) if match else None


def normalize_key(value: Any) -> str:
    return re.sub(
        r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’]+", "", str(value or "").lower()
    ).strip()


def metadata_title_key(value: Any) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(
        r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\]+", "", normalized
    ).strip()


def metadata_title_exact_match(expected: Any, candidate: Any) -> bool:
    expected_key = metadata_title_key(expected)
    candidate_key = metadata_title_key(candidate)
    return bool(expected_key and candidate_key and expected_key == candidate_key)


def _metadata_title_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [title for item in value for title in _metadata_title_strings(item)]
    if isinstance(value, dict):
        return [
            title
            for key in ("v", "value", "title", "name", "name_cn", "alias")
            for title in _metadata_title_strings(value.get(key))
        ]
    return []


def metadata_candidate_title_values(candidate: dict[str, Any]) -> list[str]:
    """Return every provider-declared title, including cached Bangumi aliases."""

    values = [
        *_metadata_title_strings(candidate.get("title")),
        *_metadata_title_strings(candidate.get("titleAliases")),
    ]
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    for key in (
        "title",
        "name",
        "name_cn",
        "originalTitle",
        "original_title",
        "origin_title",
        "alt_title",
        "aliases",
        "aka",
    ):
        values.extend(_metadata_title_strings(raw.get(key)))
    infobox = raw.get("infobox") if isinstance(raw.get("infobox"), list) else []
    for entry in infobox:
        if not isinstance(entry, dict) or not re.search(
            r"别名|又名|中文名|简体中文|繁体中文|原名|日文名|英文名",
            str(entry.get("key") or ""),
            re.IGNORECASE,
        ):
            continue
        values.extend(_metadata_title_strings(entry.get("value")))
    return list(dict.fromkeys(value for value in values if metadata_title_key(value)))


def metadata_candidate_title_exact_match(
    expected: Any, candidate: dict[str, Any]
) -> bool:
    return any(
        metadata_title_exact_match(expected, value)
        for value in metadata_candidate_title_values(candidate)
    )


def metadata_title_needs_ai(value: Any) -> bool:
    title = str(value or "").strip()
    if len(title) < 2:
        return True
    if re.search(r"\.(epub|cbz|zip|pdf|txt|m4b|m4a|mp3)$", title, re.IGNORECASE):
        return True
    return bool(re.fullmatch(r"[0-9a-f]{16,}", title, re.IGNORECASE))


def contains_cjk(value: Any) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(value or "")))


def sort_candidates_for_title(
    candidates: list[dict[str, Any]], title: str | None
) -> list[dict[str, Any]]:
    indexed = list(enumerate(candidates))
    indexed.sort(
        key=lambda item: (
            0 if metadata_candidate_title_exact_match(title, item[1]) else 1,
            0 if contains_cjk(item[1].get("title")) else 1,
            item[0],
        )
    )
    return [item for _, item in indexed]


def first_exact_title_candidate(
    candidates: list[dict[str, Any]], title: str | None
) -> dict[str, Any] | None:
    return next(
        (
            candidate
            for candidate in candidates
            if metadata_candidate_title_exact_match(title, candidate)
        ),
        None,
    )


def metadata_context_for_work(
    db: Session, work_id: str
) -> dict[str, Any] | None:
    return organize_review.load_work_context(db, work_id)


def local_metadata_summary(context: dict[str, Any]) -> dict[str, Any]:
    work = context["work"]
    files = context["files"][:8]
    metadata = [
        parse_json_value(item.get("rawJson")) for item in context["metadata"][:4]
    ]
    return {
        "title": work.get("title"),
        "author": work.get("author"),
        "seriesName": work.get("seriesName"),
        "seriesIndex": work.get("seriesIndex"),
        "tags": parse_json_value(work.get("tags")) or [],
        "fileNames": [str(file.get("path") or "").rsplit("/", 1)[-1] for file in files],
        "parentPaths": sorted(
            {
                str(file.get("path") or "").rsplit("/", 1)[0]
                for file in files
                if "/" in str(file.get("path") or "")
            }
        ),
        "embeddedMetadata": metadata,
    }


def normalize_ai_confidence(value: Any) -> float:
    try:
        parsed = float(value if value is not None else 0.6)
    except (TypeError, ValueError):
        parsed = 0.6
    return min(0.74, max(0.0, parsed))


def suggestion_from_ai_item(item: dict[str, Any]) -> dict[str, Any] | None:
    field = item.get("field")
    if field not in {
        "title",
        "author",
        "description",
        "tags",
        "seriesName",
        "seriesIndex",
    }:
        return None
    value = item.get("value")
    if value is None or value == "" or value == []:
        return None
    return {
        "field": field,
        "suggestedValue": json_text(value)
        if isinstance(value, (dict, list, int, float, bool))
        else str(value),
        "source": "ai",
        "confidence": normalize_ai_confidence(item.get("confidence")),
        "reason": f"AI 识别：{string_value(item.get('reason')) or '根据本地元数据摘要推断'}",
        "status": "PENDING",
    }


def suggestion_from_external(
    field: str, value: Any, confidence: float, reason: str, source: str = "external"
) -> dict[str, Any] | None:
    if field not in {
        "title",
        "author",
        "description",
        "tags",
        "seriesName",
        "seriesIndex",
    }:
        return None
    if value is None or value == "" or value == []:
        return None
    return {
        "field": field,
        "suggestedValue": json_text(value)
        if isinstance(value, (dict, list, int, float, bool))
        else str(value),
        "source": source,
        "confidence": confidence,
        "reason": reason,
        "status": "PENDING",
    }


def douban_candidates(payload: Any, confidence: float) -> list[dict[str, Any]]:
    raw = payload if isinstance(payload, dict) else {}
    books = (
        raw.get("books")
        if isinstance(raw.get("books"), list)
        else raw.get("items")
        if isinstance(raw.get("items"), list)
        else raw.get("results")
        if isinstance(raw.get("results"), list)
        else raw.get("subjects")
        if isinstance(raw.get("subjects"), list)
        else raw.get("data")
        if isinstance(raw.get("data"), list)
        else payload
        if isinstance(payload, list)
        else [raw]
        if raw.get("title") or raw.get("id")
        else []
    )
    candidates = []
    for index, item in enumerate(books):
        if not isinstance(item, dict):
            continue
        tags = string_array(item.get("tags")) or string_array(item.get("tag"))
        candidates.append(
            {
                "id": str(
                    item.get("id")
                    or item.get("isbn13")
                    or item.get("isbn10")
                    or item.get("url")
                    or f"douban-{index}"
                ),
                "source": "douban",
                "title": first_string(item.get("title"), item.get("subtitle")),
                "author": first_string(item.get("author"), item.get("authors")),
                "description": first_string(
                    item.get("summary"), item.get("description")
                ),
                "tags": tags,
                "seriesName": first_string(
                    item.get("seriesName"), item.get("series"), item.get("series_name")
                ),
                "publisher": first_string(item.get("publisher")),
                "publishedAt": publication_datetime_or_none(
                    item.get("pubdate"), item.get("publishedAt")
                ),
                "isbn": first_string(
                    item.get("isbn13"), item.get("isbn10"), item.get("isbn")
                ),
                "coverUrl": first_url(
                    item.get("image"),
                    item.get("coverUrl"),
                    item.get("cover_url"),
                    (item.get("images") or {}).get("large")
                    if isinstance(item.get("images"), dict)
                    else None,
                ),
                "confidence": confidence,
                "raw": item,
            }
        )
    return [
        candidate
        for candidate in candidates
        if candidate.get("title")
        or candidate.get("author")
        or candidate.get("description")
    ]


def publication_datetime_or_none(*values: Any) -> str | None:
    value = first_string(*values)
    if not value:
        return None
    match = re.search(
        r"(?P<year>\d{4})(?:[-/.\u5e74](?P<month>\d{1,2}))?(?:[-/.\u6708](?P<day>\d{1,2}))?",
        value,
    )
    if match is None:
        return None
    try:
        parsed = datetime(
            int(match.group("year")),
            int(match.group("month") or 1),
            int(match.group("day") or 1),
            tzinfo=UTC,
        )
    except ValueError:
        return None
    return parsed.isoformat()


def first_url(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    return None


def douban_abstract_parts(value: Any) -> list[str]:
    text_value = first_string(value)
    return (
        [part.strip() for part in text_value.split("/") if part.strip()]
        if text_value
        else []
    )


def strip_html(value: str) -> str:
    cleaned = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</p\s*>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"[ \t\r\f\v]+", " ", unescape(cleaned)).strip()


def attrs_from_tag(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([:\w-]+)\s*=\s*(['\"])(.*?)\2", tag, re.DOTALL):
        attrs[match.group(1).lower()] = unescape(match.group(3)).strip()
    return attrs


def meta_content(html: str, property_name: str) -> str | None:
    for match in re.finditer(r"<meta\b[^>]*>", html, re.IGNORECASE):
        attrs = attrs_from_tag(match.group(0))
        if attrs.get("property") == property_name or attrs.get("name") == property_name:
            return attrs.get("content") or None
    return None


def parse_json_ld_book(html: str) -> dict[str, Any] | None:
    match = re.search(
        r"<script\s+type=['\"]application/ld\+json['\"][^>]*>([\s\S]*?)</script>",
        html,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        payload = json.loads(match.group(1).strip())
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def parse_douban_info_block(html: str) -> dict[str, str]:
    match = re.search(
        r"<div\s+id=['\"]info['\"][^>]*>([\s\S]*?)</div>", html, re.IGNORECASE
    )
    if not match:
        return {}
    text_value = strip_html(match.group(1))
    text_value = re.sub(
        r"\s*(作者|出版社|出版年|ISBN|页数|定价|装帧|副标题|原作名|译者|丛书):\s*",
        r"\n\1: ",
        text_value,
    )
    fields: dict[str, str] = {}
    for line in [item.strip() for item in text_value.split("\n") if item.strip()]:
        field_match = re.match(
            r"^(作者|出版社|出版年|ISBN|页数|定价|装帧|副标题|原作名|译者|丛书):\s*(.+)$",
            line,
        )
        if field_match:
            fields[field_match.group(1)] = field_match.group(2).strip()
    return fields


def parse_douban_intro(html: str) -> str | None:
    heading = re.search(r"<h2>\s*<span>\s*内容简介\s*</span>", html, re.IGNORECASE)
    if not heading:
        return meta_content(html, "og:description")
    rest = html[heading.end() :]
    intro_match = re.search(
        r"<div\s+class=['\"]intro['\"][^>]*>([\s\S]*?)</div>", rest, re.IGNORECASE
    )
    if not intro_match:
        return meta_content(html, "og:description")
    return re.sub(r"\n+", "\n", strip_html(intro_match.group(1))).strip()


def parse_douban_subject_html(
    html: str, fallback: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    fallback = fallback or {}
    json_ld = parse_json_ld_book(html) or {}
    info = parse_douban_info_block(html)
    author_value = json_ld.get("author")
    authors = (
        [
            first_string(item.get("name"))
            for item in author_value
            if isinstance(item, dict)
        ]
        if isinstance(author_value, list)
        else string_array(author_value)
    )
    authors = [item for item in authors if item]
    url = first_string(
        json_ld.get("url"),
        json_ld.get("sameAs"),
        meta_content(html, "og:url"),
        fallback.get("id"),
    )
    subject_match = re.search(r"/subject/(\d+)/", url or "")
    title = first_string(
        json_ld.get("name"), meta_content(html, "og:title"), fallback.get("title")
    )
    author = (authors[0] if authors else None) or first_string(
        info.get("作者"), fallback.get("author")
    )
    description = first_string(parse_douban_intro(html), fallback.get("description"))
    pubdate = first_string(
        info.get("出版年"),
        (fallback.get("raw") or {}).get("pubdate")
        if isinstance(fallback.get("raw"), dict)
        else None,
    )
    publisher = first_string(
        info.get("出版社"),
        (fallback.get("raw") or {}).get("publisher")
        if isinstance(fallback.get("raw"), dict)
        else None,
    )
    series_name = first_string(
        info.get("丛书"),
        fallback.get("seriesName"),
        (fallback.get("raw") or {}).get("seriesName")
        if isinstance(fallback.get("raw"), dict)
        else None,
    )
    cover_url = first_url(meta_content(html, "og:image"), fallback.get("coverUrl"))
    isbn = first_string(
        json_ld.get("isbn"), meta_content(html, "book:isbn"), info.get("ISBN")
    )
    if not title and not author and not description:
        return None
    candidate_id = (
        subject_match.group(1)
        if subject_match
        else str(fallback.get("id") or f"douban-{normalize_key(url or title)}")
    )
    return {
        "id": candidate_id,
        "source": "douban",
        "title": title,
        "author": author,
        "description": description,
        "tags": fallback.get("tags") if isinstance(fallback.get("tags"), list) else [],
        "seriesName": series_name,
        "coverUrl": cover_url,
        "confidence": float(fallback.get("confidence") or 0.78),
        "raw": {
            **(fallback.get("raw") if isinstance(fallback.get("raw"), dict) else {}),
            "id": candidate_id,
            "url": url,
            "isbn": isbn,
            "pubdate": pubdate,
            "publisher": publisher,
            "seriesName": series_name,
            "coverUrl": cover_url,
        },
    }


def parse_douban_search_html(html: str, confidence: float) -> list[dict[str, Any]]:
    match = re.search(r"window\.__DATA__\s*=\s*(\{[\s\S]*?\})\s*;", html)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    items = (
        payload.get("items")
        if isinstance(payload, dict) and isinstance(payload.get("items"), list)
        else []
    )
    candidates: list[dict[str, Any]] = []
    for item in items:
        if (
            not isinstance(item, dict)
            or item.get("tpl_name") != "search_subject"
            or "/subject/" not in str(item.get("url") or "")
        ):
            continue
        abstract = first_string(item.get("abstract"))
        abstract_parts = douban_abstract_parts(abstract)
        subject_match = re.search(r"/subject/(\d+)/", str(item.get("url") or ""))
        cover_url = first_url(item.get("cover_url"))
        candidates.append(
            {
                "id": str(
                    item.get("id")
                    or (
                        subject_match.group(1)
                        if subject_match
                        else f"douban-{normalize_key(item.get('title'))}"
                    )
                ),
                "source": "douban",
                "title": first_string(item.get("title")),
                "author": abstract_parts[0] if abstract_parts else None,
                "description": first_string(item.get("abstract_2")),
                "tags": [],
                "coverUrl": cover_url,
                "confidence": confidence,
                "raw": {
                    **item,
                    "url": first_string(item.get("url")),
                    "coverUrl": cover_url,
                },
            }
        )
    return [
        candidate
        for candidate in candidates
        if candidate.get("title") or candidate.get("author")
    ]


def normalize_douban_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    return {
        **candidate,
        "seriesName": first_string(
            candidate.get("seriesName"),
            raw.get("seriesName"),
            raw.get("series"),
            raw.get("series_name"),
        ),
        "publisher": first_string(candidate.get("publisher"), raw.get("publisher")),
        "publishedAt": publication_datetime_or_none(
            candidate.get("publishedAt"), raw.get("pubdate")
        ),
        "isbn": first_string(
            candidate.get("isbn"), raw.get("isbn"), raw.get("isbn13"), raw.get("isbn10")
        ),
        "coverUrl": first_url(
            candidate.get("coverUrl"),
            raw.get("coverUrl"),
            raw.get("cover_url"),
            raw.get("image"),
        ),
    }


def douban_crawler_headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "User-Agent": string_value(config.get("userAgent"))
        or "ShukuStarship/0.1 (+https://github.com/GMD170629/ermao-library)",
        "Referer": "https://book.douban.com",
    }


def douban_base_url(config: dict[str, Any]) -> str:
    return string_value(config.get("baseUrl")).rstrip("/") or "https://book.douban.com"


def fetch_text(
    url: str,
    headers: dict[str, str],
    *,
    provider_id: str | None = None,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> str:
    if provider_id is not None and automatic_request_gate is not None:
        automatic_request_gate.wait(provider_id)
    request = UrlRequest(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_douban_subject(
    base_url: str,
    subject_url: str,
    headers: dict[str, str],
    fallback: dict[str, Any],
    *,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> dict[str, Any] | None:
    url = (
        subject_url
        if subject_url.startswith(("http://", "https://"))
        else urljoin(f"{base_url}/", subject_url.lstrip("/"))
    )
    return parse_douban_subject_html(
        fetch_text(
            url,
            headers,
            provider_id="douban",
            automatic_request_gate=automatic_request_gate,
        ),
        fallback,
    )


def run_douban_crawler_provider(
    context: dict[str, Any],
    config: dict[str, Any],
    force: bool = True,
    query: str | None = None,
    match_title: str | None = None,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> dict[str, Any]:
    base_url = douban_base_url(config)
    headers = douban_crawler_headers(config)
    volume = next(iter(context["volumes"]), {})
    isbn = first_string(volume.get("isbn"), volume.get("identifier"))
    title = first_string(context["work"].get("title")) or ""
    author = first_string(context["work"].get("author")) or ""
    query_text = query or isbn or " ".join(part for part in [title, author] if part)
    confidence = 0.9 if isbn else 0.8 if author else 0.7
    if not query_text:
        return {
            "provider": "douban",
            "enabled": True,
            "added": 0,
            "cacheHit": False,
            "message": "豆瓣查询文本为空",
            "suggestions": [],
        }

    subject_match = re.search(r"(?:book\.douban\.com/subject/)?(\d{4,})", query_text)
    candidates: list[dict[str, Any]] = []
    candidate: dict[str, Any] | None = None
    if subject_match and "/subject/" in query_text:
        candidate = fetch_douban_subject(
            base_url,
            f"/subject/{subject_match.group(1)}/",
            headers,
            {"confidence": confidence},
            automatic_request_gate=automatic_request_gate,
        )
        candidates = [normalize_douban_candidate(candidate)] if candidate else []
    else:
        search_html = fetch_text(
            f"{base_url}/subject_search?{urlencode({'search_text': query_text})}",
            headers,
            provider_id="douban",
            automatic_request_gate=automatic_request_gate,
        )
        candidates = sort_candidates_for_title(
            [
                normalize_douban_candidate(candidate)
                for candidate in parse_douban_search_html(search_html, confidence)
            ],
            match_title or query_text,
        )
        selected = (
            first_exact_title_candidate(candidates, match_title)
            if match_title
            else (candidates[0] if candidates else None)
        )
        subject_url = (
            first_string((selected.get("raw") or {}).get("url"))
            if isinstance(selected, dict) and isinstance(selected.get("raw"), dict)
            else None
        )
        try:
            subject_candidate = (
                fetch_douban_subject(
                    base_url,
                    subject_url,
                    headers,
                    selected,
                    automatic_request_gate=automatic_request_gate,
                )
                if selected and subject_url
                else None
            )
        # A failed optional detail fetch must not discard the valid search result.
        except Exception:
            subject_candidate = None
        candidate = subject_candidate or selected
        if candidate:
            normalized_first = normalize_douban_candidate(candidate)
            candidates = [
                normalized_first,
                *[
                    item
                    for item in candidates
                    if item.get("id") != normalized_first.get("id")
                ],
            ]
    if not candidate:
        message = (
            "豆瓣未找到标题完全匹配的图书"
            if match_title and candidates
            else "豆瓣未找到匹配图书"
        )
        return {
            "provider": "douban",
            "enabled": True,
            "added": 0,
            "cacheHit": False,
            "message": message,
            "suggestions": [],
            "candidates": candidates,
        }
    normalized_candidate = normalize_douban_candidate(candidate)
    if match_title and not metadata_candidate_title_exact_match(
        match_title, normalized_candidate
    ):
        return {
            "provider": "douban",
            "enabled": True,
            "added": 0,
            "cacheHit": False,
            "message": "豆瓣未找到标题完全匹配的图书",
            "suggestions": [],
            "candidates": candidates or [normalized_candidate],
        }
    suggestions = douban_book_suggestions(
        normalized_candidate, float(candidate.get("confidence") or confidence)
    )
    message = None if suggestions else "豆瓣未找到可用候选字段"
    return {
        "provider": "douban",
        "enabled": True,
        "added": 0,
        "cacheHit": False,
        "message": message,
        "suggestions": suggestions,
        "candidates": candidates or [normalized_candidate],
    }


def douban_book_suggestions(payload: Any, confidence: float) -> list[dict[str, Any]]:
    book = next(iter(douban_candidates(payload, confidence)), None)
    if not book:
        return []
    raw = [
        suggestion_from_external(
            "title",
            book.get("title"),
            confidence,
            "外部数据源 · 豆瓣：匹配图书标题",
            "douban",
        ),
        suggestion_from_external(
            "author",
            book.get("author"),
            confidence,
            "外部数据源 · 豆瓣：匹配作者",
            "douban",
        ),
        suggestion_from_external(
            "description",
            book.get("description"),
            min(confidence, 0.82),
            "外部数据源 · 豆瓣：补全简介",
            "douban",
        ),
        suggestion_from_external(
            "tags",
            book.get("tags"),
            min(confidence, 0.76),
            "外部数据源 · 豆瓣：补全标签",
            "douban",
        ),
        suggestion_from_external(
            "seriesName",
            book.get("seriesName"),
            min(confidence, 0.82),
            "外部数据源 · 豆瓣：补全丛书",
            "douban",
        ),
    ]
    return [item for item in raw if item]


def bangumi_candidates(payload: Any, confidence: float) -> list[dict[str, Any]]:
    raw = payload if isinstance(payload, dict) else {}
    data = (
        raw.get("data")
        if isinstance(raw.get("data"), list)
        else raw.get("list")
        if isinstance(raw.get("list"), list)
        else raw.get("results")
        if isinstance(raw.get("results"), list)
        else payload
        if isinstance(payload, list)
        else [raw]
        if raw.get("name") or raw.get("name_cn") or raw.get("id")
        else []
    )
    candidates = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        tags = (
            [
                str(tag if isinstance(tag, str) else tag.get("name", "")).strip()
                for tag in item.get("tags", [])
                if str(tag if isinstance(tag, str) else tag.get("name", "")).strip()
            ]
            if isinstance(item.get("tags"), list)
            else []
        )
        infobox = item.get("infobox") if isinstance(item.get("infobox"), list) else []
        authors = []
        title_aliases = [
            *_metadata_title_strings(item.get("name")),
            *_metadata_title_strings(item.get("name_cn")),
        ]
        for entry in infobox:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key") or "")
            value = entry.get("value")
            if re.search(r"作者|作画|原作", key):
                authors.extend(string_array(value))
            if re.search(
                r"别名|又名|中文名|简体中文|繁体中文|原名|日文名|英文名",
                key,
                re.IGNORECASE,
            ):
                title_aliases.extend(_metadata_title_strings(value))
        images = item.get("images") if isinstance(item.get("images"), dict) else {}
        candidates.append(
            {
                "id": str(item.get("id") or item.get("url") or f"bangumi-{index}"),
                "source": "bangumi",
                "title": first_string(item.get("name_cn"), item.get("name")),
                "titleAliases": list(
                    dict.fromkeys(
                        alias for alias in title_aliases if metadata_title_key(alias)
                    )
                ),
                "author": authors[0] if authors else None,
                "description": first_string(item.get("summary")),
                "tags": tags[:8],
                "seriesName": first_string(item.get("name_cn"), item.get("name")),
                "coverUrl": first_url(
                    images.get("large"),
                    images.get("common"),
                    images.get("medium"),
                    images.get("small"),
                    item.get("image"),
                ),
                "confidence": confidence,
                "raw": item,
            }
        )
    return [
        candidate
        for candidate in candidates
        if candidate.get("title") or candidate.get("description")
    ]


def bangumi_candidate_suggestions(
    subject: dict[str, Any] | None, confidence: float
) -> list[dict[str, Any]]:
    if not subject:
        return []
    raw = [
        suggestion_from_external(
            "title",
            subject.get("title"),
            confidence,
            "外部数据源 · Bangumi：匹配条目",
            "bangumi",
        ),
        suggestion_from_external(
            "author",
            subject.get("author"),
            min(confidence, 0.78),
            "外部数据源 · Bangumi：补全作者/原作",
            "bangumi",
        ),
        suggestion_from_external(
            "description",
            subject.get("description"),
            min(confidence, 0.8),
            "外部数据源 · Bangumi：补全简介",
            "bangumi",
        ),
        suggestion_from_external(
            "tags",
            subject.get("tags"),
            min(confidence, 0.72),
            "外部数据源 · Bangumi：补全标签",
            "bangumi",
        ),
        suggestion_from_external(
            "seriesName",
            subject.get("seriesName"),
            min(confidence, 0.82),
            "外部数据源 · Bangumi：补全系列名",
            "bangumi",
        ),
    ]
    return [item for item in raw if item]


def bangumi_subject_suggestions(
    payload: Any, confidence: float
) -> list[dict[str, Any]]:
    return bangumi_candidate_suggestions(
        next(iter(bangumi_candidates(payload, confidence)), None), confidence
    )


def ai_suggestions_from_payload(payload: Any) -> list[dict[str, Any]]:
    raw = payload if isinstance(payload, dict) else {}
    choices = raw.get("choices")
    message = (
        choices[0].get("message")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict)
        else None
    )
    content = message.get("content") if isinstance(message, dict) else None
    parsed = (
        parse_json_value(
            re.sub(r"^```json\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        )
        if isinstance(content, str)
        else raw
    )
    suggestions = parsed.get("suggestions") if isinstance(parsed, dict) else []
    return [
        suggestion
        for item in suggestions
        if isinstance(item, dict) and (suggestion := suggestion_from_ai_item(item))
    ]


def run_ai_metadata_provider(
    context: dict[str, Any], config: dict[str, Any], force: bool = True
) -> dict[str, Any]:
    base_url = string_value(config.get("baseUrl")).rstrip("/")
    api_key = string_value(config.get("apiKey"))
    model = string_value(config.get("model"))
    if not base_url or not api_key or not model:
        return {
            "provider": "ai",
            "enabled": False,
            "added": 0,
            "cacheHit": False,
            "message": "AI 服务地址、模型或 API Key 未配置",
            "suggestions": [],
        }
    summary = local_metadata_summary(context)
    body = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": '你是图书元数据整理助手。只返回 JSON，格式为 {"suggestions":[{"field":"title|author|description|tags|seriesName|seriesIndex","value":...,"confidence":0-1,"reason":"..."}]}。不要编造不确定信息。',
            },
            {"role": "user", "content": json_text(summary)},
        ],
    }
    request = UrlRequest(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "provider": "ai",
        "enabled": True,
        "added": 0,
        "cacheHit": False,
        "suggestions": ai_suggestions_from_payload(payload),
    }


def run_bangumi_metadata_provider(
    context: dict[str, Any],
    config: dict[str, Any],
    force: bool = True,
    query: str | None = None,
    match_title: str | None = None,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> dict[str, Any]:
    user_agent = (
        string_value(config.get("userAgent"))
        or "ShukuStarship/0.1 (https://github.com/GMD170629/ermao-library)"
    )
    if not user_agent:
        return {
            "provider": "bangumi",
            "enabled": False,
            "added": 0,
            "cacheHit": False,
            "message": "Bangumi User-Agent 未配置",
            "suggestions": [],
        }
    base_url = string_value(config.get("baseUrl")).rstrip("/") or "https://api.bgm.tv"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    access_token = string_value(config.get("accessToken"))
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    title = (
        query
        or first_string(context["work"].get("seriesName"), context["work"].get("title"))
        or ""
    )
    if not title:
        return {
            "provider": "bangumi",
            "enabled": True,
            "added": 0,
            "cacheHit": False,
            "message": "Bangumi 查询文本为空",
            "suggestions": [],
        }
    request = UrlRequest(
        f"{base_url}/v0/search/subjects",
        data=json.dumps(
            {"keyword": title, "sort": "match", "filter": {"type": [1]}},
            ensure_ascii=False,
        ).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    if automatic_request_gate is not None:
        automatic_request_gate.wait("bangumi")
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    candidates = sort_candidates_for_title(
        bangumi_candidates(payload, 0.82), match_title or title
    )
    subject = (
        first_exact_title_candidate(candidates, match_title)
        if match_title
        else (candidates[0] if candidates else None)
    )
    suggestions = bangumi_candidate_suggestions(subject, 0.82)
    if match_title and not subject:
        message = "Bangumi 未找到标题完全匹配的条目"
    else:
        message = None if suggestions else "Bangumi 未找到匹配条目"
    return {
        "provider": "bangumi",
        "enabled": True,
        "added": 0,
        "cacheHit": False,
        "message": message,
        "suggestions": suggestions,
        "candidates": candidates,
    }


def run_douban_metadata_provider(
    context: dict[str, Any],
    config: dict[str, Any],
    force: bool = True,
    query: str | None = None,
    match_title: str | None = None,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> dict[str, Any]:
    return run_douban_crawler_provider(
        context,
        config,
        force=force,
        query=query,
        match_title=match_title,
        automatic_request_gate=automatic_request_gate,
    )


def external_metadata_cache_get(
    db: Session, provider: str, query_key: str
) -> dict[str, Any] | None:
    raw_json = metadata_cache.get_cached_raw_json(
        db, provider=provider, query_key=query_key
    )
    if raw_json is None:
        return None
    parsed = parse_json_value(raw_json)
    return (
        parsed
        if isinstance(parsed, dict) and external_metadata_result_cacheable(parsed)
        else None
    )


def external_metadata_result_cacheable(result: dict[str, Any]) -> bool:
    if result.get("enabled") is False or result.get("error"):
        return False
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return False
    useful_fields = (
        "title",
        "author",
        "description",
        "tags",
        "seriesName",
        "seriesIndex",
        "coverUrl",
    )
    return any(
        isinstance(candidate, dict)
        and any(candidate.get(field) not in (None, "", []) for field in useful_fields)
        for candidate in candidates
    )


def external_metadata_cache_put(
    db: Session,
    provider: str,
    query_key: str,
    result: dict[str, Any],
    *,
    cache_ready: bool | None = None,
) -> None:
    if (
        not query_key
        or not external_metadata_result_cacheable(result)
    ):
        return
    if cache_ready is None:
        cache_ready = metadata_cache.external_metadata_cache_ready(db)
    if not cache_ready:
        return
    candidates = result["candidates"]
    timestamp = now_timestamp_ms()
    payload = json_text(
        {
            "candidates": candidates,
            "suggestions": result.get("suggestions")
            if isinstance(result.get("suggestions"), list)
            else [],
            "message": result.get("message"),
        }
    )
    entry_id = f"py_{time_ns()}"
    expires_at_ms = timestamp + 24 * 60 * 60 * 1000
    prepared = metadata_cache.prepare_cache_entry_write(
        entry_id=entry_id,
        provider=provider,
        query_key=query_key,
        raw_json=payload,
        expires_at_ms=expires_at_ms,
        now_ms=timestamp,
    )
    try:
        with metadata_short_write_session(db) as writer:
            with MetadataWriteTransaction(writer):
                metadata_cache.write_prepared_cache_entry(writer, prepared)
    except Exception as exc:
        if not is_database_busy_error(exc):
            raise
        LOGGER.info(
            "metadata_cache_write outcome=deferred reason=database_busy provider=%s",
            provider,
        )


def metadata_search_candidates(
    db: Session,
    context: dict[str, Any],
    source: str,
    query: str | None = None,
    *,
    config: dict[str, Any],
    force: bool = False,
    use_cache: bool = True,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> dict[str, Any]:
    search_text = query or first_string(context["work"].get("title")) or ""
    query_key = metadata_title_key(search_text)
    cache_eligible = source in {"bangumi", "douban", "ai"}
    cache_ready = (
        metadata_cache.external_metadata_cache_ready(db) if cache_eligible else False
    )
    cached = (
        external_metadata_cache_get(db, source, query_key)
        if cache_eligible and cache_ready and use_cache
        else None
    )
    if cached is not None:
        return {
            "provider": source,
            "enabled": True,
            "added": 0,
            "cacheHit": True,
            **cached,
        }
    db.close()
    if source == "bangumi":
        if automatic_request_gate is None:
            result = run_bangumi_metadata_provider(
                context, config, force=force, query=query
            )
        else:
            result = run_bangumi_metadata_provider(
                context,
                config,
                force=force,
                query=query,
                automatic_request_gate=automatic_request_gate,
            )
    elif source == "douban":
        if automatic_request_gate is None:
            result = run_douban_metadata_provider(
                context, config, force=force, query=query
            )
        else:
            result = run_douban_metadata_provider(
                context,
                config,
                force=force,
                query=query,
                automatic_request_gate=automatic_request_gate,
            )
    else:
        ai_result = run_ai_metadata_provider(context, config, force=force)
        fields = {
            item["field"]: parse_json_value(item.get("suggestedValue"))
            for item in ai_result.get("suggestions") or []
        }
        candidate = {
            "id": "ai-suggestion",
            "source": "ai",
            "title": fields.get("title"),
            "author": fields.get("author"),
            "description": fields.get("description"),
            "tags": fields.get("tags") if isinstance(fields.get("tags"), list) else [],
            "seriesName": fields.get("seriesName"),
            "seriesIndex": fields.get("seriesIndex"),
            "confidence": max(
                [
                    float(item.get("confidence") or 0)
                    for item in ai_result.get("suggestions") or []
                ]
                or [0.0]
            ),
            "raw": {"suggestions": ai_result.get("suggestions") or []},
        }
        result = {
            **ai_result,
            "candidates": [candidate] if ai_result.get("suggestions") else [],
        }
    if source in {"bangumi", "douban"}:
        result = {
            **result,
            "candidates": sort_candidates_for_title(
                result.get("candidates") or [],
                query or first_string(context["work"].get("title")),
            ),
        }
    if cache_eligible and result.get("enabled"):
        external_metadata_cache_put(
            db,
            source,
            query_key,
            result,
            cache_ready=cache_ready,
        )
    return result
