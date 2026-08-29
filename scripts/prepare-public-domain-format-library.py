#!/usr/bin/env python3
"""Prepare compact, provenance-recorded format fixtures from public-domain Alice sources."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

TITLE_PREFIX = "公开格式测试"
SOURCES = {
    "epub": "https://www.gutenberg.org/ebooks/11.epub3.images",
    "text": "https://www.gutenberg.org/cache/epub/11/pg11.txt",
    "mobi": "https://www.gutenberg.org/ebooks/11.kindle.images",
    "azw3": "https://www.gutenberg.org/ebooks/11.kf8.images",
    "illustrated_epub": "https://www.gutenberg.org/ebooks/28885.epub3.images",
    "pdf": "https://www.gutenberg.org/files/11/old/old/11-pdf.pdf",
    "audio": (
        "https://archive.org/download/"
        "alicesadventuresinwonderland_1902_librivox/"
        "alicesadventuresinwonderland_01_carroll_64kb.mp3"
    ),
}

AUDIO_EXTENSIONS = (
    ".aac",
    ".ac3",
    ".adx",
    ".aif",
    ".aifc",
    ".aiff",
    ".amr",
    ".aptx",
    ".aptxhd",
    ".au",
    ".caf",
    ".dts",
    ".eac3",
    ".flac",
    ".g722",
    ".g726",
    ".gsm",
    ".lbc",
    ".m4a",
    ".m4b",
    ".m4r",
    ".mka",
    ".mlp",
    ".mp2",
    ".mp3",
    ".oga",
    ".ogg",
    ".opus",
    ".ra",
    ".rf64",
    ".snd",
    ".spx",
    ".thd",
    ".tta",
    ".voc",
    ".w64",
    ".wav",
    ".wave",
    ".weba",
    ".wma",
    ".wv",
)

# The import capability also accepts these legacy/proprietary containers. The
# portable FFmpeg build used for reproducible fixtures has no encoder for them,
# so they are recorded explicitly instead of being represented by renamed or
# otherwise invalid files.
UNAVAILABLE_AUDIO_EXTENSIONS = (
    ".ape",
    ".dff",
    ".dsf",
    ".mpc",
    ".oma",
    ".qcp",
    ".shn",
    ".tak",
    ".xma",
)

EXPLICIT_AUDIO_ARGUMENTS: dict[str, tuple[str, ...]] = {
    ".amr": (
        "-ar",
        "8000",
        "-ac",
        "1",
        "-c:a",
        "libopencore_amrnb",
        "-b:a",
        "12.2k",
        "-f",
        "amr",
    ),
    ".dts": ("-ar", "48000", "-ac", "2", "-c:a", "dca", "-strict", "-2", "-f", "dts"),
    ".g726": ("-ar", "8000", "-ac", "1", "-c:a", "g726", "-f", "g726"),
    ".gsm": ("-ar", "8000", "-ac", "1", "-c:a", "libgsm", "-f", "gsm"),
    ".lbc": ("-ar", "8000", "-ac", "1", "-c:a", "libilbc", "-f", "ilbc"),
    ".m4r": ("-c:a", "aac", "-f", "ipod"),
    ".mlp": ("-ar", "48000", "-ac", "2", "-c:a", "mlp", "-strict", "-2", "-f", "mlp"),
    ".rf64": ("-c:a", "pcm_s16le", "-f", "wav", "-rf64", "always"),
    ".snd": ("-c:a", "pcm_s16be", "-f", "au"),
    ".spx": ("-ar", "16000", "-ac", "1", "-c:a", "libspeex", "-f", "spx"),
    ".thd": (
        "-ar",
        "48000",
        "-ac",
        "2",
        "-c:a",
        "truehd",
        "-strict",
        "-2",
        "-f",
        "truehd",
    ),
    ".wave": ("-c:a", "pcm_s16le", "-f", "wav"),
    ".weba": ("-c:a", "libopus", "-f", "webm"),
    ".wv": (
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "wavpack",
        "-sample_fmt",
        "s32p",
        "-frame_size",
        "1024",
        "-f",
        "wv",
    ),
}


def download(url: str, destination: Path) -> None:
    if destination.is_file() and destination.stat().st_size > 0:
        header = destination.read_bytes()[:128]
        if destination.suffix.lower() != ".azw3" or b"BOOKMOBI" in header:
            return
    request = urllib.request.Request(
        url, headers={"User-Agent": "ErmaoBooksFormatFixture/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        temporary = destination.with_suffix(destination.suffix + ".part")
        with temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        temporary.replace(destination)


def run(command: list[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_fb2(source_text: Path, destination: Path) -> None:
    paragraphs = [
        line.strip()
        for line in source_text.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    body = "\n".join(
        f"      <p>{html.escape(paragraph)}</p>" for paragraph in paragraphs
    )
    document = f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
  <description><title-info><genre>children</genre><author><first-name>Lewis</first-name><last-name>Carroll</last-name></author><book-title>Alice's Adventures in Wonderland</book-title><lang>en</lang></title-info></description>
  <body><title><p>Alice's Adventures in Wonderland</p></title>
{body}
  </body>
</FictionBook>
"""
    destination.write_text(document, encoding="utf-8")


def extract_images(epub: Path, image_directory: Path) -> list[Path]:
    image_directory.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(epub) as archive:
        candidates = [
            name
            for name in archive.namelist()
            if Path(name).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            and archive.getinfo(name).file_size >= 10_000
        ]
        for index, name in enumerate(candidates[:6], start=1):
            target = image_directory / f"{index:03d}{Path(name).suffix.lower()}"
            target.write_bytes(archive.read(name))
            extracted.append(target)
    if len(extracted) < 2:
        raise RuntimeError(
            "The public-domain EPUB did not contain enough usable illustrations"
        )
    return extracted


def package_comics(images: list[Path], target_root: Path, rar: Path) -> list[Path]:
    created: list[Path] = []
    for extension in (".cbz", ".zip"):
        target = target_root / f"{TITLE_PREFIX} - {extension[1:].upper()}{extension}"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for image in images:
                archive.write(image, image.name)
        created.append(target)
    for extension in (".cbr", ".rar"):
        target = target_root / f"{TITLE_PREFIX} - {extension[1:].upper()}{extension}"
        target.unlink(missing_ok=True)
        run(
            [
                str(rar),
                "a",
                "-idq",
                "-ep1",
                str(target),
                *[image.name for image in images],
            ],
            cwd=images[0].parent,
        )
        created.append(target)
    return created


def probe_audio(ffprobe: Path, path: Path) -> dict[str, object]:
    raw_options = (
        ["-f", "g726", "-code_size", "4", "-ar", "8000"]
        if path.suffix.lower() == ".g726"
        else []
    )
    completed = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=format_name,duration",
            "-show_entries",
            "stream=codec_name,codec_type,sample_rate,channels",
            "-of",
            "json",
            *raw_options,
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip())
    payload = json.loads(completed.stdout)
    streams = payload.get("streams")
    duration = float(payload.get("format", {}).get("duration", 0))
    raw_without_container_duration = {".aptx", ".aptxhd", ".mlp", ".thd"}
    if (
        not isinstance(streams, list)
        or not any(stream.get("codec_type") == "audio" for stream in streams)
        or (duration <= 0 and path.suffix.lower() not in raw_without_container_duration)
    ):
        raise RuntimeError(f"No valid audio stream and duration in {path.name}")
    return payload


def write_sphere(ffmpeg: Path, source: Path, destination: Path) -> None:
    raw = destination.with_suffix(".pcm")
    run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-t",
            "30",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "s16le",
            str(raw),
        ]
    )
    payload = raw.read_bytes()
    sample_count = len(payload) // 2
    fields = [
        "NIST_1A",
        "   1024",
        "channel_count -i 1",
        f"sample_count -i {sample_count}",
        "sample_rate -i 16000",
        "sample_n_bytes -i 2",
        "sample_byte_format -s2 01",
        "sample_sig_bits -i 16",
        "end_head",
    ]
    header = ("\n".join(fields) + "\n").encode("ascii")
    destination.write_bytes(header.ljust(1024, b" ") + payload)
    raw.unlink(missing_ok=True)


def transcode_audio(
    ffmpeg: Path, ffprobe: Path, source: Path, target_root: Path
) -> tuple[list[Path], dict[str, dict[str, object]], dict[str, str]]:
    created: list[Path] = []
    probes: dict[str, dict[str, object]] = {}
    failures: dict[str, str] = {}
    for extension in AUDIO_EXTENSIONS:
        target = (
            target_root / f"{TITLE_PREFIX} - AUDIO - {extension[1:].upper()}{extension}"
        )
        arguments = [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-t",
            "30",
            "-i",
            str(source),
            "-vn",
        ]
        arguments.extend(EXPLICIT_AUDIO_ARGUMENTS.get(extension, ()))
        arguments.append(str(target))
        try:
            run(arguments)
            probes[extension] = probe_audio(ffprobe, target)
        except RuntimeError as exc:
            target.unlink(missing_ok=True)
            failures[extension] = str(exc)
            continue
        created.append(target)
    return created, probes, failures


def write_manifest(
    target_root: Path,
    created: list[Path],
    probes: dict[str, dict[str, object]],
    failures: dict[str, str],
) -> Path:
    lines = [
        "# 公开格式测试 / Public format fixtures",
        "",
        "原作 / Work: Alice's Adventures in Wonderland — Lewis Carroll (1865).",
        "文本与插图来源 / Text and illustration source: Project Gutenberg eBook #11 (public domain in the USA).",
        "AZW3/KF8 来源 / AZW3/KF8 source: Project Gutenberg eBook #11.",
        "有声书来源 / Audiobook source: LibriVox version 6, read by StudioMike (Public Domain Mark 1.0 in the USA).",
        "音频文件是同一 LibriVox 公版章节的 30 秒格式测试转码；服务器不会在正常导入或播放时转码。",
        "MOBI、AZW 与 PRC 使用同一合法 MOBI7/Palm Database 容器，因为这三个扩展名属于该兼容容器家族；AZW3 使用独立 KF8 文件。",
        "",
        "Sources:",
        *[f"- {name}: {url}" for name, url in SOURCES.items()],
        "",
        "Files:",
    ]
    for path in sorted(created, key=lambda item: item.name.casefold()):
        lines.append(
            f"- `{path.name}` — {path.stat().st_size} bytes — SHA-256 `{sha256(path)}`"
        )
    lines.extend(
        [
            "",
            "Audio probes:",
            "",
            "```json",
            json.dumps(probes, ensure_ascii=False, indent=2),
            "```",
            "",
        ]
    )
    if failures:
        lines.extend(
            [
                "Declared compatibility extensions not emitted by the available encoder:",
                "",
            ]
        )
        lines.extend(
            f"- `{extension}` — {reason}" for extension, reason in failures.items()
        )
        lines.append("")
    manifest = target_root / f"{TITLE_PREFIX} - 来源与校验.md"
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--rar", type=Path, required=True)
    args = parser.parse_args()
    args.target_root.mkdir(parents=True, exist_ok=True)
    args.source_root.mkdir(parents=True, exist_ok=True)

    source_paths = {name: args.source_root / f"alice.{name}" for name in SOURCES}
    for name, url in SOURCES.items():
        download(url, source_paths[name])

    created: list[Path] = []
    direct_formats = {
        "EPUB": source_paths["epub"],
        "TXT": source_paths["text"],
        "MOBI": source_paths["mobi"],
        "AZW": source_paths["mobi"],
        "PRC": source_paths["mobi"],
        "AZW3": source_paths["azw3"],
        "PDF": source_paths["pdf"],
    }
    for label, source in direct_formats.items():
        target = args.target_root / f"{TITLE_PREFIX} - {label}.{label.lower()}"
        shutil.copy2(source, target)
        created.append(target)
    fb2 = args.target_root / f"{TITLE_PREFIX} - FB2.fb2"
    write_fb2(source_paths["text"], fb2)
    created.append(fb2)

    image_directory = args.target_root / f"{TITLE_PREFIX} - IMAGE_DIR"
    images = extract_images(source_paths["illustrated_epub"], image_directory)
    created.extend(images)
    created.extend(package_comics(images, args.target_root, args.rar))

    audio_files, probes, failures = transcode_audio(
        args.ffmpeg, args.ffprobe, source_paths["audio"], args.target_root
    )
    sphere = args.target_root / f"{TITLE_PREFIX} - AUDIO - SPH.sph"
    write_sphere(args.ffmpeg, source_paths["audio"], sphere)
    probes[".sph"] = probe_audio(args.ffprobe, sphere)
    for extension in UNAVAILABLE_AUDIO_EXTENSIONS:
        failures.setdefault(
            extension,
            "No encoder is available in the pinned portable fixture toolchain.",
        )
    audio_files.append(sphere)
    created.extend(audio_files)
    audiobook_directory = args.target_root / f"{TITLE_PREFIX} - AUDIOBOOK_DIR"
    audiobook_directory.mkdir(exist_ok=True)
    for index, source in enumerate(audio_files[-2:], start=1):
        target = (
            audiobook_directory / f"{index:02d} - Alice chapter excerpt{source.suffix}"
        )
        shutil.copy2(source, target)
        created.append(target)

    manifest = write_manifest(args.target_root, created, probes, failures)
    print(
        json.dumps(
            {
                "created": len(created),
                "manifest": str(manifest),
                "audioExtensions": len(probes),
                "audioFailures": failures,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
