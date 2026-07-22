from __future__ import annotations

from datetime import timezone
from email.utils import parsedate_to_datetime
import hashlib
from html import unescape
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from xml.etree import ElementTree as ET

@dataclass(frozen=True)
class ProviderResult:
    ok: bool
    message: str
    details: Any = None


PROVIDER_CAPABILITIES: dict[str, dict[str, bool]] = {
    "manual": {"search": True, "download": False},
    "http": {"search": True, "download": True},
    "pt_rss": {"search": True, "download": False, "rss": True, "torrent": True, "requiresAuth": True},
    "rss": {"search": True, "download": True, "rss": True},
    "comic_api": {"search": True, "download": True, "api": True},
}

SENSITIVE_QUERY_KEYS = {"token", "passkey", "cookie", "auth", "key", "secret"}
TORRENT_MIME_TYPES = {"application/x-bittorrent", "application/octet-stream"}


def source_config(source: dict[str, Any]) -> dict[str, Any]:
    config = source.get("config")
    if isinstance(config, dict):
        return config
    if isinstance(config, str) and config.strip():
        try:
            parsed = json.loads(config)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def string_value(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def array_value(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [part.strip() for part in re.split(r"[,;\n]", value) if part.strip()]
    return []


def source_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    items = source_config(source).get("items")
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _matches_keyword(item: dict[str, Any], keyword: str, fields: list[str]) -> bool:
    lower = keyword.lower()
    return any(lower in (string_value(item.get(field)) or "").lower() for field in fields)


def _is_http_url(value: str | None) -> bool:
    return bool(value and (value.startswith("http://") or value.startswith("https://")))


def _source_kind(source: dict[str, Any], kind: str | None = None) -> str:
    if kind in {"novel", "comic", "mixed"}:
        return kind
    source_kind = string_value(source.get("kind"))
    return source_kind if source_kind in {"novel", "comic", "mixed"} else "novel"


def _rss_url(config: dict[str, Any]) -> str | None:
    return string_value(config.get("rssUrl")) or string_value(config.get("url"))


def _text_from_element(element: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in list(element):
        local = child.tag.rsplit("}", 1)[-1].lower()
        if local in names and child.text and child.text.strip():
            return unescape(child.text.strip())
    return None


def _attr_from_element(element: ET.Element, name: str) -> str | None:
    value = element.attrib.get(name)
    return unescape(value.strip()) if isinstance(value, str) and value.strip() else None


def _parse_rss_items(xml: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(xml)
    items: list[dict[str, Any]] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1].lower() != "item":
            continue
        enclosure = next((child for child in list(item) if child.tag.rsplit("}", 1)[-1].lower() == "enclosure"), None)
        items.append(
            {
                "title": _text_from_element(item, ("title",)),
                "link": _text_from_element(item, ("link",)),
                "guid": _text_from_element(item, ("guid", "id")),
                "pubDate": _text_from_element(item, ("pubdate", "published", "updated")),
                "category": _text_from_element(item, ("category",)),
                "enclosureUrl": _attr_from_element(enclosure, "url") if enclosure is not None else None,
                "enclosureType": _attr_from_element(enclosure, "type") if enclosure is not None else None,
                "enclosureLength": _attr_from_element(enclosure, "length") if enclosure is not None else None,
            }
        )
    return [item for item in items if item.get("title")]


def _fetch_rss_items(url: str) -> list[dict[str, Any]]:
    if not _is_http_url(url):
        raise ValueError("RSS URL 只支持 http/https。")
    request = UrlRequest(url, headers={"Accept": "application/rss+xml, application/xml, text/xml, */*"})
    with urlopen(request, timeout=12) as response:
        return _parse_rss_items(response.read())


def _date_iso(value: str | None) -> str | None:
    if not value:
        return None
    if re.fullmatch(r"\d{4}", value.strip()):
        return f"{value.strip()}-01-01T00:00:00+00:00"
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return value


def _hash_ref(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _sanitize_public_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return value
    query = urlencode(
        [(key, "REDACTED" if key.lower() in SENSITIVE_QUERY_KEYS else val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)]
    )
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, query, parsed.fragment))


def _is_torrent_like(url: str | None, mime_type: str | None = None) -> bool:
    if not url:
        return False
    lower_url = url.lower()
    lower_mime = (mime_type or "").lower()
    return lower_mime in TORRENT_MIME_TYPES or lower_url.startswith("magnet:") or ".torrent" in lower_url or lower_url.endswith("/download")


def _pt_rss_matches(item: dict[str, Any], keyword: str, config: dict[str, Any]) -> bool:
    title = (string_value(item.get("title")) or "").lower()
    if keyword and keyword.lower() not in title:
        return False
    category = string_value(config.get("category"))
    item_category = string_value(item.get("category"))
    if category and item_category and category.lower() not in item_category.lower():
        return False
    if any(word.lower() not in title for word in array_value(config.get("keywordInclude"))):
        return False
    if any(word.lower() in title for word in array_value(config.get("keywordExclude"))):
        return False
    return True


def _pt_rss_item_to_result(source: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any]:
    title = string_value(item.get("title")) or f"PT RSS 结果 {index + 1}"
    link = string_value(item.get("link"))
    enclosure_url = string_value(item.get("enclosureUrl"))
    enclosure_type = string_value(item.get("enclosureType"))
    torrent_link = enclosure_url if _is_torrent_like(enclosure_url, enclosure_type) else link if _is_torrent_like(link) else None
    download_source = enclosure_url or torrent_link
    ref = string_value(item.get("guid")) or link or enclosure_url or title
    return {
        "sourceId": source["id"],
        "providerType": "pt_rss",
        "externalId": string_value(item.get("guid")) or f"pt_rss:{_hash_ref(ref)}",
        "title": title,
        "subtitle": string_value(item.get("category")),
        "author": None,
        "description": None,
        "coverUrl": None,
        "externalUrl": _sanitize_public_url(link),
        "format": "comic",
        "size": string_value(item.get("enclosureLength")),
        "language": None,
        "publishedAt": _date_iso(string_value(item.get("pubDate"))),
        "downloadAvailable": bool(download_source),
        "downloadMeta": {
            "kind": "torrent",
            "source": download_source,
            "downloadUrl": enclosure_url or torrent_link,
            "enclosureType": enclosure_type,
            "enclosureLength": string_value(item.get("enclosureLength")),
            "refHash": _hash_ref(ref),
        }
        if download_source
        else None,
        "raw": {
            "rss": item,
            "guid": string_value(item.get("guid")),
            "category": string_value(item.get("category")),
            "hasEnclosure": bool(enclosure_url),
            "linkHash": _hash_ref(link or enclosure_url or title),
        },
    }


def _generic_rss_item_to_result(source: dict[str, Any], item: dict[str, Any], index: int, kind: str) -> dict[str, Any]:
    title = string_value(item.get("title")) or f"RSS 结果 {index + 1}"
    link = string_value(item.get("link"))
    enclosure_url = string_value(item.get("enclosureUrl"))
    enclosure_type = string_value(item.get("enclosureType"))
    download_url = enclosure_url if _is_http_url(enclosure_url) else link if _is_http_url(link) else None
    ref = string_value(item.get("guid")) or link or enclosure_url or title
    return {
        "sourceId": source["id"],
        "providerType": "rss",
        "externalId": string_value(item.get("guid")) or f"rss:{_hash_ref(ref)}",
        "title": title,
        "subtitle": string_value(item.get("category")),
        "author": None,
        "description": None,
        "coverUrl": None,
        "externalUrl": _sanitize_public_url(link),
        "format": "comic" if kind == "comic" else "ebook",
        "size": string_value(item.get("enclosureLength")),
        "language": None,
        "publishedAt": _date_iso(string_value(item.get("pubDate"))),
        "downloadAvailable": bool(download_url),
        "downloadMeta": {
            "type": "http",
            "downloadUrl": download_url,
            "enclosureType": enclosure_type,
            "enclosureLength": string_value(item.get("enclosureLength")),
            "refHash": _hash_ref(ref),
        }
        if download_url
        else None,
        "raw": {
            "rss": item,
            "guid": string_value(item.get("guid")),
            "category": string_value(item.get("category")),
            "hasEnclosure": bool(enclosure_url),
            "linkHash": _hash_ref(link or enclosure_url or title),
        },
    }


def _generic_rss_matches(item: dict[str, Any], keyword: str, config: dict[str, Any]) -> bool:
    title = (string_value(item.get("title")) or "").lower()
    category = (string_value(item.get("category")) or "").lower()
    lower_keyword = keyword.lower()
    if lower_keyword and lower_keyword not in title and lower_keyword not in category:
        return False
    configured_category = string_value(config.get("category"))
    if configured_category and configured_category.lower() not in category:
        return False
    if any(word.lower() not in title for word in array_value(config.get("keywordInclude"))):
        return False
    if any(word.lower() in title for word in array_value(config.get("keywordExclude"))):
        return False
    return True


def _gateway_items(payload: Any) -> list[dict[str, Any]]:
    value = payload.get("results") if isinstance(payload, dict) else payload
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _manual_item_to_result(source: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any] | None:
    external_id = string_value(item.get("externalId"))
    title = string_value(item.get("title"))
    if not external_id or not title:
        return None
    download_url = string_value(item.get("downloadUrl"))
    return {
        "sourceId": source["id"],
        "providerType": source.get("providerType") or "manual",
        "externalId": external_id,
        "title": title,
        "subtitle": string_value(item.get("subtitle")),
        "author": string_value(item.get("author")),
        "description": string_value(item.get("description")),
        "coverUrl": string_value(item.get("coverUrl")),
        "externalUrl": string_value(item.get("externalUrl")) or download_url,
        "format": string_value(item.get("format")),
        "size": string_value(item.get("size")),
        "language": string_value(item.get("language")),
        "publishedAt": string_value(item.get("publishedAt")),
        "downloadAvailable": bool(download_url),
        "downloadMeta": {"type": "manual", "downloadUrl": download_url} if download_url else None,
        "raw": {"manualItem": True, "index": index, "item": item},
    }


def _http_item_to_result(source: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any] | None:
    external_id = string_value(item.get("externalId"))
    title = string_value(item.get("title"))
    download_url = string_value(item.get("downloadUrl"))
    if not external_id or not title or not _is_http_url(download_url):
        return None
    return {
        "sourceId": source["id"],
        "providerType": source.get("providerType") or "http",
        "externalId": external_id,
        "title": title,
        "subtitle": string_value(item.get("subtitle")),
        "author": string_value(item.get("author")),
        "description": string_value(item.get("description")),
        "coverUrl": string_value(item.get("coverUrl")),
        "externalUrl": string_value(item.get("externalUrl")) or download_url,
        "format": string_value(item.get("format")),
        "size": string_value(item.get("size")),
        "language": string_value(item.get("language")),
        "publishedAt": string_value(item.get("publishedAt")),
        "downloadAvailable": True,
        "downloadMeta": {"type": "http", "downloadUrl": download_url},
        "raw": {"httpItem": True, "index": index, "item": item},
    }


def _comic_api_item_to_result(source: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any] | None:
    title = string_value(item.get("title"))
    if not title:
        return None
    download_url = string_value(item.get("downloadUrl")) or string_value(item.get("fileUrl"))
    external_url = string_value(item.get("externalUrl")) or string_value(item.get("url")) or download_url
    external_ref = f"{source.get('id')}:{title}:{external_url or index}"
    external_id = string_value(item.get("externalId")) or string_value(item.get("id")) or f"comic_api:{_hash_ref(external_ref)}"
    return {
        "sourceId": source["id"],
        "providerType": "comic_api",
        "externalId": external_id,
        "title": title,
        "subtitle": string_value(item.get("subtitle")) or string_value(item.get("series")),
        "author": string_value(item.get("author")),
        "description": string_value(item.get("description")) or string_value(item.get("summary")),
        "coverUrl": string_value(item.get("coverUrl")),
        "externalUrl": external_url,
        "format": string_value(item.get("format")) or "comic",
        "size": string_value(item.get("size")),
        "language": string_value(item.get("language")),
        "publishedAt": string_value(item.get("publishedAt")) or string_value(item.get("updatedAt")),
        "downloadAvailable": _is_http_url(download_url),
        "downloadMeta": {"type": "http", "downloadUrl": download_url} if _is_http_url(download_url) else None,
        "raw": {"comicApiItem": True, "index": index, "item": item},
    }


def _fetch_comic_api_results(source: dict[str, Any], keyword: str, kind: str, page: int, page_size: int) -> list[dict[str, Any]]:
    config = source_config(source)
    url = string_value(config.get("searchUrl")) or string_value(config.get("apiUrl")) or string_value(config.get("url"))
    if not _is_http_url(url):
        raise ValueError("请填写漫画搜索地址，或添加至少一条静态结果。")
    method = (string_value(config.get("method")) or "POST").upper()
    headers = {"Accept": "application/json"}
    api_key = string_value(config.get("apiKey"))
    if api_key:
        headers[string_value(config.get("apiKeyHeader")) or "Authorization"] = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
    if method == "GET":
        query = urlencode({"keyword": keyword, "kind": kind, "page": str(page), "pageSize": str(page_size)})
        request = UrlRequest(f"{url}{'&' if '?' in url else '?'}{query}", headers=headers)
    else:
        headers["Content-Type"] = "application/json"
        request = UrlRequest(
            url,
            data=json.dumps({"keyword": keyword, "kind": kind, "page": page, "pageSize": page_size}, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise ValueError(f"漫画 API 搜索失败：HTTP {exc.code}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"漫画 API 返回了无效 JSON：{exc}") from exc
    return [
        result
        for index, item in enumerate(_gateway_items(payload))
        if (result := _comic_api_item_to_result(source, item, index)) is not None
    ]


def test_source_provider(source: dict[str, Any]) -> ProviderResult:
    provider_type = source.get("providerType")
    if provider_type not in PROVIDER_CAPABILITIES:
        return ProviderResult(False, "这个来源暂不支持搜索或连接测试。")

    items = source_items(source)
    if provider_type == "manual":
        invalid_count = sum(1 for item in items if not string_value(item.get("externalId")) or not string_value(item.get("title")))
        if invalid_count:
            return ProviderResult(False, f"手动源中有 {invalid_count} 条结果缺少编号或标题。")
        return ProviderResult(True, f"手动源已就绪，可搜索 {len(items)} 条结果。")

    if provider_type == "http":
        if not items:
            return ProviderResult(False, "请先为 HTTP 源添加至少一条文件。")
        invalid_count = sum(
            1
            for item in items
            if not string_value(item.get("externalId")) or not string_value(item.get("title")) or not _is_http_url(string_value(item.get("downloadUrl")))
        )
        if invalid_count:
            return ProviderResult(False, f"HTTP 源中有 {invalid_count} 条文件缺少编号、标题或下载地址。")
        return ProviderResult(True, f"HTTP 源已就绪，可搜索 {len(items)} 条文件。")

    if provider_type == "pt_rss":
        config = source_config(source)
        url = _rss_url(config)
        if not url:
            return ProviderResult(False, "请配置 RSS 订阅地址。")
        if (string_value(config.get("defaultType")) or "comic") != "comic":
            return ProviderResult(False, "PT RSS 当前仅支持漫画内容。")
        try:
            preview = _fetch_rss_items(url)[:5]
        except Exception as exc:
            return ProviderResult(False, f"RSS 读取失败：{exc}")
        return ProviderResult(True, f"RSS 可读取，最近 {len(preview)} 条标题已返回预览。", {"preview": preview})

    if provider_type == "rss":
        config = source_config(source)
        url = _rss_url(config)
        if not url:
            return ProviderResult(False, "请配置 RSS 订阅地址。")
        try:
            preview = _fetch_rss_items(url)[:5]
        except Exception as exc:
            return ProviderResult(False, f"RSS 读取失败：{exc}")
        return ProviderResult(True, f"RSS 可读取，最近 {len(preview)} 条标题已返回预览。", {"preview": preview})

    if provider_type == "comic_api":
        config = source_config(source)
        items = source_items(source)
        api_url = string_value(config.get("searchUrl")) or string_value(config.get("apiUrl")) or string_value(config.get("url"))
        if api_url:
            if not _is_http_url(api_url):
                return ProviderResult(False, "漫画搜索地址必须以 http 或 https 开头。")
            return ProviderResult(True, "漫画源已就绪，将通过远程服务搜索。", {"apiConfigured": True})
        invalid_count = sum(1 for item in items if not string_value(item.get("title")))
        if invalid_count:
            return ProviderResult(False, f"漫画源中有 {invalid_count} 条结果缺少标题。")
        if not items:
            return ProviderResult(False, "请填写漫画搜索地址，或添加至少一条静态结果。")
        return ProviderResult(True, f"漫画源已就绪，可搜索 {len(items)} 条结果。", {"apiConfigured": False})

    return ProviderResult(False, "这个来源暂不支持搜索或连接测试。")


def search_source_provider(source: dict[str, Any], keyword: str, kind: str | None = None, page: int = 1, page_size: int = 20) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_type = source.get("providerType")
    if provider_type not in PROVIDER_CAPABILITIES:
        raise ValueError("这个来源暂不支持搜索。")

    if provider_type == "manual":
        items = source_items(source)
        fields = ["externalId", "title", "subtitle", "author", "description", "format", "language"]
        mapper = _manual_item_to_result
        start = max(0, page - 1) * page_size
        end = start + page_size
        matched = [item for item in items if _matches_keyword(item, keyword, fields)][start:end]
        results = [result for index, item in enumerate(matched) if (result := mapper(source, item, index))]
        return results, {"providerType": provider_type, "capabilities": PROVIDER_CAPABILITIES[provider_type]}

    if provider_type == "http":
        items = source_items(source)
        fields = ["externalId", "title", "subtitle", "author", "description", "format", "size", "language", "downloadUrl"]
        mapper = _http_item_to_result
        start = max(0, page - 1) * page_size
        end = start + page_size
        matched = [item for item in items if _matches_keyword(item, keyword, fields)][start:end]
        results = [result for index, item in enumerate(matched) if (result := mapper(source, item, index))]
        return results, {"providerType": provider_type, "capabilities": PROVIDER_CAPABILITIES[provider_type]}

    if provider_type == "comic_api":
        config = source_config(source)
        search_kind = _source_kind(source, kind)
        if string_value(config.get("searchUrl")) or string_value(config.get("apiUrl")) or string_value(config.get("url")):
            results = _fetch_comic_api_results(source, keyword, search_kind, page, page_size)
            return results, {"providerType": provider_type, "capabilities": PROVIDER_CAPABILITIES[provider_type]}
        fields = ["externalId", "id", "title", "subtitle", "series", "author", "description", "summary", "format", "language", "downloadUrl", "fileUrl"]
        start = max(0, page - 1) * page_size
        end = start + page_size
        matched = [item for item in source_items(source) if _matches_keyword(item, keyword, fields)][start:end]
        results = [result for index, item in enumerate(matched) if (result := _comic_api_item_to_result(source, item, index))]
        return results, {"providerType": provider_type, "capabilities": PROVIDER_CAPABILITIES[provider_type]}

    config = source_config(source)
    url = _rss_url(config)
    if not url:
        raise ValueError("请先配置 RSS 订阅地址")
    if provider_type == "pt_rss" and (string_value(config.get("defaultType")) or "comic") != "comic":
        raise ValueError("PT RSS 当前仅支持漫画内容。")
    try:
        items = _fetch_rss_items(url)
    except Exception as exc:
        raise ValueError(f"RSS 读取失败：{exc}") from exc
    start = max(0, page - 1) * page_size
    end = start + page_size
    if provider_type == "pt_rss":
        matched = [item for item in items if _pt_rss_matches(item, keyword, config)][start:end]
        results = [_pt_rss_item_to_result(source, item, index) for index, item in enumerate(matched)]
    else:
        search_kind = _source_kind(source, kind)
        matched = [item for item in items if _generic_rss_matches(item, keyword, config)][start:end]
        results = [_generic_rss_item_to_result(source, item, index, search_kind) for index, item in enumerate(matched)]
    return results, {"providerType": provider_type, "capabilities": PROVIDER_CAPABILITIES[provider_type]}
