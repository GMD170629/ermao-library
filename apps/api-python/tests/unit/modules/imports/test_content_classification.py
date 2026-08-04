from app.modules.imports.domain.content_classification import (
    ClassificationSource,
    ContentEvidence,
    MediaKindPolicy,
    classify_content,
)


def test_folder_policy_forces_category_without_format_validation() -> None:
    result = classify_content(
        MediaKindPolicy.AUDIOBOOK,
        ContentEvidence(volume_format="EPUB"),
    )
    assert result.media_kind == "AUDIOBOOK"
    assert result.source is ClassificationSource.MONITOR_FOLDER


def test_explicit_comic_subject_is_high_confidence() -> None:
    result = classify_content(
        MediaKindPolicy.MIXED,
        ContentEvidence(volume_format="MOBI", subjects=("manga",)),
    )
    assert result.media_kind == "COMIC"
    assert result.reason == "COMIC_SUBJECT"


def test_fixed_layout_and_image_pdf_are_ebook_suggestions() -> None:
    fixed = classify_content(
        MediaKindPolicy.MIXED,
        ContentEvidence(volume_format="EPUB", fixed_layout=True),
    )
    scanned = classify_content(
        MediaKindPolicy.MIXED,
        ContentEvidence(volume_format="PDF", image_only=True),
    )
    assert (fixed.media_kind, fixed.suggested_media_kind) == ("EBOOK", "COMIC")
    assert (scanned.media_kind, scanned.suggested_media_kind) == ("EBOOK", "COMIC")


def test_audio_and_comic_archives_use_format_defaults() -> None:
    audio = classify_content(
        MediaKindPolicy.MIXED, ContentEvidence(volume_format="M4B")
    )
    comic = classify_content(
        MediaKindPolicy.MIXED, ContentEvidence(volume_format="CBZ")
    )
    assert audio.media_kind == "AUDIOBOOK"
    assert comic.media_kind == "COMIC"
