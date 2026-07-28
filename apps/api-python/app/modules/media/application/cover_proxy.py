"""Validation policy for remotely fetched metadata covers."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit


class UnsafeCoverUrl(ValueError):
    """Raised when a cover URL could reach a non-public network target."""


def configured_cover_origins(values: Iterable[object]) -> frozenset[tuple[str, str, int | None]]:
    origins: set[tuple[str, str, int | None]] = set()
    for value in values:
        parsed = urlsplit(str(value or "").strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            continue
        try:
            port = parsed.port
        except ValueError:
            continue
        origins.add((parsed.scheme.lower(), parsed.hostname.lower().rstrip("."), port))
    return frozenset(origins)


def validate_cover_url(
    url: str,
    *,
    configured_origins: frozenset[tuple[str, str, int | None]] = frozenset(),
) -> str:
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise UnsafeCoverUrl("unsupported cover URL")

    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeCoverUrl("invalid cover URL port") from exc

    if (scheme, hostname, port) in configured_origins:
        return url

    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(hostname, port or (443 if scheme == "https" else 80))
        }
    except (OSError, ValueError) as exc:
        raise UnsafeCoverUrl("cover host could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise UnsafeCoverUrl("cover host is not public")
    return url
