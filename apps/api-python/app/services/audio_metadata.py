from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any

from app.modules.imports.application.audio_types import (
    DISC_DIRECTORY_PATTERN,
    LEGACY_AUDIO_EXTS,
    MAX_AUDIO_BUNDLE_TRACKS,
    MAX_AUDIO_CHAPTERS,
    AudioBundleStructure,
    AudioChapterMetadata,
    AudioFileMetadata,
    AudioVolumeDirectory,
    is_supported_audio_file,
)
from app.modules.imports.application.errors import (
    AudioInspectionError,
    AudioTrackLimitExceededError,
)
from app.modules.imports.domain.volume_index import parse_structured_volume_index
from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    normalize_identity_part,
    recognize_book_identity_with_regex,
)

AAC_RFC6381_OBJECT_TYPES = {2, 5, 29}
MAX_EMBEDDED_COVER_BYTES = 20 * 1024 * 1024
MAX_FFPROBE_STDOUT_BYTES = 16 * 1024 * 1024
MAX_FFPROBE_STDERR_BYTES = 256 * 1024
MISDECLARED_TEXT_ENCODING_CANDIDATES = (
    "utf-8",
    "gb18030",
    "big5",
    "shift_jis",
    "cp1252",
)
MUTAGEN_TEXT_ENCODINGS = {
    0: "latin-1",
    1: "utf-16",
    2: "utf-16-be",
    3: "utf-8",
}


def read_audio_group_identity(path: str | Path) -> tuple[str | None, str | None]:
    """Read only the tags needed by the watcher to prove bundle membership.

    This intentionally avoids ffprobe and duration parsing: watcher events can
    arrive while a large file is still being copied.  A missing/unreadable tag
    is represented as ``None`` and never used as proof that unrelated files
    belong to one book.
    """

    source = Path(path).expanduser().resolve()
    if not source.is_file() or not is_supported_audio_file(source):
        return None, None
    try:
        import mutagen  # type: ignore[import-not-found]

        audio = mutagen.File(str(source), easy=False)
    # Mutagen plugins may raise format-specific exceptions that do not share a
    # stable public base class; this read-only probe boundary treats all as no tag evidence.
    except Exception:  # noqa: BLE001
        return None, None
    if audio is None:
        return None, None
    values = _normalized_mutagen_tags(getattr(audio, "tags", None))
    album = _clean_text(_first_tag(values, "album", "©alb", "talb"))
    author = _clean_text(
        _first_tag(
            values,
            "albumartist",
            "album artist",
            "aart",
            "©art",
            "artist",
            "tpe1",
            "tpe2",
        )
    )
    return album.casefold() if album else None, author.casefold() if author else None


def _directory_identity(path: Path) -> tuple[str, str | None, float | None]:
    identity = recognize_book_identity_with_regex(f"{path.name}.epub")
    author = identity.author if identity.author != UNKNOWN_AUTHOR else None
    return identity.title.strip() or path.name, author, identity.volume_index


class _AudioTrackCounter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.count = 0

    def add(self, path: Path) -> Path:
        self.count += 1
        if self.count > MAX_AUDIO_BUNDLE_TRACKS:
            raise AudioTrackLimitExceededError(
                path=str(self.root),
                limit=MAX_AUDIO_BUNDLE_TRACKS,
                observed_count=self.count,
            )
        return path.resolve()


def _iter_directory_entries(path: Path):
    iterator = os.scandir(path)
    try:
        yield from iterator
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()


def _direct_audio_files(path: Path, counter: _AudioTrackCounter) -> list[Path]:
    return [
        counter.add(Path(entry.path))
        for entry in _iter_directory_entries(path)
        if entry.is_file(follow_symlinks=False) and is_supported_audio_file(entry.name)
    ]


def _directory_audio_files(
    path: Path,
    counter: _AudioTrackCounter,
) -> list[Path]:
    files = _direct_audio_files(path, counter)
    for entry in _iter_directory_entries(path):
        if not entry.is_dir(follow_symlinks=False) or not DISC_DIRECTORY_PATTERN.match(
            entry.name.strip()
        ):
            continue
        files.extend(_direct_audio_files(Path(entry.path), counter))
    return sorted(dict.fromkeys(files), key=_natural_audio_key)


def inspect_audio_bundle(path: str | Path) -> AudioBundleStructure | None:
    """Resolve a single- or multi-volume audiobook directory.

    Disc/CD directories are physical track groupings. Other child directories
    become volumes only when the shared identity parser finds a volume number,
    or when their normalized title contains the parent book title.
    """

    root = Path(path).expanduser().resolve()
    if root.is_file():
        if not is_supported_audio_file(root):
            return None
        return AudioBundleStructure(
            root=root,
            title=root.stem,
            author=None,
            volumes=(AudioVolumeDirectory(root, root.stem, None, None, (root,)),),
        )
    if not root.is_dir():
        return None

    counter = _AudioTrackCounter(root)
    root_title, root_author, _root_volume_index = _directory_identity(root)
    direct_files = _directory_audio_files(root, counter)
    root_key = normalize_identity_part(root_title)
    matched_volumes: list[AudioVolumeDirectory] = []
    for entry in _iter_directory_entries(root):
        if not entry.is_dir(follow_symlinks=False):
            continue
        child = Path(entry.path)
        if DISC_DIRECTORY_PATTERN.match(entry.name.strip()):
            continue
        child_title, child_author, volume_index = _directory_identity(child)
        child_key = normalize_identity_part(child_title)
        title_contains_parent = bool(
            root_key and child_key and root_key != child_key and root_key in child_key
        )
        if volume_index is None and not title_contains_parent:
            continue
        child_files = _directory_audio_files(child, counter)
        if not child_files:
            continue
        matched_volumes.append(
            AudioVolumeDirectory(
                path=child.resolve(),
                title=child.name,
                volume_index=volume_index,
                author=child_author,
                files=tuple(child_files),
            )
        )

    if direct_files and matched_volumes:
        raise ValueError(
            "有声书书名目录不能同时包含直属音轨和卷目录，请整理为单卷或多卷结构后重试"
        )
    if matched_volumes:
        matched_volumes.sort(
            key=lambda volume: (
                volume.volume_index is None,
                volume.volume_index
                if volume.volume_index is not None
                else float("inf"),
                _natural_audio_key(volume.path),
            )
        )
        volumes = tuple(matched_volumes)
    elif direct_files:
        volumes = (
            AudioVolumeDirectory(
                path=root,
                title="正文",
                volume_index=None,
                author=None,
                files=tuple(direct_files),
            ),
        )
    else:
        return None

    return AudioBundleStructure(
        root=root,
        title=root_title,
        author=root_author,
        volumes=volumes,
    )


def collect_audio_bundle_files(path: str | Path) -> list[Path]:
    structure = inspect_audio_bundle(path)
    return list(structure.files) if structure else []


def audio_bundle_root(path: str | Path, monitor_root: str | Path | None = None) -> Path:
    source = Path(path).expanduser().resolve()
    if source.is_dir():
        return source
    parent = source.parent
    if DISC_DIRECTORY_PATTERN.match(parent.name.strip()):
        parent = parent.parent
    configured_root = (
        Path(monitor_root).expanduser().resolve() if monitor_root is not None else None
    )
    if configured_root is not None and parent == configured_root:
        return parent
    grandparent = parent.parent
    if grandparent != parent and (
        configured_root is None
        or grandparent == configured_root
        or configured_root in grandparent.parents
    ):
        root_title, _root_author, _root_volume = _directory_identity(grandparent)
        child_title, _child_author, child_volume = _directory_identity(parent)
        root_key = normalize_identity_part(root_title)
        child_key = normalize_identity_part(child_title)
        if child_volume is not None or bool(
            root_key and child_key and root_key != child_key and root_key in child_key
        ):
            return grandparent
    return parent


def parse_audio_metadata(
    path: str | Path, *, timeout_seconds: int = 60
) -> AudioFileMetadata:
    source = Path(path).expanduser().resolve()
    if not source.is_file() or not is_supported_audio_file(source):
        raise ValueError("音频文件不存在或格式不受支持")

    parser_errors: list[str] = []
    try:
        mutagen_data = _read_with_mutagen(source)
    except ValueError as exc:
        mutagen_data = {}
        parser_errors.append(str(exc))
    try:
        probe_data = _read_with_ffprobe(source, timeout_seconds=timeout_seconds)
    except AudioInspectionError as exc:
        if exc.code in {"AUDIO_STREAM_NOT_FOUND", "AUDIO_VIDEO_STREAM_UNSUPPORTED"}:
            raise
        probe_data = {}
        parser_errors.append(str(exc))
    except ValueError as exc:
        probe_data = {}
        parser_errors.append(str(exc))
    if source.suffix.lower() not in LEGACY_AUDIO_EXTS and not probe_data:
        if parser_errors:
            raise AudioInspectionError("AUDIO_METADATA_INVALID", parser_errors[-1])
        raise AudioInspectionError(
            "AUDIO_PROBE_REQUIRED",
            "该音频格式需要服务器安装 ffprobe 后才能导入",
        )
    if not mutagen_data and not probe_data:
        detail = "；".join(parser_errors[-2:])
        raise AudioInspectionError(
            "AUDIO_METADATA_INVALID",
            detail or "无法读取音频元数据：服务器需要 Mutagen 或 ffprobe，请安装后重试",
        )

    merged = _merge_metadata(mutagen_data, probe_data)
    raw_codec = str(merged.get("codec") or "").strip().lower()
    codec = _normalize_audio_codec(raw_codec)
    if not codec:
        raise AudioInspectionError(
            "AUDIO_STREAM_NOT_FOUND", "音频文件没有可识别的音频流"
        )
    duration_ms = _positive_int(merged.get("duration_ms"))
    if duration_ms is None:
        raise AudioInspectionError(
            "AUDIO_METADATA_INVALID",
            "无法读取音频时长，文件可能损坏或编码不受支持",
        )

    chapters = tuple(
        AudioChapterMetadata(
            title=str(item.get("title") or f"第 {index + 1} 章"),
            start_ms=max(0, int(item.get("start_ms") or 0)),
            end_ms=max(0, int(item.get("end_ms") or 0)),
        )
        for index, item in enumerate(merged.get("chapters") or [])
        if int(item.get("end_ms") or 0) > int(item.get("start_ms") or 0)
    )
    if len(chapters) > MAX_AUDIO_CHAPTERS:
        raise AudioInspectionError(
            "AUDIO_METADATA_INVALID",
            f"音频章节超过 {MAX_AUDIO_CHAPTERS} 个，文件可能损坏或标签异常",
        )
    return AudioFileMetadata(
        path=source,
        title=_clean_text(merged.get("title")),
        album=_clean_text(merged.get("album")),
        author=_clean_text(merged.get("author")),
        narrator=_clean_text(merged.get("narrator")),
        duration_ms=duration_ms,
        codec=codec,
        bitrate=_positive_int(merged.get("bitrate")),
        sample_rate=_positive_int(merged.get("sample_rate")),
        channels=_positive_int(merged.get("channels")),
        disc_number=_tag_number(merged.get("disc_number")),
        track_number=_tag_number(merged.get("track_number")),
        series_name=_clean_text(merged.get("series_name")),
        volume_index=parse_structured_volume_index(merged.get("volume_index")),
        chapters=chapters,
        raw_tags=merged.get("raw_tags")
        if isinstance(merged.get("raw_tags"), dict)
        else {},
        cover_data=merged.get("cover_data")
        if isinstance(merged.get("cover_data"), bytes)
        else None,
        cover_extension=_clean_text(merged.get("cover_extension")),
    )


def _read_with_ffprobe(path: Path, *, timeout_seconds: int) -> dict[str, Any]:
    configured = os.environ.get("FFPROBE_PATH")
    executable = (
        configured
        if configured and Path(configured).is_file()
        else shutil.which("ffprobe")
    )
    if not executable and Path("/opt/homebrew/bin/ffprobe").is_file():
        executable = "/opt/homebrew/bin/ffprobe"
    if not executable:
        return {}
    command = [
        executable,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        str(path),
    ]
    returncode, stdout, stderr = _run_process_with_output_limit(
        command, timeout_seconds=max(1, timeout_seconds)
    )
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise AudioInspectionError(
            "AUDIO_METADATA_INVALID",
            f"音频文件无法解析：{detail[-1] if detail else 'ffprobe 返回错误'}",
        )
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AudioInspectionError(
            "AUDIO_METADATA_INVALID", "ffprobe 返回了无效的音频元数据"
        ) from exc
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    audio_stream = next(
        (item for item in streams if item.get("codec_type") == "audio"), None
    )
    if not isinstance(audio_stream, dict):
        raise AudioInspectionError("AUDIO_STREAM_NOT_FOUND", "文件中没有音频流")
    video_streams = [
        item
        for item in streams
        if isinstance(item, dict)
        and item.get("codec_type") == "video"
        and not (
            isinstance(item.get("disposition"), dict)
            and bool(item["disposition"].get("attached_pic"))
        )
    ]
    if video_streams:
        raise AudioInspectionError(
            "AUDIO_VIDEO_STREAM_UNSUPPORTED",
            "文件包含视频流，不能作为有声书音频导入",
        )
    format_data = (
        payload.get("format") if isinstance(payload.get("format"), dict) else {}
    )
    tags: dict[str, Any] = {}
    for source_tags in (format_data.get("tags"), audio_stream.get("tags")):
        if isinstance(source_tags, dict):
            tags.update({str(key).lower(): value for key, value in source_tags.items()})
    duration = audio_stream.get("duration") or format_data.get("duration")
    chapters = []
    for index, chapter in enumerate(payload.get("chapters") or []):
        if not isinstance(chapter, dict):
            continue
        chapter_tags = (
            chapter.get("tags") if isinstance(chapter.get("tags"), dict) else {}
        )
        start_ms = _seconds_to_ms(chapter.get("start_time"))
        end_ms = _seconds_to_ms(chapter.get("end_time"))
        if end_ms > start_ms:
            chapters.append(
                {
                    "title": chapter_tags.get("title") or f"第 {index + 1} 章",
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                }
            )
    result = {
        "title": _first_tag(tags, "title"),
        "album": _first_tag(tags, "album"),
        "author": _first_tag(tags, "album_artist", "albumartist", "artist", "author"),
        "narrator": _first_tag(tags, "narrator", "readby", "reader", "composer"),
        "duration_ms": _seconds_to_ms(duration),
        "codec": audio_stream.get("codec_name"),
        "bitrate": audio_stream.get("bit_rate") or format_data.get("bit_rate"),
        "sample_rate": audio_stream.get("sample_rate"),
        "channels": audio_stream.get("channels"),
        "disc_number": _first_tag(tags, "disc", "discnumber"),
        "track_number": _first_tag(tags, "track", "tracknumber"),
        "series_name": _first_tag(tags, "series", "series_name", "seriesname"),
        "volume_index": _first_tag(
            tags,
            "volume",
            "volume_number",
            "volumenumber",
            "series_index",
            "seriesindex",
            "series-part",
            "series_part",
        ),
        "chapters": chapters,
        "raw_tags": {"ffprobe": tags},
    }
    _repair_audio_metadata_text(result, source="ffprobe")
    return result


def _run_process_with_output_limit(
    command: list[str],
    *,
    timeout_seconds: int,
    max_stdout_bytes: int = MAX_FFPROBE_STDOUT_BYTES,
    max_stderr_bytes: int = MAX_FFPROBE_STDERR_BYTES,
) -> tuple[int, bytes, bytes]:
    """Run ffprobe without allowing a malformed file to exhaust RAM."""

    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except OSError as exc:
        raise ValueError(f"ffprobe 读取音频失败：{exc}") from exc
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise ValueError("ffprobe 读取音频失败：无法捕获子进程输出")

    selector = selectors.DefaultSelector()
    selector.register(
        process.stdout, selectors.EVENT_READ, ("stdout", max_stdout_bytes)
    )
    selector.register(
        process.stderr, selectors.EVENT_READ, ("stderr", max_stderr_bytes)
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + max(1, timeout_seconds)
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise ValueError(f"ffprobe 读取音频超时（{timeout_seconds} 秒）")
            events = selector.select(timeout=min(0.25, remaining))
            if not events and process.poll() is not None:
                # Pipes can still contain buffered bytes after process exit.
                events = [
                    (key, selectors.EVENT_READ) for key in selector.get_map().values()
                ]
            for key, _mask in events:
                stream_name, limit = key.data
                chunk = os.read(key.fd, 64 * 1024)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffer = buffers[stream_name]
                if len(buffer) + len(chunk) > limit:
                    process.kill()
                    process.wait()
                    raise ValueError(
                        f"ffprobe {stream_name} 输出超过 {limit} bytes，文件元数据异常"
                    )
                buffer.extend(chunk)
        remaining = max(0.01, deadline - time.monotonic())
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.wait()
            raise ValueError(f"ffprobe 读取音频超时（{timeout_seconds} 秒）") from exc
        return returncode, bytes(buffers["stdout"]), bytes(buffers["stderr"])
    finally:
        selector.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            process.kill()
            process.wait()


def _read_with_mutagen(path: Path) -> dict[str, Any]:
    try:
        import mutagen  # type: ignore[import-not-found]
    except ImportError:
        return {}
    try:
        audio = mutagen.File(str(path), easy=False)
    except Exception as exc:
        raise ValueError(f"Mutagen 读取音频失败：{exc}") from exc
    if audio is None:
        return {}
    tags = getattr(audio, "tags", None)
    raw_tags = _serializable_tags(tags)
    encoding_repairs: list[dict[str, str]] = []
    values = _normalized_mutagen_tags(tags, repairs=encoding_repairs)
    info = getattr(audio, "info", None)
    chapters: list[dict[str, Any]] = []
    for index, chapter in enumerate(getattr(audio, "chapters", None) or []):
        start_ms = _seconds_to_ms(getattr(chapter, "start", None))
        end_ms = _seconds_to_ms(getattr(chapter, "end", None))
        if end_ms > start_ms:
            chapter_title, repair = _repair_misdecoded_text(
                str(getattr(chapter, "title", None) or f"第 {index + 1} 章")
            )
            if repair:
                encoding_repairs.append({"tag": f"chapter:{index + 1}", **repair})
            chapters.append(
                {"title": chapter_title, "start_ms": start_ms, "end_ms": end_ms}
            )
    id3_chapters = []
    if tags is not None and hasattr(tags, "getall"):
        try:
            id3_chapters = list(tags.getall("CHAP"))
        # ID3 implementations can raise plugin-specific errors at this adapter boundary.
        except Exception:  # noqa: BLE001
            id3_chapters = []
    if id3_chapters:
        chapters = []
        for index, chapter in enumerate(
            sorted(id3_chapters, key=lambda item: int(getattr(item, "start_time", 0)))
        ):
            sub_frames = getattr(chapter, "sub_frames", None) or {}
            title_frame = (
                next(iter(sub_frames.getall("TIT2")), None)
                if hasattr(sub_frames, "getall")
                else None
            )
            raw_title = str(getattr(title_frame, "text", [f"第 {index + 1} 章"])[0])
            chapter_title, repair = _repair_misdecoded_text(
                raw_title,
                declared_encoding=_mutagen_declared_text_encoding(title_frame),
            )
            if repair:
                encoding_repairs.append({"tag": f"CHAP:{index + 1}:TIT2", **repair})
            chapters.append(
                {
                    "title": chapter_title,
                    "start_ms": int(getattr(chapter, "start_time", 0)),
                    "end_ms": int(getattr(chapter, "end_time", 0)),
                }
            )
    cover_data, cover_extension = _mutagen_cover(tags)
    if cover_data and len(cover_data) > MAX_EMBEDDED_COVER_BYTES:
        raw_tags["coverWarning"] = (
            f"embedded cover ignored: {len(cover_data)} bytes exceeds {MAX_EMBEDDED_COVER_BYTES}"
        )
        cover_data = None
        cover_extension = None
    if encoding_repairs:
        raw_tags["encodingRepairs"] = encoding_repairs
    return {
        "title": _first_tag(values, "title", "©nam", "tit2"),
        "album": _first_tag(values, "album", "©alb", "talb"),
        "author": _first_tag(
            values,
            "albumartist",
            "album artist",
            "aart",
            "©art",
            "artist",
            "tpe1",
            "tpe2",
        ),
        "narrator": _first_tag(
            values, "narrator", "readby", "reader", "composer", "tcom"
        ),
        "duration_ms": _seconds_to_ms(getattr(info, "length", None)),
        "codec": _mutagen_codec(path, info),
        "bitrate": getattr(info, "bitrate", None),
        "sample_rate": getattr(info, "sample_rate", None),
        "channels": getattr(info, "channels", None),
        "disc_number": _first_tag(values, "discnumber", "disk", "tpos"),
        "track_number": _first_tag(values, "tracknumber", "trkn", "trck"),
        "series_name": _first_tag(values, "series", "series_name", "seriesname"),
        "volume_index": _first_tag(
            values,
            "volume",
            "volume_number",
            "volumenumber",
            "series_index",
            "seriesindex",
            "series-part",
            "series_part",
        ),
        "chapters": chapters,
        "raw_tags": {"mutagen": raw_tags},
        "cover_data": cover_data,
        "cover_extension": cover_extension,
    }


def _merge_metadata(
    primary: dict[str, Any], fallback: dict[str, Any]
) -> dict[str, Any]:
    output = dict(fallback)
    for key, value in primary.items():
        if value not in (None, "", [], {}, ()):
            output[key] = value
    # ffprobe reports the actual stream codec; container-based guesses from
    # Mutagen must not turn ALAC/AC-3 in an M4A container into a false AAC.
    if fallback.get("codec"):
        output["codec"] = fallback["codec"]
    raw: dict[str, Any] = {}
    for item in (fallback.get("raw_tags"), primary.get("raw_tags")):
        if isinstance(item, dict):
            raw.update(item)
    output["raw_tags"] = raw
    return output


def _normalized_mutagen_tags(
    tags: Any,
    *,
    repairs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if tags is None:
        return {}
    output: dict[str, Any] = {}
    try:
        items = tags.items()
    except AttributeError:
        return output
    for key, value in items:
        frame = value
        normalized_key = str(key).lower()
        if normalized_key.startswith("txxx:"):
            normalized_key = normalized_key.split(":", 1)[1].strip().lower()
        if hasattr(value, "text"):
            value = value.text
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if isinstance(value, tuple) and value:
            value = value[0]
        if isinstance(value, str):
            value, repair = _repair_misdecoded_text(
                value,
                declared_encoding=_mutagen_declared_text_encoding(frame),
            )
            if repair and repairs is not None:
                repairs.append({"tag": str(key), **repair})
        output[normalized_key] = value
    return output


def _mutagen_declared_text_encoding(frame: Any) -> str | None:
    value = getattr(frame, "encoding", None)
    try:
        return MUTAGEN_TEXT_ENCODINGS.get(int(value))
    except (TypeError, ValueError):
        return None


def _repair_audio_metadata_text(metadata: dict[str, Any], *, source: str) -> None:
    repairs: list[dict[str, str]] = []
    for field_name in ("title", "album", "author", "narrator"):
        value = metadata.get(field_name)
        if not isinstance(value, str):
            continue
        repaired, repair = _repair_misdecoded_text(value)
        metadata[field_name] = repaired
        if repair:
            repairs.append({"tag": field_name, **repair})
    for index, chapter in enumerate(metadata.get("chapters") or []):
        if not isinstance(chapter, dict) or not isinstance(chapter.get("title"), str):
            continue
        repaired, repair = _repair_misdecoded_text(chapter["title"])
        chapter["title"] = repaired
        if repair:
            repairs.append({"tag": f"chapter:{index + 1}", **repair})
    if not repairs:
        return
    raw_tags = metadata.setdefault("raw_tags", {})
    if isinstance(raw_tags, dict):
        raw_tags.setdefault("encodingRepairs", []).extend(
            {"source": source, **repair} for repair in repairs
        )


def _repair_misdecoded_text(
    value: str,
    *,
    declared_encoding: str | None = None,
) -> tuple[str, dict[str, str] | None]:
    """Conservatively repair legacy tag bytes decoded as Latin-1.

    Old tag writers commonly stored bytes in a local encoding while marking
    the frame as ISO-8859-1. Mutagen correctly follows that declaration, so
    the original bytes remain reversibly represented by U+0000..U+00FF. We
    only replace the text when the current value has strong mojibake signals,
    a candidate round-trips byte-for-byte, and its quality is materially
    better. Plain ASCII and normal Western text are intentionally untouched.
    """

    if not value or value.isascii():
        return value, None
    suspicion = _mojibake_suspicion(value)
    if suspicion < 4:
        return value, None
    try:
        raw = value.encode("latin-1", errors="strict")
    except UnicodeEncodeError:
        return value, None

    original_score = _decoded_text_quality(value)
    candidates: list[tuple[float, int, str, str]] = []
    for priority, encoding in enumerate(MISDECLARED_TEXT_ENCODING_CANDIDATES):
        try:
            decoded = raw.decode(encoding, errors="strict")
            if decoded.encode(encoding, errors="strict") != raw:
                continue
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        if decoded == value or not decoded.strip() or "\ufffd" in decoded:
            continue
        score = _candidate_decoding_quality(decoded, encoding)
        candidates.append((score, -priority, encoding, decoded))
    if not candidates:
        return value, None

    candidates.sort(reverse=True)
    best_score, _priority, encoding, decoded = candidates[0]
    if best_score < original_score + 4:
        return value, None
    # Bytes in the C1 range are common Shift-JIS lead bytes. If a short
    # all-ideograph value is equally plausible as GB18030 and Shift-JIS, there
    # is not enough evidence to choose safely (for example a Japanese name
    # with no kana), so retain the declared value for manual correction.
    shift_jis_candidate = next(
        (candidate for candidate in candidates if candidate[2] == "shift_jis"), None
    )
    if (
        encoding == "gb18030"
        and shift_jis_candidate
        and best_score - shift_jis_candidate[0] < 1
        and any(0x80 <= byte <= 0x9F for byte in raw)
        and _contains_only_cjk_letters(decoded)
        and _contains_only_cjk_letters(shift_jis_candidate[3])
    ):
        return value, None
    return decoded, {
        "declaredEncoding": declared_encoding or "unknown",
        "detectedEncoding": encoding,
        "original": value,
        "repaired": decoded,
    }


def _mojibake_suspicion(value: str) -> int:
    score = 0
    score += value.count("\ufffd") * 10
    score += sum(
        8
        for character in value
        if unicodedata.category(character) == "Cc" and character not in "\t\r\n"
    )
    score += len(re.findall(r"(?:Ã.|Â.|â..|ð.|Ð.|Ñ.|¡[¶·])", value)) * 4
    score += len(re.findall(r"[\u00c0-\u00ff]{4,}", value)) * 5
    latin1_non_ascii = sum(
        1 for character in value if "\u00a0" <= character <= "\u00ff"
    )
    if latin1_non_ascii >= 4 and latin1_non_ascii / max(1, len(value)) >= 0.35:
        score += 5
    return score


def _decoded_text_quality(value: str) -> float:
    score = 0.0
    for character in value:
        category = unicodedata.category(character)
        if character == "\ufffd":
            score -= 12
        elif category == "Cc" and character not in "\t\r\n":
            score -= 10
        elif category[0] in {"L", "N"}:
            score += 1
        elif character.isspace() or category[0] == "P":
            score += 0.25
        elif category[0] == "S":
            score -= 0.25
    score -= _mojibake_suspicion(value) * 1.5
    if any(_is_cjk_character(character) for character in value):
        score += 3
    if re.search(r"[\u3040-\u30ff]", value):
        score += 3
    if re.search(r"《[^》]+》|「[^」]+」|『[^』]+』", value):
        score += 2
    return score


def _candidate_decoding_quality(value: str, encoding: str) -> float:
    score = _decoded_text_quality(value)
    # A strict, byte-for-byte UTF-8 round trip is much stronger evidence than
    # a coincidentally valid two-byte legacy decoding.
    if encoding == "utf-8":
        score += 6
    halfwidth_katakana = len(re.findall(r"[\uff61-\uff9f]", value))
    # A dense run of halfwidth katakana is a frequent accidental Shift-JIS
    # interpretation of valid Western or GBK bytes. Legitimate Japanese tags
    # overwhelmingly use fullwidth kana, so require much stronger evidence.
    score -= halfwidth_katakana * 4
    has_cjk = any(_is_cjk_character(character) for character in value)
    has_fullwidth_kana = bool(re.search(r"[\u3040-\u30ff]", value))
    if encoding in {"gb18030", "big5"} and has_cjk and has_fullwidth_kana:
        score -= 5
    if encoding == "shift_jis" and has_fullwidth_kana:
        score += 2
    return score


def _contains_only_cjk_letters(value: str) -> bool:
    significant = [character for character in value if not character.isspace()]
    return bool(significant) and all(
        _is_cjk_character(character) for character in significant
    )


def _is_cjk_character(character: str) -> bool:
    return 0x3400 <= ord(character) <= 0x9FFF


def _serializable_tags(tags: Any) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if tags is None or not hasattr(tags, "items"):
        return output
    for key, value in tags.items():
        if str(key).lower().startswith(("apic", "covr")):
            output[str(key)] = "<embedded cover>"
            continue
        if hasattr(value, "text"):
            value = value.text
        if isinstance(value, bytes):
            output[str(key)] = f"<bytes:{len(value)}>"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            output[str(key)] = value
        elif isinstance(value, (list, tuple)):
            output[str(key)] = [str(item) for item in value]
        else:
            output[str(key)] = str(value)
    return output


def _mutagen_cover(tags: Any) -> tuple[bytes | None, str | None]:
    if tags is None:
        return None, None
    if hasattr(tags, "getall"):
        try:
            picture = next(iter(tags.getall("APIC")), None)
        # Cover frames come from third-party tag implementations with no common error type.
        except Exception:  # noqa: BLE001
            picture = None
        data = getattr(picture, "data", None)
        if isinstance(data, bytes):
            mime = str(getattr(picture, "mime", "") or "").lower()
            return data, ".png" if "png" in mime else ".jpg"
    try:
        covers = tags.get("covr") or tags.get("cover")
    except AttributeError:
        covers = None
    if isinstance(covers, (list, tuple)) and covers:
        data = bytes(covers[0])
        return data, ".png" if data.startswith(b"\x89PNG") else ".jpg"
    return None, None


def _mutagen_codec(path: Path, info: Any) -> str | None:
    if path.suffix.lower() == ".mp3":
        return "mp3"
    # MP4 is a container: .m4a/.m4b may contain AAC, ALAC, AC-3, or another
    # stream. Never infer AAC from the extension because that would silently
    # admit codecs outside the V1 playback boundary.
    codec = (
        str(getattr(info, "codec", "") or getattr(info, "codec_description", ""))
        .strip()
        .lower()
    )
    return _normalize_audio_codec(codec)


def _normalize_audio_codec(value: Any) -> str | None:
    """Normalize parser-specific codec names without trusting the MP4 container.

    Mutagen reports MPEG-4 Audio Object Types as RFC 6381 strings on some
    files (for example ``mp4a.40.2`` for AAC-LC) while ffprobe reports the
    same stream as ``aac``. Known aliases are canonicalized for the Reader
    contract; other ffprobe codec names remain intact for runtime playback
    capability checks.
    """

    codec = str(value or "").strip().lower()
    if not codec:
        return None
    if "alac" in codec or "apple lossless" in codec:
        return "alac"
    if "e-ac-3" in codec or "eac3" in codec or "ec-3" in codec:
        return "eac3"
    if "ac-3" in codec or "ac3" in codec:
        return "ac3"
    object_type = re.fullmatch(r"mp4a\.40\.(\d+)", codec)
    if object_type and int(object_type.group(1)) in AAC_RFC6381_OBJECT_TYPES:
        return "aac"
    if "aac" in codec:
        return "aac"
    if "mpeg" in codec and ("layer 3" in codec or "layer iii" in codec):
        return "mp3"
    return codec or None


def _first_tag(tags: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = tags.get(key.lower())
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value not in (None, ""):
            return value
    return None


def _tag_number(value: Any) -> int | None:
    if isinstance(value, (tuple, list)) and value:
        value = value[0]
        if isinstance(value, (tuple, list)) and value:
            value = value[0]
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else None


def _seconds_to_ms(value: Any) -> int:
    try:
        return max(0, round(float(value) * 1000))
    except (TypeError, ValueError):
        return 0


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clean_text(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned or None


def _natural_audio_key(path: Path) -> tuple[Any, ...]:
    parts: list[Any] = []
    for segment in path.parts[-2:]:
        parts.extend(
            int(item) if item.isdigit() else item.casefold()
            for item in re.split(r"(\d+)", segment)
        )
    return tuple(parts)
