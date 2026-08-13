package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

enum class ReaderEngine(val wireValue: String) {
    Readium("readium"),
}

enum class ReaderEnginePlatform(val wireValue: String) {
    Android("android"),
    Ios("ios"),
    Web("web"),
}

/**
 * Versioned engine-owned locator payload.
 *
 * The payload stays opaque to shared domain code and is bounded at the model
 * boundary so neither local persistence nor the server wire can accept an
 * unbounded locator document.
 */
class EngineLocatorPayload private constructor(val canonicalJson: String) {
    init {
        require(canonicalJson.encodeToByteArray().size <= EngineLocator.MAXIMUM_PAYLOAD_BYTES) {
            "Engine locator payload exceeds 64 KiB"
        }
    }

    companion object {
        fun parse(value: String): EngineLocatorPayload {
            require(value.isNotBlank()) { "Engine locator payload is blank" }
            val element = try {
                Json.parseToJsonElement(value)
            } catch (error: SerializationException) {
                throw IllegalArgumentException("Engine locator payload is malformed", error)
            }
            require(element is JsonObject) { "Engine locator payload must be a JSON object" }
            return EngineLocatorPayload(element.toString())
        }
    }

    override fun equals(other: Any?): Boolean =
        other is EngineLocatorPayload && canonicalJson == other.canonicalJson

    override fun hashCode(): Int = canonicalJson.hashCode()

    override fun toString(): String = canonicalJson
}

data class EngineLocator(
    val engine: ReaderEngine,
    val platform: ReaderEnginePlatform,
    val version: String,
    val payload: EngineLocatorPayload,
) {
    init {
        require(version.isNotBlank()) { "Engine locator version is blank" }
        require(version.length <= MAXIMUM_VERSION_LENGTH) { "Engine locator version is too long" }
    }

    companion object {
        const val MAXIMUM_PAYLOAD_BYTES = 65_536
        private const val MAXIMUM_VERSION_LENGTH = 191
    }
}

data class TextQuote(
    val exact: String,
    val prefix: String? = null,
    val suffix: String? = null,
) {
    init {
        require(exact.isNotBlank()) { "Text quote is blank" }
        require(exact.length <= MAXIMUM_EXACT_LENGTH) { "Text quote exact text is too long" }
        require(prefix == null || prefix.isNotBlank()) { "Text quote prefix is blank" }
        require(prefix == null || prefix.length <= MAXIMUM_CONTEXT_LENGTH) { "Text quote prefix is too long" }
        require(suffix == null || suffix.isNotBlank()) { "Text quote suffix is blank" }
        require(suffix == null || suffix.length <= MAXIMUM_CONTEXT_LENGTH) { "Text quote suffix is too long" }
    }

    private companion object {
        const val MAXIMUM_EXACT_LENGTH = 8_192
        const val MAXIMUM_CONTEXT_LENGTH = 4_096
    }
}

sealed interface ReaderLocation {
    val contentFingerprint: ContentFingerprint
}

data class ReflowReaderLocation(
    val resourceKey: String? = null,
    val progression: Double? = null,
    val totalProgression: Double? = null,
    val position: Int? = null,
    val textQuote: TextQuote? = null,
    val engineLocator: EngineLocator? = null,
    override val contentFingerprint: ContentFingerprint,
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
        require(engineLocator != null || resourceKey != null || progression != null || textQuote != null || position != null) {
            "Reflow location requires at least one anchor"
        }
    }
}

data class PdfReaderLocation(
    val pageIndex: Int,
    val pageProgression: Double? = null,
    override val contentFingerprint: ContentFingerprint,
    val engineLocator: EngineLocator? = null,
) : ReaderLocation {
    init {
        require(pageIndex >= 0) { "PDF page index is negative" }
        require(pageProgression == null || pageProgression.isFinite() && pageProgression in PROGRESSION_RANGE) {
            "PDF page progression is outside 0..1"
        }
    }
}

data class ComicReaderLocation(
    val pageIndex: Int,
    override val contentFingerprint: ContentFingerprint,
    val engineLocator: EngineLocator? = null,
) : ReaderLocation {
    init {
        require(pageIndex >= 0) { "Comic page index is negative" }
    }
}

data class AudioReaderLocation(
    val fileId: String,
    val chapterId: String? = null,
    val positionMillis: Long,
    override val contentFingerprint: ContentFingerprint,
    val engineLocator: EngineLocator? = null,
) : ReaderLocation {
    init {
        require(fileId.isNotBlank()) { "Audio file id is blank" }
        require(chapterId == null || chapterId.isNotBlank()) { "Audio chapter id is blank" }
        require(positionMillis >= 0) { "Audio position is negative" }
    }
}

private val PROGRESSION_RANGE = 0.0..1.0

data class ReaderProgress(
    val sourceId: String,
    val location: ReaderLocation,
    val updatedAtEpochMillis: Long,
    val deviceId: String,
    /** Required for non-reflow formats because a page/time anchor cannot imply whole-volume percent. */
    val percent: Double? = null,
) {
    init {
        require(sourceId.isNotBlank()) { "Reader progress source id is blank" }
        require(updatedAtEpochMillis >= 0) { "Reader progress timestamp is negative" }
        require(deviceId.isNotBlank()) { "Reader progress device id is blank" }
        require(percent == null || percent.isFinite() && percent in 0.0..100.0) {
            "Reader progress percent is outside 0..100"
        }
        if (location is ReflowReaderLocation) {
            require(ReadiumLocatorEnvelope.from(location) != null) {
                "Reflow Reader progress requires an exact Readium block locator"
            }
        }
    }
}
