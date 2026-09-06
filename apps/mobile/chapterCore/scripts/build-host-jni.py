#!/usr/bin/env python3
"""Build the canonical chapter JNI bridge for JVM host tests.

The Android and host builds both compile chapter_jni.c and the policy-neutral
chapter core through the one CMake entry point. This script only supplies a
Zig compiler wrapper and the host JDK JNI headers; it does not provide a
second parser or copy an Android library.
"""

from __future__ import annotations

import argparse
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


def fail(message: str) -> NoReturn:
    raise SystemExit(f"host JNI build failed: {message}")


def existing_file(path: Path, label: str) -> Path:
    if not path.is_file():
        fail(f"{label} does not exist: {path}")
    return path.resolve()


def first_existing_file(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def discover_zig(repo_root: Path) -> Path:
    candidates: list[Path] = []
    configured = os.environ.get("ERMAO_ZIG")
    if configured:
        candidates.append(Path(configured))
    path_lookup = shutil.which("zig")
    if path_lookup:
        candidates.append(Path(path_lookup))
    for runtime_root in (repo_root / ".runtime-windows" / "zig",):
        if runtime_root.is_dir():
            candidates.extend(sorted(runtime_root.glob("*/zig.exe"), reverse=True))
            candidates.extend(sorted(runtime_root.glob("*/zig"), reverse=True))

    zig = first_existing_file(candidates)
    if zig is None:
        fail("Zig 0.14.1 was not found; set ERMAO_ZIG to the existing zig executable")
    return zig


def discover_cmake() -> Path:
    configured = os.environ.get("CMAKE")
    if configured:
        return existing_file(Path(configured), "CMAKE")

    path_lookup = shutil.which("cmake")
    if path_lookup:
        return Path(path_lookup).resolve()

    sdk_root = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if sdk_root:
        cmake_root = Path(sdk_root) / "cmake"
        candidates = sorted(cmake_root.glob("*/bin/cmake.exe"), reverse=True)
        candidates.extend(sorted(cmake_root.glob("*/bin/cmake"), reverse=True))
        cmake = first_existing_file(candidates)
        if cmake:
            return cmake
    fail("CMake was not found; set CMAKE to the existing CMake executable")


def discover_ninja(cmake: Path) -> Path:
    configured = os.environ.get("NINJA")
    if configured:
        return existing_file(Path(configured), "NINJA")

    path_lookup = shutil.which("ninja")
    if path_lookup:
        return Path(path_lookup).resolve()

    sibling_name = "ninja.exe" if platform.system().lower() == "windows" else "ninja"
    sibling = cmake.parent / sibling_name
    return existing_file(sibling, "Ninja")


def jdk_candidates(explicit: str | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    for variable in ("ERMAO_HOST_JNI_JDK", "JAVA_HOME"):
        value = os.environ.get(variable)
        if value:
            candidates.append(Path(value))

    if platform.system().lower() == "windows":
        candidates.extend(
            sorted(Path("C:/Program Files/JetBrains").glob("*/jbr"))
            if Path("C:/Program Files/JetBrains").is_dir()
            else []
        )
        candidates.extend(
            sorted(Path("C:/Program Files/Java").glob("*"))
            if Path("C:/Program Files/Java").is_dir()
            else []
        )
    else:
        candidates.extend(sorted(Path("/usr/lib/jvm").glob("*")))
        candidates.extend(sorted(Path("/usr/java").glob("*")))
    return candidates


def discover_jni_headers(explicit: str | None) -> tuple[Path, Path, str]:
    platform_name = platform.system().lower()
    if platform_name == "windows":
        platform_include_name = "win32"
    elif platform_name == "linux":
        platform_include_name = "linux"
    else:
        fail(f"unsupported host OS for JNI headers: {platform.system()}")

    candidates = jdk_candidates(explicit)
    for candidate in candidates:
        include_dir = candidate / "include"
        platform_include_dir = include_dir / platform_include_name
        if (include_dir / "jni.h").is_file() and (
            platform_include_dir / "jni_md.h"
        ).is_file():
            return (
                include_dir.resolve(),
                platform_include_dir.resolve(),
                platform_include_name,
            )

    searched = ", ".join(str(path) for path in candidates)
    fail(
        "a JDK with include/jni.h and include/"
        f"{platform_include_name}/jni_md.h was not found; searched: {searched}"
    )


def host_spec() -> tuple[str, str, str, str]:
    host_os = platform.system().lower()
    machine = platform.machine().lower()
    if machine not in {"amd64", "x86_64"}:
        fail(f"unsupported host architecture: {platform.machine()}; x86_64 is required")
    if host_os == "windows":
        return "windows-x86_64", "x86_64-windows-gnu", "ermao_chapter_jni.dll", "win32"
    if host_os == "linux":
        return "linux-x86_64", "x86_64-linux-gnu", "libermao_chapter_jni.so", "linux"
    fail(f"unsupported host OS: {platform.system()}; Windows and Linux are supported")


def write_zig_subcommand_wrapper(
    wrapper: Path, zig: Path, arguments: tuple[str, ...], is_windows: bool
) -> None:
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    if is_windows:
        zig_text = str(zig).replace('"', '""')
        wrapper.write_text(
            f'@echo off\r\n"{zig_text}" {" ".join(arguments)} %*\r\n',
            encoding="utf-8",
            newline="",
        )
    else:
        wrapper.write_text(
            f'#!/bin/sh\nexec {shlex.join((str(zig), *arguments))} "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(
            wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )


def run(command: list[str], cwd: Path) -> None:
    print("host JNI:", " ".join(command))
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode != 0:
        fail(f"command exited with {completed.returncode}")


def cmake_path(path: Path) -> str:
    """Use CMake's slash form so Windows paths are not parsed as escapes."""
    return path.as_posix() if platform.system().lower() == "windows" else str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--build-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--jdk-home", type=str)
    parser.add_argument("--zig", type=Path)
    parser.add_argument("--cmake", type=Path)
    parser.add_argument("--ninja", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    source_dir = args.source_dir.resolve()
    build_dir = args.build_dir.resolve()
    output_dir = args.output_dir.resolve()
    if not source_dir.is_dir():
        fail(f"JNI CMake source directory does not exist: {source_dir}")
    if (
        not (source_dir / "CMakeLists.txt").is_file()
        or not (source_dir / "chapter_jni.c").is_file()
    ):
        fail(f"canonical JNI CMake entry is incomplete: {source_dir}")

    platform_name, target, library_name, jni_platform_name = host_spec()
    zig = existing_file(args.zig, "Zig") if args.zig else discover_zig(repo_root)
    cmake = existing_file(args.cmake, "CMake") if args.cmake else discover_cmake()
    ninja = existing_file(args.ninja, "Ninja") if args.ninja else discover_ninja(cmake)
    jni_include, jni_platform_include, _ = discover_jni_headers(args.jdk_home)

    build_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    wrapper_name = "zig-cc.cmd" if platform_name.startswith("windows") else "zig-cc"
    wrapper = build_dir / "toolchain" / wrapper_name
    write_zig_subcommand_wrapper(
        wrapper, zig, ("cc", "-target", target), platform_name.startswith("windows")
    )
    ar_name = "zig-ar.cmd" if platform_name.startswith("windows") else "zig-ar"
    ranlib_name = (
        "zig-ranlib.cmd" if platform_name.startswith("windows") else "zig-ranlib"
    )
    ar_wrapper = build_dir / "toolchain" / ar_name
    ranlib_wrapper = build_dir / "toolchain" / ranlib_name
    write_zig_subcommand_wrapper(
        ar_wrapper, zig, ("ar",), platform_name.startswith("windows")
    )
    write_zig_subcommand_wrapper(
        ranlib_wrapper, zig, ("ranlib",), platform_name.startswith("windows")
    )

    configure = [
        str(cmake),
        "-S",
        cmake_path(source_dir),
        "-B",
        cmake_path(build_dir),
        "-G",
        "Ninja",
        f"-DCMAKE_MAKE_PROGRAM={cmake_path(ninja)}",
        f"-DCMAKE_C_COMPILER={cmake_path(wrapper)}",
        f"-DCMAKE_AR={cmake_path(ar_wrapper)}",
        f"-DCMAKE_RANLIB={cmake_path(ranlib_wrapper)}",
        "-DCMAKE_BUILD_TYPE=Debug",
        "-DERMAO_CHAPTER_BUILD_HOST=ON",
        f"-DERMAO_CHAPTER_HOST_OUTPUT_DIR={cmake_path(output_dir)}",
        f"-DERMAO_CHAPTER_JNI_INCLUDE_DIR={cmake_path(jni_include)}",
        f"-DERMAO_CHAPTER_JNI_PLATFORM_INCLUDE_DIR={cmake_path(jni_platform_include)}",
    ]
    run(configure, repo_root)
    run(
        [
            str(cmake),
            "--build",
            cmake_path(build_dir),
            "--target",
            "ermao_chapter_jni",
            "--config",
            "Debug",
        ],
        repo_root,
    )

    library = output_dir / library_name
    if not library.is_file() or library.stat().st_size == 0:
        fail(f"CMake completed but did not produce {library}")
    print(
        f"host JNI ready: {library} ({library.stat().st_size} bytes; target {target}; JNI {jni_platform_name})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
