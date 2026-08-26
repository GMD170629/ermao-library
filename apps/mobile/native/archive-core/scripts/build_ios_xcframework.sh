#!/bin/sh
set -eu

script_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
archive_root=$(CDPATH= cd -- "$script_directory/.." && pwd)
output_directory="$archive_root/Frameworks/ErmaoArchiveCore.xcframework"
cmake_binary="${ERMAO_CMAKE_BINARY:-/Users/guyu/Library/Android/sdk/cmake/3.22.1/bin/cmake}"

if [ ! -x "$cmake_binary" ]; then
    echo "CMake is unavailable: $cmake_binary" >&2
    exit 1
fi
if [ -e "$output_directory" ]; then
    echo "Refusing to overwrite existing artifact: $output_directory" >&2
    exit 1
fi

work_directory=$(mktemp -d)
trap 'rm -rf "$work_directory"' EXIT HUP INT TERM
build_directory="$work_directory/iphoneos-arm64"
combined_library="$work_directory/libErmaoArchiveCore.a"
framework_directory="$work_directory/ErmaoArchiveCore.framework"

"$cmake_binary" -S "$archive_root" -B "$build_directory" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_SYSTEM_NAME=iOS \
    -DCMAKE_OSX_SYSROOT=iphoneos \
    -DCMAKE_OSX_ARCHITECTURES=arm64 \
    -DCMAKE_OSX_DEPLOYMENT_TARGET=16.0 \
    -DERMAO_ARCHIVE_BUILD_TESTS=OFF
"$cmake_binary" --build "$build_directory" --target ermao_archive_core -j 8

mkdir -p "$framework_directory/Headers" "$framework_directory/Modules" "$(dirname -- "$output_directory")"
libtool -static \
    "$build_directory/libermao_archive_core.a" \
    "$build_directory/libarchive/libarchive/libarchive.a" \
    -o "$combined_library"
cp "$combined_library" "$framework_directory/ErmaoArchiveCore"
cp "$archive_root/include/archive_core.h" "$framework_directory/Headers/ErmaoArchiveCore.h"
cp "$archive_root/include/framework.modulemap" "$framework_directory/Modules/module.modulemap"
cp "$archive_root/include/Info.plist" "$framework_directory/Info.plist"
xcodebuild -create-xcframework \
    -framework "$framework_directory" \
    -output "$output_directory"

echo "Created $output_directory (iphoneos arm64 only)"
