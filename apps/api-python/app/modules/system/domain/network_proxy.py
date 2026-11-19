"""Domain rules for routing server requests through one configured proxy."""

import re
from dataclasses import dataclass, field
from ipaddress import ip_address
from typing import Literal

ProxyProtocol = Literal["http", "socks5"]
ProxyPreset = Literal["updates", "github", "bangumi"]
ProxyProbeStatus = Literal[
    "connected", "timeout", "authentication", "failed", "not_configured"
]
PROXY_SETTING_KEY = "network.proxy"

PROXY_PRESETS: dict[ProxyPreset, tuple[str, ...]] = {
    "updates": (
        "raw.githubusercontent.com",
        "github.com",
        "ghcr.io",
        "pkg-containers.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    ),
    "github": ("github.com", "githubusercontent.com"),
    "bangumi": ("bgm.tv", "bangumi.tv", "chii.in"),
}


def normalize_host(value: str) -> str:
    host = value.strip().rstrip(".")
    if ":" in host:
        return str(ip_address(host))
    ascii_host = host.encode("idna").decode("ascii").lower()
    if not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in ascii_host.split(".")
    ):
        raise ValueError("Invalid host name")
    return ascii_host


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


@dataclass(frozen=True)
class ProxyConnection:
    protocol: ProxyProtocol
    host: str
    port: int
    username: str = ""
    password: str = field(default="", repr=False)


@dataclass(frozen=True)
class ProxyProbeResult:
    host: str
    rules: tuple[str, ...]
    result: ProxyProbeStatus
    status: int | None = None


@dataclass(frozen=True)
class NetworkProxy:
    connection: ProxyConnection | None = None
    presets: tuple[ProxyPreset, ...] = ()
    domains: tuple[str, ...] = ()

    def rules_for(self, host: str) -> tuple[str, ...]:
        normalized = normalize_host(host)
        return (
            *(
                key
                for key in self.presets
                if any(_matches(normalized, domain) for domain in PROXY_PRESETS[key])
            ),
            *(domain for domain in self.domains if _matches(normalized, domain)),
        )
