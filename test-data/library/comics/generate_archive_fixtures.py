"""Build deterministic, original RAR5/CBR fixtures from the existing PNG corpus.

The stored-file headers follow https://www.rarlab.com/technote.htm.
This is a test fixture builder, not a Reader conversion or download path.
"""

from pathlib import Path
from struct import pack
from zipfile import ZIP_STORED, ZipFile, ZipInfo
from zlib import crc32


def vint(value: int) -> bytes:
    encoded = bytearray()
    while value >= 128:
        encoded.append((value & 127) | 128)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def header(fields: bytes) -> bytes:
    content = vint(len(fields)) + fields
    return pack("<I", crc32(content)) + content


def main() -> None:
    root = Path(__file__).resolve().parent
    archive = bytearray(b"Rar!\x1a\x07\x01\x00")
    archive.extend(header(b"\x01\x00\x00"))
    for page in sorted((root / "starship-pages").glob("*.png")):
        content = page.read_bytes()
        name = page.name.encode("utf-8")
        fields = b"\x02\x02" + vint(len(content)) + b"\x04"
        fields += vint(len(content)) + vint(0o100644) + pack("<I", crc32(content))
        fields += b"\x00\x01" + vint(len(name)) + name
        archive.extend(header(fields))
        archive.extend(content)
    archive.extend(header(b"\x05\x00\x00"))
    for suffix in ("rar", "cbr"):
        (root / f"reader-pages.{suffix}").write_bytes(archive)
    for suffix in ("zip", "cbz"):
        with ZipFile(root / f"reader-pages.{suffix}", "w") as zipped:
            for page in sorted((root / "starship-pages").glob("*.png")):
                entry = ZipInfo(page.name, date_time=(2026, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_STORED
                zipped.writestr(entry, page.read_bytes())


if __name__ == "__main__":
    main()
