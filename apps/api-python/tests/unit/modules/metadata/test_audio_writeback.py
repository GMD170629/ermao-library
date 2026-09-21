import json
import subprocess

import pytest

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.infrastructure.audio_writeback import write_audio_metadata


def probe(path):
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_packets",
            "-show_chapters",
            "-show_data_hash",
            "sha256",
            "-show_entries",
            "packet=pts,dts,duration,data_hash:chapter",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize("format", ["MP3", "M4A", "M4B", "FLAC"])
def test_audio_write_preserves_encoded_packets_and_chapters(tmp_path, format):
    source = tmp_path / ("original." + format.lower())
    output = tmp_path / ("written." + format.lower())
    chapters = tmp_path / "chapters.txt"
    chapters.write_text(
        ";FFMETADATA1\ntitle=Original\nartist=Author\ncomment=Unrelated comment\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=500\ntitle=Opening\n"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=22050",
            "-i",
            str(chapters),
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-t",
            "0.6",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    original = source.read_bytes()
    before = probe(source)
    with source.open("rb") as input_file, output.open("w+b") as output_file:
        write_audio_metadata(
            input_file,
            output_file,
            format=format,
            values=PublicationMetadata(title="新标题", authors=("新作者",)),
            fields=frozenset({"title", "authors"}),
        )
    assert source.read_bytes() == original
    assert probe(output) == before


@pytest.mark.parametrize("format", ["MP3", "M4A", "M4B", "FLAC"])
def test_audio_publication_reads_back_selected_fields_and_preserves_original(
    tmp_path, format
):
    from app.modules.library.infrastructure.source_file_access import (
        open_library_directory,
        open_library_file,
    )
    from app.modules.metadata.application.standard_writeback import StandardWriteFile
    from app.modules.metadata.infrastructure.standard_publication import (
        StandardMetadataPublication,
    )

    source = tmp_path / ("book." + format.lower())
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=22050",
            "-metadata",
            "title=Before",
            "-t",
            "0.1",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    original = source.read_bytes()
    publisher = StandardMetadataPublication(open_library_directory, open_library_file)
    values = PublicationMetadata(title="Published")
    fields = frozenset({"title"})
    inspected = publisher.inspect(tmp_path, source.name, format, values, fields)
    request = StandardWriteFile(
        "library",
        tmp_path,
        source.name,
        inspected.parent_device,
        inspected.parent_inode,
        format,
        inspected.original,
        values,
        fields,
        ".ermao-mcp-" + "a" * 32 + "-target",
        ".ermao-mcp-" + "a" * 32 + "-source",
    )
    prepared = publisher.prepare(request)
    assert source.read_bytes() == original
    publisher.publish(request, prepared)
    assert (
        publisher.inspect(tmp_path, source.name, format, values, fields).before.title
        == "Published"
    )
    assert (tmp_path / request.backup_name).read_bytes() == original


def test_id3_v23_preserves_unrelated_frames(tmp_path):
    from mutagen.id3 import APIC, ID3, TXXX

    path = tmp_path / "book.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=22050",
            "-metadata",
            "title=Before",
            "-id3v2_version",
            "3",
            "-t",
            "0.1",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=20,
    )
    tags = ID3(path, translate=False)
    tags.add(TXXX(encoding=1, desc="custom", text=["preserve 中文"]))
    tags.add(
        APIC(
            encoding=0,
            mime="image/jpeg",
            type=3,
            desc="",
            data=b"opaque existing cover",
        )
    )
    tags.save(path, v2_version=3)
    output = tmp_path / "output.mp3"
    before = probe(path)
    with path.open("rb") as source, output.open("w+b") as destination:
        write_audio_metadata(
            source,
            destination,
            format="MP3",
            values=PublicationMetadata(title="新标题"),
            fields=frozenset({"title"}),
        )
    assert probe(output) == before
    result = ID3(output, translate=False)
    assert result.version[1] == 3
    assert result["TXXX:custom"] == tags["TXXX:custom"]
    assert result["APIC:"].data == b"opaque existing cover"
