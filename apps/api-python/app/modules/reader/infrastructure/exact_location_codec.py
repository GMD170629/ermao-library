"""Canonical JSON codec for validated exact Reader location DTOs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal, cast

from app.modules.reader.application.dto import (
    ReaderAudioExactLocationDto,
    ReaderComicExactLocationDto,
    ReaderEngineLocatorDto,
    ReaderExactLocationDto,
    ReaderPdfExactLocationDto,
    ReaderPublicationFingerprintDto,
    ReaderReflowableExactLocationDto,
)


def encode_exact_location(location: ReaderExactLocationDto) -> str:
    document: dict[str, object] = {
        "kind": _kind(location),
        "publication": _publication_document(location.publication),
    }
    if isinstance(location, ReaderReflowableExactLocationDto):
        document["engineLocator"] = _engine_document(location.engine_locator)
    elif isinstance(location, ReaderPdfExactLocationDto):
        document.update(
            pageIndex=location.page_index,
            pageProgression=location.page_progression,
        )
        _add_optional_engine(document, location.engine_locator)
    elif isinstance(location, ReaderComicExactLocationDto):
        document.update(
            pageIndex=location.page_index,
            resourceHref=location.resource_href,
        )
        _add_optional_engine(document, location.engine_locator)
    elif isinstance(location, ReaderAudioExactLocationDto):
        document.update(
            fileId=location.file_id,
            positionMillis=location.position_millis,
        )
        if location.chapter_id is not None:
            document["chapterId"] = location.chapter_id
        _add_optional_engine(document, location.engine_locator)
    return json.dumps(document, ensure_ascii=False, separators=(",", ":"))


def decode_exact_location(raw_json: str | None) -> ReaderExactLocationDto | None:
    if not raw_json:
        return None
    try:
        value: object = json.loads(raw_json)
        root = _mapping(value)
        publication = _publication(root["publication"])
        kind = _string(root, "kind")
        if kind == "reflowable":
            engine = _engine(root["engineLocator"])
            payload = _mapping(json.loads(engine.payload_json))
            locations = _mapping(payload["locations"])
            return ReaderReflowableExactLocationDto(
                publication=publication,
                resource_href=_string(payload, "href"),
                media_type=_string(payload, "type"),
                resource_progression=_optional_number(locations, "progression"),
                total_progression=_optional_number(locations, "totalProgression"),
                engine_locator=engine,
            )
        if kind == "pdf":
            return ReaderPdfExactLocationDto(
                publication=publication,
                page_index=_integer(root, "pageIndex"),
                page_progression=_number(root, "pageProgression"),
                engine_locator=_optional_engine(root),
            )
        if kind == "comic":
            return ReaderComicExactLocationDto(
                publication=publication,
                page_index=_integer(root, "pageIndex"),
                resource_href=_string(root, "resourceHref"),
                engine_locator=_optional_engine(root),
            )
        if kind == "audio":
            return ReaderAudioExactLocationDto(
                publication=publication,
                file_id=_string(root, "fileId"),
                chapter_id=_optional_string(root, "chapterId"),
                position_millis=_integer(root, "positionMillis"),
                engine_locator=_optional_engine(root),
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return None


def _kind(location: ReaderExactLocationDto) -> str:
    if isinstance(location, ReaderReflowableExactLocationDto):
        return "reflowable"
    if isinstance(location, ReaderPdfExactLocationDto):
        return "pdf"
    if isinstance(location, ReaderComicExactLocationDto):
        return "comic"
    return "audio"


def _publication_document(value: ReaderPublicationFingerprintDto) -> dict[str, str]:
    return {
        "originalFileHash": value.original_file_hash,
        "parser": value.parser,
        "normalization": value.normalization,
    }


def _publication(value: object) -> ReaderPublicationFingerprintDto:
    root = _mapping(value)
    return ReaderPublicationFingerprintDto(
        original_file_hash=_string(root, "originalFileHash"),
        parser=_string(root, "parser"),
        normalization=_string(root, "normalization"),
    )


def _engine_document(value: ReaderEngineLocatorDto) -> dict[str, object]:
    payload: object = json.loads(value.payload_json)
    if not isinstance(payload, dict):
        raise TypeError("Readium payload must be an object")
    return {
        "engine": "readium",
        "platform": value.platform,
        "version": value.version,
        "payload": payload,
    }


def _engine(value: object) -> ReaderEngineLocatorDto:
    root = _mapping(value)
    if _string(root, "engine") != "readium":
        raise ValueError("Unsupported Reader engine")
    platform = _string(root, "platform")
    if platform not in {"android", "ios", "web"}:
        raise ValueError("Unsupported Reader platform")
    payload = _mapping(root["payload"])
    return ReaderEngineLocatorDto(
        platform=cast(Literal["android", "ios", "web"], platform),
        version=_string(root, "version"),
        payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def _add_optional_engine(
    document: dict[str, object], value: ReaderEngineLocatorDto | None
) -> None:
    if value is not None:
        document["engineLocator"] = _engine_document(value)


def _optional_engine(root: Mapping[str, object]) -> ReaderEngineLocatorDto | None:
    value = root.get("engineLocator")
    return _engine(value) if value is not None else None


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Reader location value must be an object")
    return value


def _string(root: Mapping[str, object], name: str) -> str:
    value = root.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Reader location field {name} must be a string")
    return value


def _optional_string(root: Mapping[str, object], name: str) -> str | None:
    value = root.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"Reader location field {name} must be a string")
    return value


def _integer(root: Mapping[str, object], name: str) -> int:
    value = root.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"Reader location field {name} must be an integer")
    return value


def _number(root: Mapping[str, object], name: str) -> float:
    value = root.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"Reader location field {name} must be numeric")
    return float(value)


def _optional_number(root: Mapping[str, object], name: str) -> float | None:
    return _number(root, name) if name in root else None
