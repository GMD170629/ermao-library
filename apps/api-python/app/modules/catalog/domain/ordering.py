"""Locale-independent ordering and path comparison for catalog topology."""

import re
import unicodedata
from collections.abc import Iterable

from app.modules.catalog.domain.model import PathComparison

_ASCII_DIGITS = re.compile(r"[0-9]+")


def comparison_component(value: str, comparison: PathComparison) -> str:
    """Return the comparison form without changing the preserved source name."""

    value = unicodedata.normalize("NFC", value)
    if comparison is PathComparison.INSENSITIVE:
        return value.casefold()
    return value


def comparison_path(
    path: tuple[str, ...], comparison: PathComparison
) -> tuple[str, ...]:
    return tuple(comparison_component(component, comparison) for component in path)


def _component_key(
    value: str, comparison: PathComparison
) -> tuple[tuple[tuple[int, int, str], ...], str, bytes]:
    normalized = comparison_component(value, comparison)
    tokens: list[tuple[int, int, str]] = []
    cursor = 0
    for match in _ASCII_DIGITS.finditer(normalized):
        if match.start() > cursor:
            tokens.append((1, 0, normalized[cursor : match.start()]))
        tokens.append((0, int(match.group()), ""))
        cursor = match.end()
    if cursor < len(normalized):
        tokens.append((1, 0, normalized[cursor:]))
    return tuple(tokens), normalized, value.encode("utf-8", "surrogatepass")


def natural_path_key(
    path: tuple[str, ...], comparison: PathComparison
) -> tuple[tuple[tuple[tuple[int, int, str], ...], str, bytes], ...]:
    return tuple(_component_key(component, comparison) for component in path)


def sorted_paths(
    paths: Iterable[tuple[str, ...]], comparison: PathComparison
) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted(paths, key=lambda path: natural_path_key(path, comparison)))
