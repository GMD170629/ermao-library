from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from app.modules.reader.application.dto import ReaderPublicationFingerprintDto

_LIBMOBI_PARSER = "libmobi:0.12@85dcfe803fc2a21020ddcf15c3eb66b93d388add"
_FORMAT_IDENTIFIERS: dict[str, tuple[str, str]] = {
    "epub": ("epub-package:1", "shuku-epub-locator-dom-v2"),
    "mobi": (_LIBMOBI_PARSER, "ermao-mobi-core-v1+shuku-locator-dom-v2"),
    "azw": (_LIBMOBI_PARSER, "ermao-mobi-core-v1+shuku-locator-dom-v2"),
    "azw3": (_LIBMOBI_PARSER, "ermao-mobi-core-v1+shuku-locator-dom-v2"),
    "prc": (_LIBMOBI_PARSER, "ermao-mobi-core-v1+shuku-locator-dom-v2"),
    "txt": ("shuku-txt-parser-v1", "shuku-txt-publication-v2"),
    "fb2": ("shuku-fb2-parser-v1", "shuku-fb2-publication-v1"),
    "pdf": ("pdf:source-v1", "shuku-pdf-pages-v1"),
    "cbz": ("archive-images:natural-order-v1", "shuku-comic-pages-v1"),
    "cbr": ("archive-images:natural-order-v1", "shuku-comic-pages-v1"),
    "mp3": ("readium-audio:v1", "shuku-audio-tracks-v1"),
    "m4b": ("readium-audio:v1", "shuku-audio-tracks-v1"),
    "m4a": ("readium-audio:v1", "shuku-audio-tracks-v1"),
    "flac": ("readium-audio:v1", "shuku-audio-tracks-v1"),
    "ogg": ("readium-audio:v1", "shuku-audio-tracks-v1"),
    "opus": ("readium-audio:v1", "shuku-audio-tracks-v1"),
    "wav": ("readium-audio:v1", "shuku-audio-tracks-v1"),
}


def build_volume_content_fingerprint(
    volume: Mapping[str, object],
    files: Sequence[Mapping[str, object]],
) -> str:
    """Build a fingerprint whose identity and inputs are strictly volume-scoped."""

    tokens: list[dict[str, object | None]] = [
        {
            "id": item.get("id"),
            "hash": item.get("fingerprint")
            or item.get("fullHash")
            or item.get("full_hash"),
            "size": item.get("sizeBytes") or item.get("size_bytes"),
            "mtime": item.get("mtimeMs") or item.get("mtime_ms"),
        }
        for item in files
    ]
    if not tokens:
        tokens = [
            {
                "volume": volume.get("id"),
                "updated": str(
                    volume.get("updatedAt") or volume.get("updated_at") or ""
                ),
            }
        ]
    serialized = json.dumps(tokens, ensure_ascii=False, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def build_publication_fingerprint(
    volume: Mapping[str, object],
    files: Sequence[Mapping[str, object]],
) -> ReaderPublicationFingerprintDto:
    """Build the exact Publication identity shared by all Reader v4 clients."""

    original_file_hash = _original_file_hash(volume, files)
    normalized_format = str(volume.get("format") or "").strip().lower()
    parser, normalization = _FORMAT_IDENTIFIERS.get(
        normalized_format,
        (f"shuku-{normalized_format or 'unknown'}-parser-v1", "shuku-publication-v1"),
    )
    return ReaderPublicationFingerprintDto(
        original_file_hash=original_file_hash,
        parser=parser,
        normalization=normalization,
    )


def publication_fingerprint_key(fingerprint: ReaderPublicationFingerprintDto) -> str:
    serialized = (
        f"{fingerprint.original_file_hash.lower()}\0"
        f"{fingerprint.parser}\0{fingerprint.normalization}"
    )
    return f"sha256:{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"


def _original_file_hash(
    volume: Mapping[str, object], files: Sequence[Mapping[str, object]]
) -> str:
    def sort_order(item: Mapping[str, object]) -> int:
        value = item.get("sort_order") or item.get("sortOrder") or 0
        return value if isinstance(value, int) else 0

    ordered_files = sorted(
        files,
        key=lambda item: (
            sort_order(item),
            str(item.get("id") or ""),
        ),
    )
    if len(ordered_files) == 1:
        full_hash = ordered_files[0].get("full_hash") or ordered_files[0].get(
            "fullHash"
        )
        if isinstance(full_hash, str):
            normalized = full_hash.removeprefix("sha256:")
            if len(normalized) == 64 and all(
                character in "0123456789abcdefABCDEF" for character in normalized
            ):
                return f"sha256:{normalized.lower()}"
    return build_volume_content_fingerprint(volume, files)
