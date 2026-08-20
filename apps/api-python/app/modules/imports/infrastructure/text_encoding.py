"""Bounded encoding detection for original TXT publications."""

from __future__ import annotations

import codecs
from pathlib import Path

TXT_ENCODING_SAMPLE_BYTES = 4 * 1024 * 1024
TXT_ENCODING_MAX_SEQUENCE_BYTES = 4


class TextEncodingError(ValueError):
    """TXT bytes cannot be decoded without guessing or replacement."""


def _decode_sample(sample: bytes, continuation: bytes, *, encoding: str) -> str:
    if not continuation:
        return sample.decode(encoding, errors="strict")

    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    decoded = decoder.decode(sample, final=False)
    continuation_offset = 0
    pending, _ = decoder.getstate()
    while pending:
        if continuation_offset >= len(continuation):
            return decoded + decoder.decode(b"", final=True)
        decoded += decoder.decode(
            continuation[continuation_offset : continuation_offset + 1],
            final=False,
        )
        continuation_offset += 1
        pending, _ = decoder.getstate()
    return decoded


def _strip_verified_trailing_nul_padding(path: Path, prefix: bytes) -> bytes:
    first_nul = prefix.find(b"\x00")
    if first_nul < 0:
        return prefix

    with path.open("rb") as source:
        source.seek(first_nul)
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            if chunk.strip(b"\x00"):
                raise TextEncodingError("无法可靠识别 TXT 编码")
    return prefix[:first_nul]


def detect_txt_encoding(path: Path) -> str:
    """Return a deterministic TXT encoding or reject ambiguous bytes."""

    with path.open("rb") as source:
        prefix = source.read(
            TXT_ENCODING_SAMPLE_BYTES + TXT_ENCODING_MAX_SEQUENCE_BYTES - 1
        )
    sample = prefix[:TXT_ENCODING_SAMPLE_BYTES]
    continuation = prefix[TXT_ENCODING_SAMPLE_BYTES:]
    if not sample:
        raise TextEncodingError("TXT 文件为空")
    if sample.startswith(codecs.BOM_UTF8):
        _strip_verified_trailing_nul_padding(path, prefix)
        return "utf-8-sig"
    if sample.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le"
    if sample.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be"
    if b"\x00" in sample:
        prefix = _strip_verified_trailing_nul_padding(path, prefix)
        sample = prefix[:TXT_ENCODING_SAMPLE_BYTES]
        continuation = prefix[TXT_ENCODING_SAMPLE_BYTES:]
        if not sample:
            raise TextEncodingError("无法可靠识别 TXT 编码")
    try:
        _decode_sample(sample, continuation, encoding="utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        decoded = _decode_sample(sample, continuation, encoding="gb18030")
    except UnicodeDecodeError as error:
        raise TextEncodingError("无法可靠识别 TXT 编码") from error
    if decoded.count("�") / max(1, len(decoded)) > 0.001:
        raise TextEncodingError("无法可靠识别 TXT 编码")
    return "gb18030"


__all__ = ["TextEncodingError", "detect_txt_encoding"]
