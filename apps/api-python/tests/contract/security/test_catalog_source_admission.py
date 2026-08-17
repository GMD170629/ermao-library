from __future__ import annotations

import hashlib
import os
import stat
import unicodedata
import warnings
import zipfile
from dataclasses import fields
from pathlib import Path

import pytest

from app.modules.catalog.application.source_admission_ports import (
    InvalidSourceRelativePath,
    SourceAdmissionOperationalError,
    SourceChangedDuringProbe,
    SourceProbeIoError,
    SourceStatExpectation,
)
from app.modules.catalog.domain.admission import (
    AdmissionRejectionReason,
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
)
from app.modules.catalog.domain.model import (
    AdmissionKind,
    EntryType,
    SidecarRole,
    SourceFormat,
)
from app.modules.catalog.infrastructure.admission import LocalSourceAdmissionAdapter

_VALID_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\nstartxref\n9\n%%EOF\n"
_VALID_MP3_PREFIX = b"\xff\xfb\x90\x64"
_TOPOLOGY_V1_MAX_ARCHIVE_ENTRIES = 10_000


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


def _write_zip(
    path: Path,
    members: tuple[tuple[str, bytes], ...],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> None:
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for name, content in members:
            archive.writestr(name, content)


def _write_epub(path: Path) -> None:
    container = (
        b'<?xml version="1.0"?>'
        b'<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        b'<rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles>'
        b"</container>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype, b"application/epub+zip")
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OPS/content.opf", b"<package/>")


def _mark_zip_encrypted(path: Path) -> None:
    content = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        offset = 0
        while True:
            header = content.find(signature, offset)
            if header < 0:
                break
            flags_at = header + flag_offset
            flags = int.from_bytes(content[flags_at : flags_at + 2], "little") | 1
            content[flags_at : flags_at + 2] = flags.to_bytes(2, "little")
            offset = header + len(signature)
    path.write_bytes(content)


def _tree_snapshot(root: Path) -> dict[str, tuple[int, int, int, int, str | None]]:
    snapshot: dict[str, tuple[int, int, int, int, str | None]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        source_stat = path.lstat()
        digest = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if stat.S_ISREG(source_stat.st_mode)
            else None
        )
        relative = "." if path == root else path.relative_to(root).as_posix()
        snapshot[relative] = (
            source_stat.st_mode,
            source_stat.st_size,
            source_stat.st_mtime_ns,
            source_stat.st_ctime_ns,
            digest,
        )
    return snapshot


@pytest.mark.parametrize(
    "relative_path",
    [
        (),
        (".",),
        ("..",),
        ("/etc/passwd",),
        (r"\\server\share",),
        ("C:",),
        ("nested/book.pdf",),
        (r"nested\book.pdf",),
        ("book\x00.pdf",),
    ],
    ids=(
        "empty",
        "dot",
        "dot-dot",
        "absolute",
        "unc",
        "drive",
        "forward-separator",
        "back-separator",
        "nul",
    ),
)
def test_external_relative_paths_cannot_escape_or_change_interpretation(
    tmp_path: Path,
    relative_path: tuple[str, ...],
) -> None:
    with pytest.raises(InvalidSourceRelativePath) as caught:
        _probe(tmp_path, relative_path)

    assert caught.value.code == "INVALID_SOURCE_RELATIVE_PATH"
    assert str(tmp_path) not in str(caught.value)


def test_nfd_name_is_probed_by_raw_spelling_without_selecting_nfc_sibling(
    tmp_path: Path,
) -> None:
    nfc_name = unicodedata.normalize("NFC", "café.txt")
    nfd_name = unicodedata.normalize("NFD", "café.txt")
    assert nfd_name != nfc_name
    (tmp_path / nfd_name).write_bytes(b"NFD text\n")
    (tmp_path / nfc_name).write_bytes(b"\x00\x01\xff")

    nfd_result = _probe(tmp_path, (nfd_name,))
    nfc_result = _probe(tmp_path, (nfc_name,))

    assert isinstance(nfd_result, SourceAdmissionEvidence)
    assert nfd_result.relative_path == (nfd_name,)
    assert nfd_result.source_format is SourceFormat.TXT
    assert isinstance(nfc_result, SourceAdmissionRejection)
    assert nfc_result.relative_path == (nfc_name,)


def test_child_symlink_is_reported_without_following_its_target(tmp_path: Path) -> None:
    root = tmp_path / "library"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(_VALID_PDF)
    (root / "linked").symlink_to(outside, target_is_directory=True)

    result = _probe(root, ("linked", "secret.pdf"))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.entry_type is EntryType.SYMLINK
    assert result.reason is AdmissionRejectionReason.SYMLINK_NOT_ALLOWED
    assert result.to_probed_entry().admission is AdmissionKind.IGNORED


def test_system_noise_and_sidecars_are_classified_without_reading_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "book.opf": (AdmissionKind.SIDECAR, SidecarRole.OPF),
        "book.jpg": (AdmissionKind.SIDECAR, SidecarRole.ARTWORK),
        "track.lrc": (AdmissionKind.SIDECAR, SidecarRole.LYRICS),
        "album.cue": (AdmissionKind.SIDECAR, SidecarRole.CUE),
        "Thumbs.db": (AdmissionKind.IGNORED, None),
    }
    for name in expected:
        (tmp_path / name).write_bytes(_VALID_PDF)

    def reject_content_read(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("sidecar and system-noise classification read content")

    monkeypatch.setattr(os, "pread", reject_content_read)
    for name, (admission, role) in expected.items():
        result = _probe(tmp_path, (name,))
        assert isinstance(result, SourceAdmissionEvidence)
        assert result.admission is admission
        assert result.sidecar_role is role
        assert result.source_format is None
        assert result.evidence is None


def test_unsupported_filename_and_metadata_text_cannot_create_a_primary(
    tmp_path: Path,
) -> None:
    (tmp_path / "Famous Title by Author.bin").write_bytes(
        _VALID_PDF + b"\ntitle=Famous Title\nauthor=Author"
    )

    result = _probe(tmp_path, ("Famous Title by Author.bin",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.UNSUPPORTED_EXTENSION
    assert result.to_probed_entry().admission is AdmissionKind.UNSUPPORTED


def test_zip_suffix_alone_does_not_admit_a_comic(tmp_path: Path) -> None:
    _write_zip(tmp_path / "notes.zip", (("notes.txt", b"not a comic"),))

    result = _probe(tmp_path, ("notes.zip",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.SIGNATURE_MISMATCH


def test_epub_container_has_priority_even_when_the_filename_ends_in_zip(
    tmp_path: Path,
) -> None:
    _write_epub(tmp_path / "publication.zip")

    result = _probe(tmp_path, ("publication.zip",))

    assert isinstance(result, SourceAdmissionEvidence)
    assert result.admission is AdmissionKind.PRIMARY
    assert result.source_format is SourceFormat.EPUB
    assert result.evidence is not None


def test_epub_suffix_cannot_downgrade_an_image_archive_to_comic(tmp_path: Path) -> None:
    _write_zip(tmp_path / "mislabelled.epub", (("page.jpg", b"image"),))

    result = _probe(tmp_path, ("mislabelled.epub",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.CORRUPT_SOURCE


def test_audio_suffix_requires_codec_evidence(tmp_path: Path) -> None:
    (tmp_path / "fake.mp3").write_bytes(b"not audio")
    (tmp_path / "track.mp3").write_bytes(_VALID_MP3_PREFIX)

    rejected = _probe(tmp_path, ("fake.mp3",))
    admitted = _probe(tmp_path, ("track.mp3",))

    assert isinstance(rejected, SourceAdmissionRejection)
    assert rejected.reason is AdmissionRejectionReason.SIGNATURE_MISMATCH
    assert isinstance(admitted, SourceAdmissionEvidence)
    assert admitted.admission is AdmissionKind.AUDIO_TRACK
    assert admitted.source_format is SourceFormat.MP3


@pytest.mark.parametrize(
    "member_name",
    ("../page.jpg", "/page.jpg", r"folder\page.jpg", "C:/page.jpg"),
    ids=("parent", "absolute", "backslash", "drive"),
)
def test_archive_member_path_injection_is_rejected(
    tmp_path: Path,
    member_name: str,
) -> None:
    _write_zip(tmp_path / "unsafe.cbz", ((member_name, b"image"),))

    result = _probe(tmp_path, ("unsafe.cbz",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH


def test_duplicate_archive_member_is_rejected(tmp_path: Path) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        _write_zip(
            tmp_path / "duplicate.cbz",
            (("page.jpg", b"one"), ("page.jpg", b"two")),
        )

    result = _probe(tmp_path, ("duplicate.cbz",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH


def test_encrypted_archive_is_rejected_before_member_content_access(
    tmp_path: Path,
) -> None:
    path = tmp_path / "encrypted.cbz"
    _write_zip(path, (("page.jpg", b"image"),))
    _mark_zip_encrypted(path)

    result = _probe(tmp_path, ("encrypted.cbz",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.ENCRYPTED_ARCHIVE


def test_archive_compression_ratio_budget_rejects_zip_bomb_shape(
    tmp_path: Path,
) -> None:
    _write_zip(
        tmp_path / "bomb.cbz",
        (("page.jpg", b"A" * 1_000_000),),
        compression=zipfile.ZIP_DEFLATED,
    )

    result = _probe(tmp_path, ("bomb.cbz",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED


def test_archive_entry_budget_is_enforced_before_admission(tmp_path: Path) -> None:
    path = tmp_path / "too-many.cbz"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(_TOPOLOGY_V1_MAX_ARCHIVE_ENTRIES + 1):
            archive.writestr(f"{index:05d}.jpg", b"")

    result = _probe(tmp_path, ("too-many.cbz",))

    assert isinstance(result, SourceAdmissionRejection)
    assert result.reason is AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED


def test_expected_stat_drift_before_probe_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(_VALID_PDF)
    source_stat = source.stat()
    stale = SourceStatExpectation(
        device_id=source_stat.st_dev,
        file_id=source_stat.st_ino,
        size_bytes=source_stat.st_size + 1,
        modified_ns=source_stat.st_mtime_ns,
    )

    with pytest.raises(SourceChangedDuringProbe) as caught:
        _probe(tmp_path, ("book.pdf",), expected_stat=stale)

    assert caught.value.code == "SOURCE_CHANGED_DURING_PROBE"


def test_stat_drift_after_probe_is_rejected_before_result_publication(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(_VALID_PDF)

    def mutate_after_inspection() -> None:
        source.write_bytes(_VALID_PDF + b"changed")

    adapter = LocalSourceAdmissionAdapter(probe_completion_hook=mutate_after_inspection)

    with pytest.raises(SourceChangedDuringProbe) as caught:
        _probe(tmp_path, ("book.pdf",), adapter=adapter)

    assert caught.value.code == "SOURCE_CHANGED_DURING_PROBE"


def test_probe_never_writes_to_the_user_directory(tmp_path: Path) -> None:
    (tmp_path / "book.pdf").write_bytes(_VALID_PDF)
    (tmp_path / "book.opf").write_bytes(b"metadata that admission must not read")
    _write_zip(tmp_path / "comic.cbz", (("page.jpg", b"image"),))
    before = _tree_snapshot(tmp_path)

    for relative_path in (("book.pdf",), ("book.opf",), ("comic.cbz",)):
        _probe(tmp_path, relative_path)

    assert _tree_snapshot(tmp_path) == before


def test_results_and_operational_errors_never_expose_the_canonical_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-library-root"
    root.mkdir()
    (root / "book.pdf").write_bytes(_VALID_PDF)

    result = _probe(root, ("book.pdf",))
    rendered_result = repr(result)
    assert str(root.resolve()) not in rendered_result
    assert not any(
        "root" in field.name.casefold() or "canonical" in field.name.casefold()
        for result_type in (SourceAdmissionEvidence, SourceAdmissionRejection)
        for field in fields(result_type)
    )

    missing_root = tmp_path / "secret-missing-root"
    with pytest.raises(SourceProbeIoError) as caught:
        LocalSourceAdmissionAdapter().probe(
            canonical_root=str(missing_root),
            relative_path=("book.pdf",),
        )
    assert caught.value.code == "SOURCE_PROBE_IO_ERROR"
    assert str(missing_root) not in str(caught.value)
    assert str(missing_root) not in repr(caught.value)


def test_operational_error_contracts_are_path_free_stable_codes() -> None:
    error_types = SourceAdmissionOperationalError.__subclasses__()

    assert error_types
    for error_type in error_types:
        error = error_type()
        assert str(error) == error.code
        assert "/" not in str(error)
        assert "\\" not in str(error)
