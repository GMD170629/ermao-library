from __future__ import annotations

import json
import urllib.parse
import uuid
from pathlib import Path

import httpx

from appv2.modules.discovery.contracts import (
    DownloadPort,
    SearchResultView,
    SourceResult,
    SourceSearchPort,
    SourceView,
)


def _nested(value: object, path: str) -> object:
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class JsonHttpSourceSearch(SourceSearchPort):
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout = timeout_seconds

    def search(self, source: SourceView, query: str) -> list[SourceResult]:
        search_path = str(source.config.get("searchPath", "/search"))
        query_param = str(source.config.get("queryParam", "q"))
        url = urllib.parse.urljoin(
            f"{source.base_url}/",
            search_path.lstrip("/"),
        )
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urllib.parse.urlencode({query_param: query})}"
        response = httpx.get(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Shuku-Starship/0.4.0",
            },
            timeout=self._timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = json.loads(response.content)
        raw_items = _nested(payload, str(source.config.get("resultsPath", "items")))
        if not isinstance(raw_items, list):
            raise ValueError("source response does not contain a result list")
        results: list[SourceResult] = []
        for item in raw_items[:200]:
            if not isinstance(item, dict):
                continue
            external_id = str(item.get("id") or item.get("url") or uuid.uuid4())
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            results.append(
                SourceResult(
                    source_id=source.id,
                    external_id=external_id,
                    title=title,
                    author=str(item["author"]) if item.get("author") else None,
                    download_url=(str(item["downloadUrl"]) if item.get("downloadUrl") else None),
                    info_url=str(item["infoUrl"]) if item.get("infoUrl") else None,
                    payload={str(key): value for key, value in item.items()},
                )
            )
        return results


class HttpDownloadAdapter(DownloadPort):
    def __init__(self, root: Path, timeout_seconds: int) -> None:
        self._root = root / "downloads"
        self._timeout = timeout_seconds

    def download(self, result: SearchResultView) -> str:
        if not result.download_url:
            raise ValueError("search result has no download URL")
        self._root.mkdir(parents=True, exist_ok=True)
        parsed = urllib.parse.urlparse(result.download_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("download URL must use HTTP or HTTPS")
        name = Path(parsed.path).name or f"{result.id}.download"
        destination = self._root / f"{result.id}-{name}"
        with httpx.stream(
            "GET",
            result.download_url,
            headers={"User-Agent": "Shuku-Starship/0.4.0"},
            timeout=self._timeout,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            with destination.open("xb") as target:
                for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                    target.write(chunk)
        return str(destination.resolve())
