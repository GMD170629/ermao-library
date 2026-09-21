"""Selective audio tags, verified against untouched frames, blocks and tracks."""

from typing import BinaryIO

from mutagen.flac import FLAC
from mutagen.id3 import COMM, ID3, TIT2, TPE1
from mutagen.mp4 import MP4

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.infrastructure.audio_structure import (
    flac_structure,
    mp3_structure,
    mp4_structure,
)
from app.modules.metadata.infrastructure.audio_tags import (
    FLAC_FIELDS,
    ID3_FIELDS,
    MP4_FIELDS,
    AudioFormat,
    audio_tag_metadata,
)
from app.modules.metadata.infrastructure.id3_writeback import write_selected_id3

AUDIO_WRITABLE_FIELDS = frozenset({"title", "authors", "description"})
_ID3 = {name: ID3_FIELDS[name].split(":", 1)[0] for name in AUDIO_WRITABLE_FIELDS}
_MP4 = {name: MP4_FIELDS[name] for name in AUDIO_WRITABLE_FIELDS}
_FLAC = {name: FLAC_FIELDS[name] for name in AUDIO_WRITABLE_FIELDS}


def _values(values: PublicationMetadata, field: str) -> list[str]:
    value = getattr(values, field)
    return list(value) if isinstance(value, tuple) else [value] if value else []


def _load(stream: BinaryIO, format: AudioFormat):
    stream.seek(0)
    return (
        ID3(stream, translate=False)
        if format == "MP3"
        else FLAC(stream)
        if format == "FLAC"
        else MP4(stream)
    )


def _tags(audio, format: AudioFormat) -> dict:
    return dict(audio if format == "MP3" else audio.tags or {})


def _observation(audio, format: AudioFormat) -> PublicationMetadata:
    return audio_tag_metadata(
        _tags(audio, format),
        format,
        id3_version=audio.version[1] if format == "MP3" else 4,
    )


def _structure(stream: BinaryIO, format: AudioFormat, fields: frozenset[str]):
    if format == "MP3":
        return mp3_structure(stream, frozenset(_ID3[name] for name in fields))
    return flac_structure(stream) if format == "FLAC" else mp4_structure(stream)


def inspect_audio_write(
    stream: BinaryIO,
    format: AudioFormat,
    values: PublicationMetadata,
    fields: frozenset[str],
) -> PublicationMetadata:
    if not fields or not fields <= AUDIO_WRITABLE_FIELDS:
        raise StandardMetadataError("UNSUPPORTED_METADATA_FIELD")
    if any(
        sum(len(value.encode("utf-8")) for value in _values(values, field)) > 1024**2
        for field in fields
    ):
        raise StandardMetadataError("METADATA_TOO_LARGE")
    _structure(stream, format, fields)
    audio = _load(stream, format)
    if (
        format == "MP3"
        and audio.version[1] == 3
        and "authors" in fields
        and any("/" in author for author in values.authors)
    ):
        raise StandardMetadataError("UNSUPPORTED_ID3_AUTHOR_SEPARATOR")
    return _observation(audio, format)


def write_audio_metadata(
    source: BinaryIO,
    output: BinaryIO,
    *,
    format: AudioFormat,
    values: PublicationMetadata,
    fields: frozenset[str],
) -> None:
    inspect_audio_write(source, format, values, fields)
    before_structure = _structure(source, format, fields)
    original = _load(source, format)
    before_tags = _tags(original, format)
    source.seek(0)
    output.seek(0)
    output.truncate()
    while chunk := source.read(1024**2):
        output.write(chunk)
    output.flush()
    audio = _load(output, format)
    if format == "MP3":
        version = audio.version[1]
        encoding = 1 if version == 3 else 3
        replacement = ID3()
        for field in fields:
            name = _ID3[field]
            # Other language/described comment frames are not the selected description.
            if field == "description":
                audio.pop("COMM::eng", None)
            else:
                audio.delall(name)
            selected = _values(values, field)
            if selected:
                frame = (
                    TIT2(encoding=encoding, text=selected)
                    if field == "title"
                    else TPE1(encoding=encoding, text=selected)
                    if field == "authors"
                    else COMM(encoding=encoding, lang="eng", desc="", text=selected)
                )
                replacement.add(frame)
        write_selected_id3(
            source,
            output,
            replacement,
            frozenset(_ID3[name] for name in fields),
            version,
        )
    else:
        if audio.tags is None:
            audio.add_tags()
        mapping = _FLAC if format == "FLAC" else _MP4
        for field in fields:
            name = mapping[field]
            selected = _values(values, field)
            if selected:
                audio.tags[name] = selected
            else:
                audio.tags.pop(name, None)
        output.seek(0)
        audio.save(output)
    output.flush()
    after_structure = _structure(output, format, fields)
    after_audio = _load(output, format)
    after_tags = _tags(after_audio, format)
    selected_keys = {
        (_ID3 if format == "MP3" else _FLAC if format == "FLAC" else _MP4)[field]
        for field in fields
    }
    if "COMM" in selected_keys:
        selected_keys.remove("COMM")
        selected_keys.add("COMM::eng")
    preserved_before = {
        key: value for key, value in before_tags.items() if key not in selected_keys
    }
    preserved_after = {
        key: value for key, value in after_tags.items() if key not in selected_keys
    }
    if before_structure != after_structure or preserved_before != preserved_after:
        raise StandardMetadataError("AUDIO_CONTENT_CHANGED")
    observed = _observation(after_audio, format)
    for field in fields:
        if _values(observed, field) != _values(values, field):
            raise StandardMetadataError("METADATA_VERIFICATION_FAILED")
