"""Stable local metadata source ordering shared by imports and organization."""

from __future__ import annotations

from typing import Literal, cast

LocalMetadataSource = Literal["SIDECAR_OPF", "EMBEDDED", "PATH"]

DEFAULT_LOCAL_METADATA_PRIORITY: tuple[LocalMetadataSource, ...] = (
    "SIDECAR_OPF",
    "EMBEDDED",
    "PATH",
)
_EXPECTED_SOURCES = frozenset(DEFAULT_LOCAL_METADATA_PRIORITY)


def validate_local_metadata_priority(
    value: object,
) -> tuple[LocalMetadataSource, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError("本地元数据识别顺序格式不正确")
    normalized = tuple(str(item).strip().upper() for item in value)
    if (
        len(normalized) != len(_EXPECTED_SOURCES)
        or set(normalized) != _EXPECTED_SOURCES
    ):
        raise ValueError(
            "本地元数据识别顺序必须包含 OPF、文件内部元数据和文件路径，且不能重复"
        )
    return cast(tuple[LocalMetadataSource, ...], normalized)


__all__ = [
    "DEFAULT_LOCAL_METADATA_PRIORITY",
    "LocalMetadataSource",
    "validate_local_metadata_priority",
]
