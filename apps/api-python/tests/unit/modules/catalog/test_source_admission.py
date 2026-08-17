from __future__ import annotations

from dataclasses import replace

import pytest

from app.modules.catalog.public import (
    SYSTEM_NOISE_NAMES,
    AdmissionKind,
    AdmissionRejectionReason,
    ArchiveEvidence,
    AudioCodec,
    AudioEvidence,
    BundleEvidence,
    DirectFileEvidence,
    EntryType,
    SidecarRole,
    SourceAdmissionEvidence,
    SourceAdmissionRejection,
    SourceFormat,
    is_system_noise_name,
    parse_disc_component,
)


def _direct(source_format: SourceFormat = SourceFormat.PDF) -> DirectFileEvidence:
    return DirectFileEvidence(
        source_format=source_format,
        probe_bytes_examined=8,
        probe_byte_budget=64,
    )


def _epub() -> ArchiveEvidence:
    return ArchiveEvidence(
        source_format=SourceFormat.EPUB,
        entry_count=4,
        inspected_entry_count=4,
        entry_budget=100,
        total_compressed_bytes=512,
        total_uncompressed_bytes=1024,
        uncompressed_byte_budget=4096,
        compression_ratio_limit=10,
        probe_bytes_examined=128,
        probe_byte_budget=1024,
        epub_mimetype_verified=True,
        epub_container_verified=True,
    )


def _comic(source_format: SourceFormat = SourceFormat.ZIP) -> ArchiveEvidence:
    return ArchiveEvidence(
        source_format=source_format,
        entry_count=5,
        inspected_entry_count=5,
        entry_budget=100,
        total_compressed_bytes=512,
        total_uncompressed_bytes=1024,
        uncompressed_byte_budget=4096,
        compression_ratio_limit=10,
        probe_bytes_examined=128,
        probe_byte_budget=1024,
        image_entry_count=5,
        comic_archive_verified=True,
    )


def _audio(source_format: SourceFormat = SourceFormat.MP3) -> AudioEvidence:
    return AudioEvidence(
        source_format=source_format,
        codec=(
            AudioCodec.MPEG_LAYER_III
            if source_format is SourceFormat.MP3
            else AudioCodec.AAC
        ),
        probe_bytes_examined=32,
        probe_byte_budget=256,
    )


def test_topology_v1_source_formats_are_closed_and_do_not_include_fb2_or_generic_audio() -> (
    None
):
    assert tuple(item.value for item in SourceFormat) == (
        "EPUB",
        "MOBI",
        "AZW",
        "AZW3",
        "PRC",
        "TXT",
        "PDF",
        "CBZ",
        "CBR",
        "RAR",
        "ZIP",
        "MP3",
        "M4A",
        "M4B",
    )
    assert "FB2" not in SourceFormat.__members__
    assert "AUDIO" not in SourceFormat.__members__
    assert "AUDIOBOOK" not in SourceFormat.__members__


@pytest.mark.parametrize(
    ("component", "expected"),
    [
        ("disc1", 1),
        ("Disc 2", 2),
        ("CD_3", 3),
        ("disk-4", 4),
        ("DISK.5", 5),
    ],
)
def test_disc_component_parser_accepts_only_the_frozen_grammar(
    component: str, expected: int
) -> None:
    assert parse_disc_component(component) == expected


@pytest.mark.parametrize(
    "component",
    [
        "disc 01",
        "disc0",
        "disc +1",
        " disc1",
        "disc1 ",
        "discs1",
        "volume1",
        "ｄｉｓｃ1",
        "",
    ],
)
def test_disc_component_parser_rejects_near_matches(component: str) -> None:
    assert parse_disc_component(component) is None


def test_system_noise_allowlist_is_exact_and_does_not_ignore_other_hidden_names() -> (
    None
):
    assert ".DS_Store" in SYSTEM_NOISE_NAMES
    assert is_system_noise_name(".DS_Store")
    assert is_system_noise_name("Thumbs.db")
    assert not is_system_noise_name("thumbs.db")
    assert not is_system_noise_name(".hidden-book.epub")
    assert not is_system_noise_name("._book.epub")


def test_primary_evidence_maps_to_typed_layout_input_without_filename_inference() -> (
    None
):
    admitted = SourceAdmissionEvidence(
        relative_path=("opaque.bin",),
        entry_type=EntryType.FILE,
        admission=AdmissionKind.PRIMARY,
        source_format=SourceFormat.PDF,
        evidence=_direct(SourceFormat.PDF),
    )

    entry = admitted.to_probed_entry()

    assert entry.relative_path == ("opaque.bin",)
    assert entry.source_format is SourceFormat.PDF
    assert entry.sidecar_role is None


def test_primary_requires_matching_format_specific_evidence() -> None:
    with pytest.raises(TypeError, match="DirectFileEvidence"):
        SourceAdmissionEvidence(
            relative_path=("book.pdf",),
            entry_type=EntryType.FILE,
            admission=AdmissionKind.PRIMARY,
            source_format=SourceFormat.PDF,
            evidence=None,
        )

    with pytest.raises(ValueError, match="does not match"):
        SourceAdmissionEvidence(
            relative_path=("book.pdf",),
            entry_type=EntryType.FILE,
            admission=AdmissionKind.PRIMARY,
            source_format=SourceFormat.PDF,
            evidence=_direct(SourceFormat.TXT),
        )

    admitted = SourceAdmissionEvidence(
        relative_path=("book.epub",),
        entry_type=EntryType.FILE,
        admission=AdmissionKind.PRIMARY,
        source_format=SourceFormat.EPUB,
        evidence=_epub(),
    )
    assert admitted.to_probed_entry().source_format is SourceFormat.EPUB


def test_epub_and_comic_archives_require_complete_verified_container_evidence() -> None:
    with pytest.raises(ValueError, match="mimetype and container"):
        ArchiveEvidence(
            source_format=SourceFormat.EPUB,
            entry_count=1,
            inspected_entry_count=1,
            entry_budget=10,
            total_compressed_bytes=8,
            total_uncompressed_bytes=8,
            uncompressed_byte_budget=16,
            compression_ratio_limit=10,
            probe_bytes_examined=8,
            probe_byte_budget=16,
            epub_mimetype_verified=True,
        )

    with pytest.raises(ValueError, match="image ownership"):
        ArchiveEvidence(
            source_format=SourceFormat.ZIP,
            entry_count=1,
            inspected_entry_count=1,
            entry_budget=10,
            total_compressed_bytes=8,
            total_uncompressed_bytes=8,
            uncompressed_byte_budget=16,
            compression_ratio_limit=10,
            probe_bytes_examined=8,
            probe_byte_budget=16,
        )

    assert _comic(SourceFormat.CBZ).comic_archive_verified
    assert _comic(SourceFormat.CBR).image_entry_count == 5
    assert _comic(SourceFormat.RAR).source_format is SourceFormat.RAR
    assert _comic(SourceFormat.ZIP).source_format is SourceFormat.ZIP


def test_archive_and_direct_evidence_enforce_declared_probe_budgets() -> None:
    with pytest.raises(ValueError, match="declared budget"):
        DirectFileEvidence(
            source_format=SourceFormat.PDF,
            probe_bytes_examined=65,
            probe_byte_budget=64,
        )

    with pytest.raises(ValueError, match="inspect every entry"):
        ArchiveEvidence(
            source_format=SourceFormat.ZIP,
            entry_count=2,
            inspected_entry_count=1,
            entry_budget=10,
            total_compressed_bytes=8,
            total_uncompressed_bytes=8,
            uncompressed_byte_budget=16,
            compression_ratio_limit=10,
            probe_bytes_examined=8,
            probe_byte_budget=16,
            image_entry_count=1,
            comic_archive_verified=True,
        )

    with pytest.raises(ValueError, match="uncompressed bytes"):
        replace(
            _comic(),
            total_uncompressed_bytes=4097,
            uncompressed_byte_budget=4096,
        )

    with pytest.raises(ValueError, match="compression ratio"):
        replace(
            _comic(),
            total_compressed_bytes=100,
            total_uncompressed_bytes=1001,
            uncompressed_byte_budget=4096,
            compression_ratio_limit=10,
        )


@pytest.mark.parametrize(
    ("source_format", "codec"),
    [
        (SourceFormat.MP3, AudioCodec.MPEG_LAYER_III),
        (SourceFormat.M4A, AudioCodec.AAC),
        (SourceFormat.M4B, AudioCodec.AAC),
    ],
)
def test_audio_admission_requires_matching_codec_evidence(
    source_format: SourceFormat, codec: AudioCodec
) -> None:
    evidence = _audio(source_format)
    assert evidence.codec is codec
    admitted = SourceAdmissionEvidence(
        relative_path=("track.data",),
        entry_type=EntryType.FILE,
        admission=AdmissionKind.AUDIO_TRACK,
        source_format=source_format,
        evidence=evidence,
    )
    assert admitted.to_probed_entry().source_format is source_format


def test_audio_codec_mismatch_and_generic_audio_format_are_impossible() -> None:
    with pytest.raises(ValueError, match="does not match"):
        AudioEvidence(
            source_format=SourceFormat.MP3,
            codec=AudioCodec.AAC,
            probe_bytes_examined=8,
            probe_byte_budget=16,
        )
    with pytest.raises(ValueError, match="audio source format"):
        SourceAdmissionEvidence(
            relative_path=("book.pdf",),
            entry_type=EntryType.FILE,
            admission=AdmissionKind.AUDIO_TRACK,
            source_format=SourceFormat.PDF,
            evidence=_direct(SourceFormat.PDF),
        )


def test_sidecars_carry_only_a_typed_role() -> None:
    admitted = SourceAdmissionEvidence(
        relative_path=("book.opf",),
        entry_type=EntryType.FILE,
        admission=AdmissionKind.SIDECAR,
        sidecar_role=SidecarRole.OPF,
    )
    assert admitted.to_probed_entry().sidecar_role is SidecarRole.OPF

    with pytest.raises(ValueError, match="carry only"):
        SourceAdmissionEvidence(
            relative_path=("book.opf",),
            entry_type=EntryType.FILE,
            admission=AdmissionKind.SIDECAR,
            sidecar_role=SidecarRole.OPF,
            evidence=_direct(),
        )


def test_complete_bundle_evidence_is_bounded_and_maps_to_a_neutral_directory() -> None:
    bundle = BundleEvidence(
        entry_count=7,
        audio_track_count=5,
        disc_directory_count=2,
        entry_budget=100,
    )
    admitted = SourceAdmissionEvidence(
        relative_path=("audio-volume",),
        entry_type=EntryType.DIRECTORY,
        admission=AdmissionKind.IGNORED,
        evidence=bundle,
    )
    entry = admitted.to_probed_entry()
    assert entry.entry_type is EntryType.DIRECTORY
    assert entry.source_format is None

    with pytest.raises(ValueError, match="declared budget"):
        BundleEvidence(
            entry_count=101,
            audio_track_count=100,
            disc_directory_count=1,
            entry_budget=100,
        )


@pytest.mark.parametrize(
    "reason",
    [
        AdmissionRejectionReason.UNSUPPORTED_EXTENSION,
        AdmissionRejectionReason.SIGNATURE_MISMATCH,
        AdmissionRejectionReason.CORRUPT_SOURCE,
        AdmissionRejectionReason.ENCRYPTED_ARCHIVE,
        AdmissionRejectionReason.UNSAFE_ARCHIVE_PATH,
        AdmissionRejectionReason.PROBE_BUDGET_EXCEEDED,
    ],
)
def test_completed_file_rejections_are_non_exception_unsupported_observations(
    reason: AdmissionRejectionReason,
) -> None:
    rejection = SourceAdmissionRejection(
        relative_path=("candidate.bin",),
        entry_type=EntryType.FILE,
        reason=reason,
    )
    entry = rejection.to_probed_entry()
    assert entry.admission is AdmissionKind.UNSUPPORTED
    assert entry.source_format is None
    assert entry.sidecar_role is None


@pytest.mark.parametrize(
    ("entry_type", "reason"),
    [
        (EntryType.SYMLINK, AdmissionRejectionReason.SYMLINK_NOT_ALLOWED),
        (EntryType.JUNCTION, AdmissionRejectionReason.JUNCTION_NOT_ALLOWED),
    ],
)
def test_links_are_ignored_observations_without_format(
    entry_type: EntryType, reason: AdmissionRejectionReason
) -> None:
    entry = SourceAdmissionRejection(
        relative_path=("linked-source",),
        entry_type=entry_type,
        reason=reason,
    ).to_probed_entry()
    assert entry.admission is AdmissionKind.IGNORED
    assert entry.source_format is None


def test_rejection_reason_must_match_link_entry_type() -> None:
    with pytest.raises(ValueError, match="symlink entry"):
        SourceAdmissionRejection(
            relative_path=("ordinary.file",),
            entry_type=EntryType.FILE,
            reason=AdmissionRejectionReason.SYMLINK_NOT_ALLOWED,
        )
