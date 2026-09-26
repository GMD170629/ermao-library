"""Bounded official bibliographic APIs; no ORM, HTML crawl or implicit writes."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request

from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.domain.recognition import normalize_isbn
from app.modules.metadata.infrastructure.http import urlopen

_MAX_RESPONSE = 2 * 1024 * 1024


def _json(url: str, provider: str, gate: AutomaticMetadataRequestGate | None, headers: dict[str, str]) -> dict[str, Any] | None:
    if gate:
        gate.wait(provider)
    try:
        with urlopen(Request(url, headers=headers), timeout=20) as response:
            content = response.read(_MAX_RESPONSE + 1)
    except HTTPError as error:
        if error.code == 404:
            return None  # A missing catalog entry is an ordinary no-result outcome.
        raise
    if len(content) > _MAX_RESPONSE:
        raise ValueError("PROVIDER_RESPONSE_TOO_LARGE")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise TypeError("INVALID_PROVIDER_RESPONSE")
    return parsed


def _text(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("value")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _strings(value: object) -> list[str]:
    return [item.strip() for item in value[:10] if isinstance(item, str) and item.strip()] if isinstance(value, list) else []


def _result(provider: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    return {"provider": provider, "enabled": True, "candidates": candidates[:10], "suggestions": [], "added": 0, "cacheHit": False}


def _edition_isbn_scope(title: object, physical_format: object = None) -> str:
    return "SET" if re.search(r"套装|套裝|全套|box\s*set|complete\s*(?:collection|set)|multi.?volume", str(title or "") + " " + str(physical_format or ""), re.IGNORECASE) else "EDITION"


def google_candidate(item: dict[str, Any]) -> dict[str, Any] | None:
    info = item.get("volumeInfo")
    if not item.get("id") or not isinstance(info, dict) or not _text(info.get("title")):
        return None
    authors = _strings(info.get("authors"))
    identifiers = info.get("industryIdentifiers") or []
    isbn = next((normalize_isbn(str(value.get("identifier") or "")) for value in identifiers
                 if isinstance(value, dict) and value.get("type") in {"ISBN_13", "ISBN_10"}
                 and normalize_isbn(str(value.get("identifier") or ""))), None)
    images = info.get("imageLinks") or {}
    title = str(info["title"])
    # A Google volume has edition-specific publication facts. A possible set
    # remains explicitly SET; the target still needs its own edition evidence.
    scope = "SET" if re.search(r"套装|套裝|全套|box\s*set|complete\s*(?:collection|set)", title, re.IGNORECASE) else "EDITION"
    return {"id": str(item["id"]), "source": "google-books", "title": title,
        "authors": authors, "author": " / ".join(authors) or None,
        "description": re.sub(r"<[^>]+>", "", _text(info.get("description")) or "") or None,
        "isbn": isbn, "isbnScope": scope if isbn else "UNKNOWN", "matchLevel": "EDITION",
        "publisher": _text(info.get("publisher")), "publishedAt": _text(info.get("publishedDate")),
        "language": _text(info.get("language")), "coverUrl": _text(images.get("thumbnail") or images.get("smallThumbnail")),
        "categories": _strings(info.get("categories")), "tags": [],
        "sourceUrl": "https://books.google.com/books?id=" + quote(str(item["id"]), safe="")}


def search_google(context: dict[str, Any], config: dict[str, Any], query: str,
                  gate: AutomaticMetadataRequestGate | None) -> dict[str, Any]:
    key = str(config.get("apiKey") or "").strip()
    if not key:
        return {**_result("google-books", []), "error": "CONFIG_REQUIRED", "message": "API Key required / 请配置 API Key"}
    headers = {"Accept": "application/json", "User-Agent": "ErmaoLibrary/1.0"}
    base = "https://www.googleapis.com/books/v1/volumes"
    direct = re.fullmatch(r"(?:google-books:|id:)([A-Za-z0-9_-]{1,100})", query)
    if direct:
        payload = _json(base + "/" + direct.group(1) + "?" + urlencode({"key": key}), "google-books", gate, headers)
        item = google_candidate(payload) if payload else None
        return _result("google-books", [item] if item else [])
    isbn = normalize_isbn(query)
    book = context.get("book") or {}
    author = str(book.get("author") or "").strip()
    search = "isbn:" + isbn if isbn else query
    if not isbn and author and query.endswith(" " + author):
        search = 'intitle:"' + query[: -len(author)].strip().replace('"', '') + '" inauthor:"' + author.replace('"', '') + '"'
    payload = _json(base + "?" + urlencode({"q": search, "maxResults": 10, "printType": "books", "key": key}), "google-books", gate, headers) or {}
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise TypeError("INVALID_PROVIDER_RESPONSE")
    candidates = [value for item in items[:10] if isinstance(item, dict) and (value := google_candidate(item)) is not None]
    return _result("google-books", candidates)


def search_open_library(context: dict[str, Any], config: dict[str, Any], query: str,
                        gate: AutomaticMetadataRequestGate | None) -> dict[str, Any]:
    identity = context.get("identity") or {}
    if identity.get("execution") != "MANUAL" or not identity.get("targetId") or not context.get("explicitManualQuery"):
        return {**_result("open-library", []), "enabled": False, "error": "MANUAL_SINGLE_TARGET_REQUIRED"}
    headers = {"Accept": "application/json", "User-Agent": str(config["userAgent"])}
    base = "https://openlibrary.org"
    isbn = normalize_isbn(query)
    if isbn:
        bibkey = "ISBN:" + isbn
        payload = _json(base + "/api/books?" + urlencode({"bibkeys": bibkey, "format": "json", "jscmd": "data"}), "open-library", gate, headers) or {}
        data = payload.get(bibkey)
        if not isinstance(data, dict):
            return _result("open-library", [])
        key = str(data.get("key") or "")
        if not re.fullmatch(r"/books/OL[0-9]+M", key):
            return _result("open-library", [])
        # This endpoint returns a selected Edition, not a search Work's ISBN bag.
        authors = [str(value["name"]) for value in data.get("authors", [])[:10] if isinstance(value, dict) and value.get("name")]
        publishers = [str(value["name"]) for value in data.get("publishers", [])[:5] if isinstance(value, dict) and value.get("name")]
        identifiers = data.get("identifiers") or {}
        observed = next((normalized for value in [*identifiers.get("isbn_13", []), *identifiers.get("isbn_10", [])] if (normalized := normalize_isbn(str(value)))), None)
        return _result("open-library", [{"id": key, "source": "open-library", "title": _text(data.get("title")),
            "author": " / ".join(authors) or None, "authors": authors, "matchLevel": "EDITION",
            "isbn": observed, "isbnScope": _edition_isbn_scope(data.get("title")) if observed else "UNKNOWN",
            "publisher": " / ".join(publishers) or None, "publishedAt": _text(data.get("publish_date")),
            "coverUrl": (data.get("cover") or {}).get("large"), "sourceUrl": base + key}])
    direct = re.fullmatch(r"(?:open-library:)?/?(books|works)/(OL[0-9]+[MW])", query)
    if direct:
        path = "/" + direct.group(1) + "/" + direct.group(2)
        data = _json(base + path + ".json", "open-library", gate, headers)
        if not data:
            return _result("open-library", [])
        authors = []
        for ref in (data.get("authors") or [])[:2]:
            ref = ref.get("author", ref) if isinstance(ref, dict) else {}
            author_key = ref.get("key", "")
            if re.fullmatch(r"/authors/OL[0-9]+A", author_key):
                person = _json(base + author_key + ".json", "open-library", gate, headers) or {}
                if person.get("name"):
                    authors.append(str(person["name"]))
        edition = direct.group(1) == "books"
        isbn = next((normalized for value in [*data.get("isbn_13", []), *data.get("isbn_10", [])] if (normalized := normalize_isbn(str(value)))), None) if edition else None
        covers = data.get("covers") or []
        return _result("open-library", [{"id": path, "source": "open-library", "title": _text(data.get("title")),
            "authors": authors, "author": " / ".join(authors) or None, "description": _text(data.get("description")),
            "matchLevel": "EDITION" if edition else "WORK", "isbn": isbn, "isbnScope": _edition_isbn_scope(data.get("title"), data.get("physical_format")) if isbn else "UNKNOWN",
            "publisher": " / ".join(_strings(data.get("publishers"))) if edition else None,
            "publishedAt": _text(data.get("publish_date")) if edition else None,
            "language": " / ".join(str(item.get("key", "")).removeprefix("/languages/") for item in data.get("languages", []) if isinstance(item, dict)) if edition else None,
            "coverUrl": f"https://covers.openlibrary.org/b/id/{covers[0]}-L.jpg" if covers and isinstance(covers[0], int) and covers[0] > 0 else None,
            "sourceUrl": base + path}])
    payload = _json(base + "/search.json?" + urlencode({"q": query, "limit": 10, "fields": "key,title,author_name"}), "open-library", gate, headers) or {}
    docs = payload.get("docs", [])
    if not isinstance(docs, list):
        raise TypeError("INVALID_PROVIDER_RESPONSE")
    return _result("open-library", [{"id": item["key"], "source": "open-library", "title": _text(item.get("title")),
        "authors": _strings(item.get("author_name")), "author": " / ".join(_strings(item.get("author_name"))) or None,
        "matchLevel": "WORK", "isbnScope": "UNKNOWN"} for item in docs[:10] if isinstance(item, dict) and item.get("key")])
