package com.ermao.library.shared.modules.reader.domain

sealed interface ReaderLocation

data class ReflowReaderLocation(
    val resourceKey: String? = null,
    val progression: Double? = null,
    val totalProgression: Double? = null,
    val position: Int? = null,
) : ReaderLocation {
    init {
        require(resourceKey == null || resourceKey.isNotBlank()) { "Reflow resource key is blank" }
        require(progression == null || progression.isFinite() && progression in PROGRESSION_RANGE) {
            "Resource progression is outside 0..1"
        }
        require(totalProgression == null || totalProgression.isFinite() && totalProgression in PROGRESSION_RANGE) {
            "Total progression is outside 0..1"
        }
        require(position == null || position > 0) { "Reflow position must be positive" }
        require(resourceKey != null || progression != null || position != null) {
            "Reflow location requires at least one anchor"
        }
    }
}

data class PdfReaderLocation(
    val pageIndex: Int,
    val pageProgression: Double,
) : ReaderLocation {
    init {
        require(pageIndex >= 0) { "PDF page index is negative" }
        require(pageProgression.isFinite() && pageProgression in PROGRESSION_RANGE) {
            "PDF page progression is outside 0..1"
        }
    }
}

data class ComicReaderLocation(
    val resourceHref: String,
    val pageIndex: Int,
) : ReaderLocation {
    init {
        require(resourceHref.isNotBlank()) { "Comic resource href is blank" }
        require(pageIndex >= 0) { "Comic page index is negative" }
    }
}

data class AudioReaderLocation(
    val assetId: String,
    val chapterId: String? = null,
    val positionMillis: Long,
) : ReaderLocation {
    init {
        require(assetId.isNotBlank()) { "Audio asset id is blank" }
        require(chapterId == null || chapterId.isNotBlank()) { "Audio chapter id is blank" }
        require(positionMillis >= 0) { "Audio position is negative" }
    }
}

private val PROGRESSION_RANGE = 0.0..1.0
