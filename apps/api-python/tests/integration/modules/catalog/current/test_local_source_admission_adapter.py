from __future__ import annotations

import io
import os
import struct
import unicodedata
import zipfile
from pathlib import Path

import pytest

from app.modules.catalog.application.source_admission_ports import (
    InvalidSourceRelativePath,
    SourceChangedDuringProbe,
    SourceProbeIoError,
    SourceProbePermissionDenied,
    SourceProbeUnavailable,
    SourceStatExpectation,
)
from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    ArchiveEvidence,
    AudioEvidence,
    DirectFileEvidence,
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    SidecarRole,
    SourceFormat,
)
from app.modules.catalog.infrastructure.admission import (
    LocalSourceAdmissionAdapter,
    RarMemberFact,
)
from app.modules.catalog.infrastructure.admission.bounded_reader import (
    BoundedRandomAccess,
    ProbeBudgetExceeded,
)


def _write(root: Path, relative_path: str, content: bytes) -> Path:
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def _probe(
    root: Path,
    relative_path: tuple[str, ...],
    *,
    adapter: LocalSourceAdmissionAdapter | None = None,
    expected_stat: SourceStatExpectation | None = None,
) -> SourceAdmissionEvidence | SourceAdmissionRejection:
    return (adapter or LocalSourceAdmissionAdapter()).probe(
        canonical_root=str(root.resolve()),
        relative_path=relative_path,
        expected_stat=expected_stat,
    )


def _expected(path: Path) -> SourceStatExpectation:
    observed = path.stat()
    return SourceStatExpectation(
        device_id=observed.st_dev,
        file_id=observed.st_ino,
        size_bytes=observed.st_size,
        modified_ns=observed.st_mtime_ns,
    )


def _mobi_bytes() -> bytes:
    content = bytearray(128)
    content[60:68] = b"BOOKMOBI"
    content[76:78] = (1).to_bytes(2, "big")
    content[78:82] = (86).to_bytes(4, "big")
    content[86:88] = (2).to_bytes(2, "big")
    content[102:106] = b"MOBI"
    return bytes(content)


def _palmdoc_prc_bytes() -> bytes:
    content = bytearray(128)
    content[60:68] = b"TEXtREAd"
    content[76:78] = (2).to_bytes(2, "big")
    content[78:82] = (96).to_bytes(4, "big")
    content[86:90] = (112).to_bytes(4, "big")
    content[96:98] = (2).to_bytes(2, "big")
    content[100:104] = (5).to_bytes(4, "big")
    content[104:106] = (1).to_bytes(2, "big")
    content[106:108] = (4096).to_bytes(2, "big")
    content[108:110] = (0).to_bytes(2, "big")
    content[112:117] = b"text\n"
    return bytes(content)


def _mp4_box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, box_type) + payload


def _m4_moov(metadata_bytes: int = 0) -> bytes:
    sample_entry = _mp4_box(b"mp4a", b"\x00" * 28)
    sample_description = _mp4_box(
        b"stsd",
        b"\x00" * 4 + (1).to_bytes(4, "big") + sample_entry,
    )
    sample_table = _mp4_box(b"stbl", sample_description)
    media_information = _mp4_box(b"minf", sample_table)
    media = _mp4_box(b"mdia", media_information)
    track = _mp4_box(b"trak", media)
    metadata = (
        _mp4_box(b"udta", b"metadata-marker" + b"\xc3" * (metadata_bytes - 15))
        if metadata_bytes
        else b""
    )
    return _mp4_box(b"moov", metadata + track)


def _m4_bytes(brand: bytes, compatible_brand: bytes = b"mp42") -> bytes:
    return _mp4_box(b"ftyp", brand + b"\x00" * 4 + compatible_brand) + _m4_moov()


def _m4_with_tail_moov(brand: bytes, mdat_bytes: int = 256 * 1024) -> bytes:
    return (
        _mp4_box(b"ftyp", brand + b"\x00" * 4 + b"mp42")
        + _mp4_box(b"mdat", b"payload-marker" + b"\xa5" * (mdat_bytes - 14))
        + _mp4_box(b"free", b"opaque padding")
        + _m4_moov(metadata_bytes=128 * 1024)
    )


def _deeply_nested_m4_bytes() -> bytes:
    content = _mp4_box(b"stsd", b"\x00" * 8)
    for _depth in range(20):
        content = _mp4_box(b"moov", content)
    return _mp4_box(b"ftyp", b"M4A " + b"\x00" * 4) + content


def _write_epub(path: Path, *, mimetype_compression: int = zipfile.ZIP_STORED) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = mimetype_compression
        archive.writestr(mimetype, b"application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            b"""<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles>
            </container>""",
        )
        # Admission only proves that the referenced package member exists. It
        # deliberately does not parse OPF metadata in this boundary.
        archive.writestr("OPS/book.opf", b"not parsed by source admission")


def _write_image_zip(path: Path, member_name: str = "pages/001.jpg") -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, b"bounded-image-member")


@pytest.mark.parametrize(
    "relative_path",
    [
        (),
        ("",),
        (".",),
        ("..",),
        ("/absolute",),
        ("nested/book.pdf",),
        ("nested\\book.pdf",),
        ("C:escape",),
        ("invalid-\udcff",),
    ],
)
def test_probe_rejects_injectable_relative_components(
    tmp_path: Path,
    relative_path: tuple[str, ...],
) -> None:
    with pytest.raises(InvalidSourceRelativePath) as caught:
        _probe(tmp_path, relative_path)

    assert str(caught.value) == "INVALID_SOURCE_RELATIVE_PATH"


def test_probe_preserves_nfd_host_name_and_opens_its_exact_spelling(
    tmp_path: Path,
) -> None:
    decomposed_name = unicodedata.normalize("NFD", "café.txt")
    _write(tmp_path, decomposed_name, b"plain text\n")

    result = _probe(tmp_path, (decomposed_name,))

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.relative_path == (decomposed_name,)
    assert result.source_format is SourceFormat.TXT


def test_invalid_canonical_root_is_a_path_free_operational_error() -> None:
    with pytest.raises(SourceProbeIoError) as caught:
        LocalSourceAdmissionAdapter().probe(
            canonical_root="/secret/root\x00suffix",
            relative_path=("book.pdf",),
        )

    assert str(caught.value) == "SOURCE_PROBE_IO_ERROR"
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("suffix", "role"),
    [
        (".opf", SidecarRole.OPF),
        (".LRC", SidecarRole.LYRICS),
        (".cue", SidecarRole.CUE),
        (".JpG", SidecarRole.ARTWORK),
        (".jpeg", SidecarRole.ARTWORK),
        (".png", SidecarRole.ARTWORK),
        (".webp", SidecarRole.ARTWORK),
    ],
)
def test_sidecar_roles_are_filename_candidates_and_do_not_parse_content(
    tmp_path: Path,
    suffix: str,
    role: SidecarRole,
) -> None:
    _write(tmp_path, f"candidate{suffix}", b"malformed content is not inspected")

    result = _probe(tmp_path, (f"candidate{suffix}",))

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.admission is AdmissionKind.SIDECAR
    assert result.sidecar_role is role
    assert result.evidence is None


def test_exact_system_noise_is_ignored_before_extension_classification(
    tmp_path: Path,
) -> None:
    _write(tmp_path, ".DS_Store", b"%PDF-1.7\nstartxref\n0\n%%EOF")
    _write(tmp_path, "thumbs.db", b"unknown")

    ignored = _probe(tmp_path, (".DS_Store",))
    visible = _probe(tmp_path, ("thumbs.db",))

    assert isinstance(ignored, SourceAdmissionEvidence)
    assert ignored.admission is AdmissionKind.IGNORED
    assert isinstance(visible, SourceAdmissionRejection)
    assert visible.reason is AdmissionRejectionReason.UNSUPPORTED_EXTENSION


def test_child_symlinks_are_diagnostics_and_are_never_followed(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.pdf"
    outside.write_bytes(b"outside secret")
    (tmp_path / "linked.pdf").symlink_to(outside)

    result = _probe(tmp_path, ("linked.pdf",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.entry_type is EntryType.SYMLINK
    assert result.reason is AdmissionRejectionReason.SYMLINK_NOT_ALLOWED
    assert outside.read_bytes() == b"outside secret"


def test_intermediate_symlink_is_rejected_without_walking_outside_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-directory"
    outside.mkdir()
    (outside / "book.pdf").write_bytes(b"outside secret")
    (tmp_path / "linked").symlink_to(outside, target_is_directory=True)

    result = _probe(tmp_path, ("linked", "book.pdf"))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.entry_type is EntryType.SYMLINK
    assert result.reason is AdmissionRejectionReason.SYMLINK_NOT_ALLOWED


def test_expected_stat_and_post_probe_stat_are_identity_fences(tmp_path: Path) -> None:
    target = _write(tmp_path, "book.txt", b"initial text")
    stale = _expected(target)
    stale = SourceStatExpectation(
        device_id=stale.device_id,
        file_id=stale.file_id,
        size_bytes=stale.size_bytes + 1,
        modified_ns=stale.modified_ns,
    )

    with pytest.raises(SourceChangedDuringProbe):
        _probe(tmp_path, ("book.txt",), expected_stat=stale)

    def mutate_after_probe() -> None:
        target.write_bytes(b"changed after parser completed")

    adapter = LocalSourceAdmissionAdapter(
        probe_completion_hook=mutate_after_probe,
    )
    with pytest.raises(SourceChangedDuringProbe) as caught:
        _probe(tmp_path, ("book.txt",), adapter=adapter)
    assert str(caught.value) == "SOURCE_CHANGED_DURING_PROBE"


def test_post_probe_fence_detects_ancestor_rename_and_rebind(tmp_path: Path) -> None:
    target = _write(tmp_path, "shelf/book.txt", b"same-sized text")
    displaced = tmp_path / "displaced-shelf"

    def rebind_ancestor_after_probe() -> None:
        target.parent.rename(displaced)
        target.parent.mkdir()
        (target.parent / target.name).write_bytes(b"same-sized text")

    adapter = LocalSourceAdmissionAdapter(
        probe_completion_hook=rebind_ancestor_after_probe,
    )

    with pytest.raises(SourceChangedDuringProbe):
        _probe(tmp_path, ("shelf", "book.txt"), adapter=adapter)


@pytest.mark.parametrize(
    ("filename", "content", "source_format", "evidence_type", "admission"),
    [
        (
            "book.pdf",
            b"%PDF-1.7\n1 0 obj\nendobj\nstartxref\n9\n%%EOF\n",
            SourceFormat.PDF,
            DirectFileEvidence,
            AdmissionKind.PRIMARY,
        ),
        (
            "book.txt",
            "UTF-8 text \u4e66\u7c4d\n".encode(),
            SourceFormat.TXT,
            DirectFileEvidence,
            AdmissionKind.PRIMARY,
        ),
        (
            "book.azw3",
            _mobi_bytes(),
            SourceFormat.AZW3,
            DirectFileEvidence,
            AdmissionKind.PRIMARY,
        ),
        (
            "legacy.prc",
            _palmdoc_prc_bytes(),
            SourceFormat.PRC,
            DirectFileEvidence,
            AdmissionKind.PRIMARY,
        ),
        (
            "track.mp3",
            b"\xff\xfb\x90\x64",
            SourceFormat.MP3,
            AudioEvidence,
            AdmissionKind.AUDIO_TRACK,
        ),
        (
            "track.m4a",
            _m4_bytes(b"isom"),
            SourceFormat.M4A,
            AudioEvidence,
            AdmissionKind.AUDIO_TRACK,
        ),
        (
            "track.m4b",
            _m4_bytes(b"M4A "),
            SourceFormat.M4B,
            AudioEvidence,
            AdmissionKind.AUDIO_TRACK,
        ),
    ],
)
def test_direct_formats_require_bounded_structural_evidence(
    tmp_path: Path,
    filename: str,
    content: bytes,
    source_format: SourceFormat,
    evidence_type: type[DirectFileEvidence | AudioEvidence],
    admission: AdmissionKind,
) -> None:
    _write(tmp_path, filename, content)

    result = _probe(tmp_path, (filename,))

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.admission is admission
    assert result.source_format is source_format
    assert isinstance(result.evidence, evidence_type)
    assert result.evidence.probe_bytes_examined <= result.evidence.probe_byte_budget


@pytest.mark.parametrize("filename", ["tail-moov.m4a", "tail-moov.m4b"])
def test_iso_bmff_probe_skips_large_mdat_and_finds_tail_moov(
    tmp_path: Path,
    filename: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.catalog.infrastructure.admission import source_file

    content = _m4_with_tail_moov(b"isom")
    _write(tmp_path, filename, content)
    mdat_header = content.index(b"mdat") - 4
    mdat_end = mdat_header + int.from_bytes(
        content[mdat_header : mdat_header + 4],
        "big",
    )
    mdat_payload_start = mdat_header + 8
    metadata_header = content.index(b"udta") - 4
    metadata_end = metadata_header + int.from_bytes(
        content[metadata_header : metadata_header + 4],
        "big",
    )
    metadata_payload_start = metadata_header + 8
    observed_reads: list[tuple[int, int]] = []
    real_pread = source_file.os.pread

    def recording_pread(file_descriptor: int, size: int, offset: int) -> bytes:
        observed_reads.append((offset, size))
        return real_pread(file_descriptor, size, offset)

    monkeypatch.setattr(source_file.os, "pread", recording_pread)

    result = _probe(tmp_path, (filename,))

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.source_format is (
        SourceFormat.M4A if filename.endswith(".m4a") else SourceFormat.M4B
    )
    assert isinstance(result.evidence, AudioEvidence)
    assert result.evidence.probe_bytes_examined < 1024
    assert result.evidence.probe_bytes_examined < len(content) // 100
    assert (
        sum(size for _, size in observed_reads) == result.evidence.probe_bytes_examined
    )
    assert all(
        (offset + size <= mdat_payload_start or offset >= mdat_end)
        and (offset + size <= metadata_payload_start or offset >= metadata_end)
        for offset, size in observed_reads
    )


@pytest.mark.parametrize(
    "invalid_box",
    [
        (64).to_bytes(4, "big") + b"moov" + b"truncated",
        b"\x00\x00\x00\x00mdatpayload",
        b"\x00\x00\x00\x01mdat" + (2**63).to_bytes(8, "big"),
    ],
    ids=("truncated", "zero-sized", "out-of-bounds-extended"),
)
def test_iso_bmff_invalid_declared_box_bounds_are_typed_rejections(
    tmp_path: Path,
    invalid_box: bytes,
) -> None:
    content = _mp4_box(b"ftyp", b"M4A " + b"\x00" * 4) + invalid_box
    _write(tmp_path, "invalid.m4a", content)

    result = _probe(tmp_path, ("invalid.m4a",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.CORRUPT_SOURCE


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("fake.pdf", b"not a pdf"),
        ("binary.txt", b"\x00\x01\xff"),
        ("fake.mobi", b"BOOKMOBI in the wrong location"),
        ("fake.mp3", b"ID3\x04\x00\x00\x00\x00\x00\x00"),
        ("wrong-brand.m4a", _m4_bytes(b"zzzz", b"xxxx")),
        (
            "fake-container.m4b",
            _mp4_box(b"ftyp", b"M4B " + b"\x00" * 4) + _mp4_box(b"mp4a", b"\x00" * 28),
        ),
        ("deeply-nested.m4a", _deeply_nested_m4_bytes()),
    ],
)
def test_suffix_only_direct_candidates_are_rejected_not_raised(
    tmp_path: Path,
    filename: str,
    content: bytes,
) -> None:
    _write(tmp_path, filename, content)

    result = _probe(tmp_path, (filename,))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason in {
        AdmissionRejectionReason.SIGNATURE_MISMATCH,
        AdmissionRejectionReason.CORRUPT_SOURCE,
        AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
    }


@pytest.mark.parametrize("filename", ["book.epub", "book.zip", "book.cbz"])
def test_valid_epub_container_has_priority_for_every_zip_family_suffix(
    tmp_path: Path,
    filename: str,
) -> None:
    target = tmp_path / filename
    _write_epub(target)

    result = _probe(tmp_path, (filename,))

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.source_format is SourceFormat.EPUB
    assert isinstance(result.evidence, ArchiveEvidence)
    assert result.evidence.epub_mimetype_verified
    assert result.evidence.epub_container_verified
    assert not result.evidence.comic_archive_verified


@pytest.mark.parametrize(
    ("filename", "source_format"),
    [("comic.cbz", SourceFormat.CBZ), ("comic.zip", SourceFormat.ZIP)],
)
def test_non_epub_zip_requires_safe_image_member_evidence(
    tmp_path: Path,
    filename: str,
    source_format: SourceFormat,
) -> None:
    _write_image_zip(tmp_path / filename)

    result = _probe(tmp_path, (filename,))

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.source_format is source_format
    assert isinstance(result.evidence, ArchiveEvidence)
    assert result.evidence.image_entry_count == 1
    assert result.evidence.comic_archive_verified


def test_plain_zip_is_not_admitted_by_extension(tmp_path: Path) -> None:
    target = tmp_path / "documents.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("notes.txt", b"not a comic")

    result = _probe(tmp_path, (target.name,))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.SIGNATURE_MISMATCH


@pytest.mark.parametrize(
    "member_names",
    [
        ("../outside.jpg",),
        ("/absolute.jpg",),
        ("C:/drive.jpg",),
        ("nested\\escape.jpg",),
        ("café.jpg", "cafe\u0301.jpg"),
    ],
)
def test_zip_rejects_unsafe_and_normalized_duplicate_member_paths(
    tmp_path: Path,
    member_names: tuple[str, ...],
) -> None:
    target = tmp_path / "unsafe.cbz"
    with zipfile.ZipFile(target, "w") as archive:
        for member_name in member_names:
            archive.writestr(member_name, b"image")

    result = _probe(tmp_path, (target.name,))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH


def test_zip_rejects_encryption_and_entry_budget_before_acceptance(
    tmp_path: Path,
) -> None:
    encrypted = tmp_path / "encrypted.cbz"
    _write_image_zip(encrypted)
    encrypted_bytes = bytearray(encrypted.read_bytes())
    central = encrypted_bytes.find(b"PK\x01\x02")
    assert central >= 0
    flags = int.from_bytes(encrypted_bytes[central + 8 : central + 10], "little")
    encrypted_bytes[central + 8 : central + 10] = (flags | 1).to_bytes(2, "little")
    encrypted.write_bytes(encrypted_bytes)

    encrypted_result = _probe(tmp_path, (encrypted.name,))

    assert isinstance(encrypted_result, SourceAdmissionRejection)
    assert encrypted_result.reason is AdmissionRejectionReason.ENCRYPTED_ARCHIVE

    oversized = tmp_path / "oversized.cbz"
    _write_image_zip(oversized)
    oversized_bytes = bytearray(oversized.read_bytes())
    eocd = oversized_bytes.rfind(b"PK\x05\x06")
    assert eocd >= 0
    oversized_bytes[eocd + 8 : eocd + 10] = (10_001).to_bytes(2, "little")
    oversized_bytes[eocd + 10 : eocd + 12] = (10_001).to_bytes(2, "little")
    oversized.write_bytes(oversized_bytes)

    oversized_result = _probe(tmp_path, (oversized.name,))

    assert isinstance(oversized_result, SourceAdmissionRejection)
    assert oversized_result.reason is AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED


def test_zip_rejects_excessive_compression_ratio(tmp_path: Path) -> None:
    target = tmp_path / "ratio.cbz"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("page.jpg", b"0" * 100_000)

    result = _probe(tmp_path, (target.name,))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED


class _StaticRarBackend:
    def __init__(self, members: tuple[RarMemberFact, ...]) -> None:
        self._members = members

    def inspect(self, source: io.BufferedIOBase) -> tuple[RarMemberFact, ...]:
        assert source.readable()
        return self._members


class _UnavailableRarBackend:
    def inspect(self, source: io.BufferedIOBase) -> tuple[RarMemberFact, ...]:
        del source
        try:
            raise OSError("backend unavailable at /secret/tool")
        except OSError as error:
            raise SourceProbeUnavailable() from error


class _ReadSpy(io.BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.requested_sizes: list[int | None] = []

    def read(self, size: int | None = -1) -> bytes:
        self.requested_sizes.append(size)
        return super().read(size)


@pytest.mark.parametrize("method_name", ["read", "read1", "readinto", "readinto1"])
def test_parser_reader_caps_each_underlying_read_before_allocation(
    method_name: str,
) -> None:
    source = _ReadSpy(b"0123456789")
    reader = BoundedRandomAccess(source, maximum_read_bytes=4)

    with pytest.raises(ProbeBudgetExceeded):
        if method_name in {"read", "read1"}:
            getattr(reader, method_name)()
        else:
            getattr(reader, method_name)(bytearray(100))

    assert source.requested_sizes == [5]
    reader.close()


def test_rar_requires_available_backend_and_preserves_operational_cause(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "comic.cbr", b"Rar!\x1a\x07\x01\x00")

    with pytest.raises(SourceProbeUnavailable) as caught:
        _probe(
            tmp_path,
            ("comic.cbr",),
            adapter=LocalSourceAdmissionAdapter(rar_backend=_UnavailableRarBackend()),
        )

    assert str(caught.value) == "SOURCE_PROBE_UNAVAILABLE"
    assert isinstance(caught.value.__cause__, OSError)
    assert "/secret" not in str(caught.value)


def test_rar_backend_facts_are_bounded_and_require_safe_image_members(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "comic.rar", b"Rar!\x1a\x07\x01\x00")
    adapter = LocalSourceAdmissionAdapter(
        rar_backend=_StaticRarBackend(
            (
                RarMemberFact(
                    name="pages/001.jpg",
                    compressed_bytes=50,
                    uncompressed_bytes=100,
                ),
            )
        )
    )

    result = _probe(tmp_path, ("comic.rar",), adapter=adapter)

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.source_format is SourceFormat.RAR
    assert isinstance(result.evidence, ArchiveEvidence)
    assert result.evidence.image_entry_count == 1


def test_probe_is_read_only_for_source_and_directory_state(tmp_path: Path) -> None:
    target = _write(
        tmp_path,
        "book.pdf",
        b"%PDF-1.7\n1 0 obj\nendobj\nstartxref\n9\n%%EOF\n",
    )
    before_stat = target.stat()
    before_names = tuple(sorted(path.name for path in tmp_path.iterdir()))
    before_content = target.read_bytes()

    result = _probe(tmp_path, (target.name,))

    after_stat = target.stat()
    assert isinstance(result, SourceAdmissionEvidence)
    assert tuple(sorted(path.name for path in tmp_path.iterdir())) == before_names
    assert target.read_bytes() == before_content
    assert (
        after_stat.st_dev,
        after_stat.st_ino,
        after_stat.st_mode,
        after_stat.st_size,
        after_stat.st_mtime_ns,
        after_stat.st_ctime_ns,
    ) == (
        before_stat.st_dev,
        before_stat.st_ino,
        before_stat.st_mode,
        before_stat.st_size,
        before_stat.st_mtime_ns,
        before_stat.st_ctime_ns,
    )


def test_permission_failure_has_stable_code_cause_and_no_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.catalog.infrastructure.admission import source_file

    def denied_open(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("denied /secret/library")

    monkeypatch.setattr(source_file.os, "open", denied_open)

    with pytest.raises(SourceProbePermissionDenied) as caught:
        _probe(tmp_path, ("book.pdf",))

    assert str(caught.value) == "SOURCE_PROBE_PERMISSION_DENIED"
    assert isinstance(caught.value.__cause__, PermissionError)
    assert "/secret" not in str(caught.value)


def test_adapter_does_not_open_source_with_write_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "book.txt", b"bounded text")
    from app.modules.catalog.infrastructure.admission import source_file

    real_open = source_file.os.open
    observed_flags: list[int] = []

    def recording_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        observed_flags.append(flags)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(source_file.os, "open", recording_open)

    result = _probe(tmp_path, ("book.txt",))

    assert isinstance(result, SourceAdmissionEvidence)
    forbidden_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    assert observed_flags
    assert all(flags & forbidden_flags == 0 for flags in observed_flags)


def test_unsupported_host_primitives_fail_closed_with_stable_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.catalog.infrastructure.admission import source_file

    monkeypatch.setattr(source_file, "_PLATFORM_SUPPORTED", False)

    with pytest.raises(SourceProbeUnavailable) as caught:
        _probe(tmp_path, ("book.txt",))

    assert str(caught.value) == "SOURCE_PROBE_UNAVAILABLE"
