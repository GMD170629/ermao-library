#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
core_dir=$(CDPATH= cd -- "$script_dir/../../mobile/native/mobi-core" && pwd)
output_dir="$app_dir/build/server"
vendor_dir="$core_dir/Sources/CLibMobi"

mkdir -p "$output_dir/objects"

if command -v cmake >/dev/null 2>&1; then
  cmake -S "$script_dir" -B "$output_dir" -DERMAO_MOBI_BUILD_TESTS=OFF
  cmake --build "$output_dir" --config Release
  exit 0
fi

common_flags="-std=c99 -O2 -fvisibility=hidden -I$vendor_dir/public -I$vendor_dir/include -I$vendor_dir/src -DPACKAGE_VERSION=\"0.12\" -DUSE_XMLWRITER -DUSE_ZLIB -DHAVE_STRDUP -DHAVE_UNISTD_H -DMOBI_INLINE=inline"
sources="buffer compression debug index memory meta opf parse_rawml read structure util write xmlwriter ermao_mobi"
objects=""
for source in $sources; do
  object="$output_dir/objects/$source.o"
  cc $common_flags -c "$vendor_dir/src/$source.c" -o "$object"
  objects="$objects $object"
done

cc $common_flags -Wall -Wextra -Wpedantic -Werror -c "$script_dir/main.c" -o "$output_dir/objects/main.o"
cc "$output_dir/objects/main.o" $objects -lz -o "$output_dir/readium_web_poc_server"
