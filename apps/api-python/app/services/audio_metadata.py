from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.book_identity import (
    UNKNOWN_AUTHOR,
    normalize_identity_part,
    recognize_book_identity_with_regex,
)


SUPPORTED_AUDIO_EXTS = {".m4b", ".m4a", ".mp3"}
SUPPORTED_AUDIO_CODECS = {"aac", "mp3"}
AAC_RFC6381_OBJECT_TYPES = {2, 5, 29}
MAX_AUDIO_BUNDLE_TRACKS = 1000
MAX_AUDIO_CHAPTERS = 10_000
MAX_EMBEDDED_COVER_BYTES = 20 * 1024 * 1024
MAX_FFPROBE_STDOUT_BYTES = 16 * 1024 * 1024
MAX_FFPROBE_STDERR_BYTES = 256 * 1024
DISC_DIRECTORY_PATTERN = re.compile(
    r"^(?:cd|disc|disk|碟|盘)\s*[-_. ]*\d+(?:\s*(?:of|/|[-–—])\s*\d+)?$",
    re.I,
)


@dataclass(frozen=True)
class AudioChapterMetadata:
    title: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AudioFileMetadata:
    path: Path
    title: str | None
    album: str | None
    author: str | None
    narrator: str | None
    duration_ms: int
    codec: str
    bitrate: int | None
    sample_rate: int | None
    channels: int | None
    disc_number: int | None
    track_number: int | None
    chapters: tuple[AudioChapterMetadata, ...] = ()
    raw_tags: dict[str, Any] = field(default_factory=dict)
    cover_data: bytes | None = None
    cover_extension: str | None = None


@dataclass(frozen=True)
class AudioVolumeDirectory:
    path: Path
    title: str
    volume_index: float | None
    author: str | None
    files: tuple[Path, ...]


@dataclass(frozen=True)
class AudioBundleStructure:
    root: Path
    title: str
    author: str | None
    volumes: tuple[AudioVolumeDirectory, ...]

    @property
    def files(self) -> tuple[Path, ...]:
        return tuple(path for volume in self.volumes for path in volume.files)

    @property
    def is_multi_volume(self) -> bool:
        return len(self.volumes) > 1 or bool(self.volumes and self.volumes[0].path != self.root)


def is_supported_audio_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_AUDIO_EXTS


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
    except Exception:
        return None, None
    if audio is None:
        return None, None
    values = _normalized_mutagen_tags(getattr(audio, "tags", None))
    album = _clean_text(_first_tag(values, "album", "©alb", "talb"))
    author = _clean_text(_first_tag(values, "albumartist", "album artist", "aart", "©art", "artist", "tpe1", "tpe2"))
    return album.casefold() if album else None, author.casefold() if author else None


def _directory_identity(path: Path) -> tuple[str, str | None, float | None]:
    identity = recognize_book_identity_with_regex(f"{path.name}.epub")
    author = identity.author if identity.author != UNKNOWN_AUTHOR else None
    return identity.title.strip() or path.name, author, identity.volume_index


def _directory_audio_files(path: Path) -> list[Path]:
    files = [item.resolve() for item in path.iterdir() if item.is_file() and is_supported_audio_file(item)]
    for child in path.iterdir():
        if child.is_dir() and DISC_DIRECTORY_PATTERN.match(child.name.strip()):
            files.extend(item.resolve() for item in child.iterdir() if item.is_file() and is_supported_audio_file(item))
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

    root_title, root_author, _root_volume_index = _directory_identity(root)
    direct_files = _directory_audio_files(root)
    root_key = normalize_identity_part(root_title)
    matched_volumes: list[AudioVolumeDirectory] = []
    for child in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: _natural_audio_key(item)):
        if DISC_DIRECTORY_PATTERN.match(child.name.strip()):
            continue
        child_files = _directory_audio_files(child)
        if not child_files:
            continue
        child_title, child_author, volume_index = _directory_identity(child)
        child_key = normalize_identity_part(child_title)
        title_contains_parent = bool(root_key and child_key and root_key != child_key and root_key in child_key)
        if volume_index is None and not title_contains_parent:
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
        raise ValueError("有声书书名目录不能同时包含直属音轨和卷目录，请整理为单卷或多卷结构后重试")
    if matched_volumes:
        matched_volumes.sort(
            key=lambda volume: (
                volume.volume_index is None,
                volume.volume_index if volume.volume_index is not None else float("inf"),
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

    result = AudioBundleStructure(root=root, title=root_title, author=root_author, volumes=volumes)
    if len(result.files) > MAX_AUDIO_BUNDLE_TRACKS:
        raise ValueError(f"有声书分轨超过 {MAX_AUDIO_BUNDLE_TRACKS} 个，请拆分后导入")
    return result


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
    grandparent = parent.parent
    if grandparent != parent:
        try:
            structure = inspect_audio_bundle(grandparent)
        except (OSError, ValueError):
            structure = None
        if structure and any(volume.path == parent for volume in structure.volumes):
            return grandparent
    if monitor_root is not None:
        try:
            if parent == Path(monitor_root).expanduser().resolve():
                return source
        except OSError:
            return source
    return parent


def parse_audio_metadata(path: str | Path, *, timeout_seconds: int = 60) -> AudioFileMetadata:
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
    except ValueError as exc:
        probe_data = {}
        parser_errors.append(str(exc))
    if not mutagen_data and not probe_data:
        detail = "；".join(parser_errors[-2:])
        raise ValueError(detail or "无法读取音频元数据：服务器需要 Mutagen 或 ffprobe，请安装后重试")

    merged = _merge_metadata(mutagen_data, probe_data)
    raw_codec = str(merged.get("codec") or "").strip().lower()
    codec = _normalize_audio_codec(raw_codec)
    if not codec:
        raise ValueError("音频文件没有可识别的音频流")
    if codec not in SUPPORTED_AUDIO_CODECS:
        raise ValueError(f"音频编码 {codec} 暂不支持；当前支持 MP3 与 AAC")
    duration_ms = _positive_int(merged.get("duration_ms"))
    if duration_ms is None:
        raise ValueError("无法读取音频时长，文件可能损坏或编码不受支持")

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
        raise ValueError(f"音频章节超过 {MAX_AUDIO_CHAPTERS} 个，文件可能损坏或标签异常")
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
        chapters=chapters,
        raw_tags=merged.get("raw_tags") if isinstance(merged.get("raw_tags"), dict) else {},
        cover_data=merged.get("cover_data") if isinstance(merged.get("cover_data"), bytes) else None,
        cover_extension=_clean_text(merged.get("cover_extension")),
    )


def _read_with_ffprobe(path: Path, *, timeout_seconds: int) -> dict[str, Any]:
    configured = os.environ.get("FFPROBE_PATH")
    executable = configured if configured and Path(configured).is_file() else shutil.which("ffprobe")
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
    returncode, stdout, stderr = _run_process_with_output_limit(command, timeout_seconds=max(1, timeout_seconds))
    if returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise ValueError(f"音频文件无法解析：{detail[-1] if detail else 'ffprobe 返回错误'}")
    try:
        payload = json.loads(stdout.decode("utf-8", errors="strict") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ffprobe 返回了无效的音频元数据") from exc
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    audio_stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not isinstance(audio_stream, dict):
        raise ValueError("文件中没有音频流")
    format_data = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    tags: dict[str, Any] = {}
    for source_tags in (format_data.get("tags"), audio_stream.get("tags")):
        if isinstance(source_tags, dict):
            tags.update({str(key).lower(): value for key, value in source_tags.items()})
    duration = audio_stream.get("duration") or format_data.get("duration")
    chapters = []
    for index, chapter in enumerate(payload.get("chapters") or []):
        if not isinstance(chapter, dict):
            continue
        chapter_tags = chapter.get("tags") if isinstance(chapter.get("tags"), dict) else {}
        start_ms = _seconds_to_ms(chapter.get("start_time"))
        end_ms = _seconds_to_ms(chapter.get("end_time"))
        if end_ms > start_ms:
            chapters.append({"title": chapter_tags.get("title") or f"第 {index + 1} 章", "start_ms": start_ms, "end_ms": end_ms})
    return {
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
        "chapters": chapters,
        "raw_tags": {"ffprobe": tags},
    }


def _run_process_with_output_limit(
    command: list[str],
    *,
    timeout_seconds: int,
    max_stdout_bytes: int = MAX_FFPROBE_STDOUT_BYTES,
    max_stderr_bytes: int = MAX_FFPROBE_STDERR_BYTES,
) -> tuple[int, bytes, bytes]:
    """Run ffprobe without allowing a malformed file to exhaust RAM."""

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise ValueError(f"ffprobe 读取音频失败：{exc}") from exc
    if process.stdout is None or process.stderr is None:
        process.kill()
        process.wait()
        raise ValueError("ffprobe 读取音频失败：无法捕获子进程输出")

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, ("stdout", max_stdout_bytes))
    selector.register(process.stderr, selectors.EVENT_READ, ("stderr", max_stderr_bytes))
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
                events = [(key, selectors.EVENT_READ) for key in selector.get_map().values()]
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
                    raise ValueError(f"ffprobe {stream_name} 输出超过 {limit} bytes，文件元数据异常")
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
    values = _normalized_mutagen_tags(tags)
    info = getattr(audio, "info", None)
    chapters: list[dict[str, Any]] = []
    for index, chapter in enumerate(getattr(audio, "chapters", None) or []):
        start_ms = _seconds_to_ms(getattr(chapter, "start", None))
        end_ms = _seconds_to_ms(getattr(chapter, "end", None))
        if end_ms > start_ms:
            chapters.append({"title": getattr(chapter, "title", None) or f"第 {index + 1} 章", "start_ms": start_ms, "end_ms": end_ms})
    id3_chapters = []
    if tags is not None and hasattr(tags, "getall"):
        try:
            id3_chapters = list(tags.getall("CHAP"))
        except Exception:
            id3_chapters = []
    if id3_chapters:
        chapters = []
        for index, chapter in enumerate(sorted(id3_chapters, key=lambda item: int(getattr(item, "start_time", 0)))):
            sub_frames = getattr(chapter, "sub_frames", None) or {}
            title_frame = next(iter(sub_frames.getall("TIT2")), None) if hasattr(sub_frames, "getall") else None
            chapters.append(
                {
                    "title": str(getattr(title_frame, "text", [f"第 {index + 1} 章"])[0]),
                    "start_ms": int(getattr(chapter, "start_time", 0)),
                    "end_ms": int(getattr(chapter, "end_time", 0)),
                }
            )
    cover_data, cover_extension = _mutagen_cover(tags)
    if cover_data and len(cover_data) > MAX_EMBEDDED_COVER_BYTES:
        raw_tags["coverWarning"] = f"embedded cover ignored: {len(cover_data)} bytes exceeds {MAX_EMBEDDED_COVER_BYTES}"
        cover_data = None
        cover_extension = None
    return {
        "title": _first_tag(values, "title", "©nam", "tit2"),
        "album": _first_tag(values, "album", "©alb", "talb"),
        "author": _first_tag(values, "albumartist", "album artist", "aart", "©art", "artist", "tpe1", "tpe2"),
        "narrator": _first_tag(values, "narrator", "readby", "reader", "composer", "tcom"),
        "duration_ms": _seconds_to_ms(getattr(info, "length", None)),
        "codec": _mutagen_codec(path, info),
        "bitrate": getattr(info, "bitrate", None),
        "sample_rate": getattr(info, "sample_rate", None),
        "channels": getattr(info, "channels", None),
        "disc_number": _first_tag(values, "discnumber", "disk", "tpos"),
        "track_number": _first_tag(values, "tracknumber", "trkn", "trck"),
        "chapters": chapters,
        "raw_tags": {"mutagen": raw_tags},
        "cover_data": cover_data,
        "cover_extension": cover_extension,
    }


def _merge_metadata(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
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


def _normalized_mutagen_tags(tags: Any) -> dict[str, Any]:
    if tags is None:
        return {}
    output: dict[str, Any] = {}
    try:
        items = tags.items()
    except AttributeError:
        return output
    for key, value in items:
        normalized_key = str(key).lower()
        if normalized_key.startswith("txxx:"):
            normalized_key = normalized_key.split(":", 1)[1].strip().lower()
        if hasattr(value, "text"):
            value = getattr(value, "text")
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if isinstance(value, tuple) and value:
            value = value[0]
        output[normalized_key] = value
    return output


def _serializable_tags(tags: Any) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if tags is None or not hasattr(tags, "items"):
        return output
    for key, value in tags.items():
        if str(key).lower().startswith(("apic", "covr")):
            output[str(key)] = "<embedded cover>"
            continue
        if hasattr(value, "text"):
            value = getattr(value, "text")
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
        except Exception:
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
    codec = str(getattr(info, "codec", "") or getattr(info, "codec_description", "")).strip().lower()
    return _normalize_audio_codec(codec)


def _normalize_audio_codec(value: Any) -> str | None:
    """Normalize parser-specific codec names without trusting the MP4 container.

    Mutagen reports MPEG-4 Audio Object Types as RFC 6381 strings on some
    files (for example ``mp4a.40.2`` for AAC-LC) while ffprobe reports the
    same stream as ``aac``.  Only the common AAC object types supported by
    the browser playback boundary are admitted; unknown ``mp4a`` values stay
    unsupported instead of being guessed from the .m4a/.m4b extension.
    """

    codec = str(value or "").strip().lower()
    if not codec:
        return None
    if "alac" in codec or "apple lossless" in codec:
        return "alac"
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
        parts.extend(int(item) if item.isdigit() else item.casefold() for item in re.split(r"(\d+)", segment))
    return tuple(parts)
