"""Pure rules for non-audio path metadata selection."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal

PathMediaFamily = Literal["EBOOK", "COMIC"]

PATH_SIMILARITY_THRESHOLD = 0.50

_COMIC_EXTENSIONS = frozenset({".cbr", ".cbz", ".rar", ".zip"})
_EBOOK_EXTENSIONS = frozenset(
    {".azw", ".azw3", ".epub", ".fb2", ".mobi", ".pdf", ".prc", ".txt"}
)
_SUPPORTED_EXTENSIONS = _COMIC_EXTENSIONS | _EBOOK_EXTENSIONS
_TEMPORARY_SUFFIXES = (".crdownload", ".download", ".part", ".tmp")


def path_title_similarity(left: object, right: object) -> float:
    """Compare parsed work candidates after path-title normalization."""

    left_key = _normalize_path_title(left)
    right_key = _normalize_path_title(right)
    if not left_key or not right_key:
        return 0.0
    return SequenceMatcher(None, left_key, right_key, autojunk=False).ratio()


def path_titles_are_related(left: object, right: object) -> bool:
    """Use the product's strict greater-than-half relationship rule."""

    return path_title_similarity(left, right) > PATH_SIMILARITY_THRESHOLD


def path_media_family(
    filename: str,
    *,
    media_kind_policy: str,
    allowed_extensions: tuple[str, ...],
) -> PathMediaFamily | None:
    """Return the sibling-evidence family for one supported publication file."""

    normalized_name = filename.strip().casefold()
    if not normalized_name or normalized_name.startswith("."):
        return None
    if normalized_name.endswith("~") or normalized_name.endswith(_TEMPORARY_SUFFIXES):
        return None
    suffix = _last_suffix(normalized_name)
    allowed = {_normalize_extension(value) for value in allowed_extensions}
    if suffix not in _SUPPORTED_EXTENSIONS or suffix not in allowed:
        return None
    normalized_policy = media_kind_policy.strip().upper()
    if normalized_policy == "EBOOK":
        return "EBOOK"
    if normalized_policy == "COMIC":
        return "COMIC"
    if normalized_policy == "AUDIOBOOK":
        return None
    return "COMIC" if suffix in _COMIC_EXTENSIONS else "EBOOK"


def _normalize_path_title(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = re.sub(
        r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\]+",
        "",
        normalized,
    )
    return re.sub(r"\d+", "{number}", normalized).strip()


def _last_suffix(filename: str) -> str:
    dot_index = filename.rfind(".")
    return filename[dot_index:] if dot_index >= 0 else ""


def _normalize_extension(value: str) -> str:
    extension = value.strip().casefold()
    return extension if extension.startswith(".") else f".{extension}"
