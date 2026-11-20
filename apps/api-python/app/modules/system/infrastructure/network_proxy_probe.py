"""Lightweight origin probes using the same configured outbound sender."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import OpenerDirector, Request

import httpx

from app.core.exception_diagnostics import capture_exception
from app.modules.system.domain.network_proxy import (
    NetworkProxy,
    ProxyPreset,
    ProxyProbeResult,
)

_PRESET_PROBES: dict[ProxyPreset, tuple[str, ...]] = {
    "updates": (
        "https://raw.githubusercontent.com/GMD170629/ermao-library/release-feed/index.json",
        "https://ghcr.io/v2/",
        "https://pkg-containers.githubusercontent.com/",
        "https://release-assets.githubusercontent.com/",
        "https://objects.githubusercontent.com/",
        "https://github.com/GMD170629/ermao-library/releases",
    ),
    "github": ("https://github.com/", "https://raw.githubusercontent.com/"),
    "bangumi": ("https://api.bgm.tv/v0/subjects/1", "https://lain.bgm.tv/"),
}


def _targets(snapshot: NetworkProxy) -> list[str]:
    presets = snapshot.presets
    if snapshot.connection is None and not (presets or snapshot.domains):
        presets = tuple(_PRESET_PROBES)
    candidates = [url for preset in presets for url in _PRESET_PROBES[preset]]
    candidates.extend(
        str(httpx.URL(scheme="https", host=domain, path="/"))
        for domain in snapshot.domains
    )
    by_host: dict[str, str] = {}
    for url in candidates:
        by_host.setdefault(urlsplit(url).hostname or "", url)
    return list(by_host.values())


def _probe(
    snapshot: NetworkProxy, opener: Callable[[], OpenerDirector], url: str
) -> ProxyProbeResult:
    host = urlsplit(url).hostname or ""
    rules = snapshot.rules_for(host)
    try:
        with opener().open(Request(url, method="HEAD"), timeout=5) as response:
            return ProxyProbeResult(
                host=host, rules=rules, result="connected", status=response.code
            )
    except HTTPError as error:
        capture_exception(error, persist=False)
        error.close()
        # Any origin HTTP response, including e.g. GHCR's 401, proves connectivity.
        return ProxyProbeResult(
            host=host,
            rules=rules,
            result="authentication" if error.code == 407 else "connected",
            status=error.code,
        )
    except (URLError, OSError) as error:
        capture_exception(error, persist=False)
        cause = error.__cause__
        reason = error.reason if isinstance(error, URLError) else error
        if isinstance(cause, httpx.TimeoutException) or isinstance(
            reason, TimeoutError
        ):
            return ProxyProbeResult(host=host, rules=rules, result="timeout")
        if isinstance(cause, httpx.ProxyError) and any(
            word in str(cause).lower() for word in ("407", "auth")
        ):
            return ProxyProbeResult(host=host, rules=rules, result="authentication")
        return ProxyProbeResult(host=host, rules=rules, result="failed")


def probe_network_proxy(
    snapshot: NetworkProxy,
    opener: Callable[[], OpenerDirector],
) -> list[ProxyProbeResult]:
    with ThreadPoolExecutor(max_workers=6) as executor:
        return list(
            executor.map(lambda url: _probe(snapshot, opener, url), _targets(snapshot))
        )
