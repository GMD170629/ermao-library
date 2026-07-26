from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import httpx

from appv2.modules.metadata.contracts import (
    MetadataCandidate,
    ProviderRegistry,
    ProviderView,
)

BANGUMI_API_ROOT = "https://api.bgm.tv"
DEFAULT_USER_AGENT = "Shuku-Starship/0.4.0 (https://github.com/GMD170629/ermao-library)"


def _object_dict(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if text := _string(item):
            result.append(text)
            continue
        item_data = _object_dict(item)
        text = _string(item_data.get("v")) or _string(item_data.get("name"))
        if text:
            result.append(text)
    return result


def _infobox_value(subject: dict[str, object], *keys: str) -> str | None:
    infobox = subject.get("infobox")
    if not isinstance(infobox, list):
        return None
    normalized_keys = {key.casefold() for key in keys}
    for item in infobox:
        item_data = _object_dict(item)
        key = _string(item_data.get("key"))
        if key is None or key.casefold() not in normalized_keys:
            continue
        values = _strings(item_data.get("value"))
        if values:
            return ", ".join(values)
    return None


def _tag_names(subject: dict[str, object]) -> list[str]:
    tags = subject.get("tags")
    if not isinstance(tags, list):
        return []
    result: list[str] = []
    for tag in tags[:20]:
        name = _string(_object_dict(tag).get("name"))
        if name:
            result.append(name)
    return result


def _cover_url(subject: dict[str, object]) -> str | None:
    images = _object_dict(subject.get("images"))
    for key in ("large", "common", "medium", "grid", "small"):
        value = _string(images.get(key))
        if value and value.startswith("https://"):
            return value
    return None


def _published_year(value: object) -> int | None:
    text = _string(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10]).year
    except ValueError:
        return None


class ConfiguredProviderRegistry(ProviderRegistry):
    """Executes only compiled-in provider adapters.

    Provider configuration can enable and prioritize an adapter, but it cannot
    introduce an arbitrary target URL or executable provider implementation.
    """

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def search_all(self, query: str, providers: list[ProviderView]) -> list[MetadataCandidate]:
        candidates: list[MetadataCandidate] = []
        for provider in providers:
            if not provider.enabled:
                continue
            if provider.slug == "bangumi":
                candidates.extend(self._search_bangumi(query, provider))
        return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)

    def _search_bangumi(
        self,
        query: str,
        provider: ProviderView,
    ) -> list[MetadataCandidate]:
        configured_agent = _string(provider.config.get("userAgent"))
        headers = {
            "Accept": "application/json",
            "User-Agent": configured_agent or DEFAULT_USER_AGENT,
        }
        with httpx.Client(
            base_url=BANGUMI_API_ROOT,
            headers=headers,
            timeout=self._timeout_seconds,
            follow_redirects=False,
            transport=self._transport,
        ) as client:
            response = client.post(
                "/v0/search/subjects",
                params={"limit": 10, "offset": 0},
                json={
                    "keyword": query,
                    "sort": "match",
                    "filter": {"type": [1], "nsfw": False},
                },
            )
            response.raise_for_status()
            payload: object = response.json()
        data = _object_dict(payload).get("data")
        if not isinstance(data, list):
            return []
        result: list[MetadataCandidate] = []
        for index, item in enumerate(data[:10]):
            subject = _object_dict(item)
            subject_id = subject.get("id")
            if not isinstance(subject_id, int):
                continue
            title = _string(subject.get("name_cn")) or _string(subject.get("name"))
            if title is None:
                continue
            raw_payload: dict[str, object] = {
                "description": _string(subject.get("summary")) or "",
                "tags": _tag_names(subject),
            }
            if publisher := _infobox_value(subject, "出版社", "出版"):
                raw_payload["publisher"] = publisher
            if year := _published_year(subject.get("date")):
                raw_payload["publishedYear"] = year
            result.append(
                MetadataCandidate(
                    provider_id=provider.id,
                    external_id=str(subject_id),
                    title=title,
                    author=_infobox_value(
                        subject,
                        "作者",
                        "原作",
                        "脚本",
                        "Author",
                    ),
                    confidence=max(0.5, 0.95 - index * 0.04),
                    cover_url=_cover_url(subject),
                    raw_payload=raw_payload,
                )
            )
        return result
