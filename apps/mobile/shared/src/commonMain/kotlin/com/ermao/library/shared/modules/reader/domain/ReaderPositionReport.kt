package com.ermao.library.shared.modules.reader.domain

import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/**
 * The Locator emitted by the active Reader engine.
 *
 * This value is deliberately not projected into a KMP location model.  Reader
 * engines own the shape of this object; KMP only validates the transport
 * boundary, bounds its compact representation and carries it unchanged.
 */
class ReaderOpaqueLocator private constructor(
    val canonicalJson: String,
) {
    init {
        require(canonicalJson.encodeToByteArray().size <= MAXIMUM_BYTES) {
            "Reader Locator exceeds 64 KiB"
        }
    }

    companion object {
        const val MAXIMUM_BYTES = 65_536

        @Throws(IllegalArgumentException::class)
        fun parse(json: String): ReaderOpaqueLocator {
            require(json.isNotBlank()) { "Reader Locator is blank" }
            val element = try {
                Json.parseToJsonElement(json)
            } catch (error: SerializationException) {
                throw IllegalArgumentException("Reader Locator is malformed", error)
            }
            require(element is JsonObject) { "Reader Locator must be a JSON object" }
            return ReaderOpaqueLocator(element.toString())
        }
    }

    override fun equals(other: Any?): Boolean =
        other is ReaderOpaqueLocator && canonicalJson == other.canonicalJson

    override fun hashCode(): Int = canonicalJson.hashCode()

    override fun toString(): String = canonicalJson
}

data class ReaderChapterPresentation(
    val href: String?,
    val title: String?,
    val index: Int?,
) {
    init {
        require(href == null || href.length <= MAXIMUM_HREF_LENGTH)
        require(title == null || title.length <= MAXIMUM_TITLE_LENGTH)
        require(index == null || index >= 0)
    }
}

data class ReaderPagePresentation(
    val number: Int,
    val total: Int?,
) {
    init {
        require(number >= 1)
        require(total == null || total >= 1)
    }
}

data class ReaderPlaybackPresentation(
    val positionMillis: Long,
    val durationMillis: Long?,
) {
    init {
        require(positionMillis >= 0)
        require(durationMillis == null || durationMillis >= 0)
    }
}

/** Presentation is a sibling of the opaque Locator, never a Locator projection. */
data class ReaderPositionPresentation(
    val displayPercent: Double,
    val totalProgression: Double,
    val currentHref: String?,
    val chapter: ReaderChapterPresentation?,
    val page: ReaderPagePresentation?,
    val playback: ReaderPlaybackPresentation?,
) {
    init {
        require(displayPercent.isFinite() && displayPercent in 0.0..100.0) {
            "Reader display percent is outside 0..100"
        }
        require(totalProgression.isFinite() && totalProgression in 0.0..1.0) {
            "Reader total progression is outside 0..1"
        }
        require(currentHref == null || currentHref.length <= MAXIMUM_HREF_LENGTH)
    }
}

/** The only position value exchanged by Reader v5. */
data class ReaderPositionReport(
    val locator: ReaderOpaqueLocator,
    val presentation: ReaderPositionPresentation,
)

/** Server state returned by Reader v5 GET and PUT. */
data class ReaderProgressSnapshotV5(
    val resourceId: String,
    val clientId: String,
    val revision: Long,
    val mutationId: String,
    val capturedAtEpochMillis: Long,
    val receivedAtEpochMillis: Long,
    val position: ReaderPositionReport,
) {
    init {
        require(resourceId.isNotBlank())
        requireReaderClientId(clientId)
        requireReaderMutationId(mutationId)
        require(revision > 0)
        require(capturedAtEpochMillis >= 0)
        require(receivedAtEpochMillis >= 0)
    }
}

/** Latest-only durable outbox entry. There is intentionally no base revision. */
data class ReaderProgressMutationV5(
    val resourceId: String,
    val clientId: String,
    val mutationId: String,
    val capturedAtEpochMillis: Long,
    val position: ReaderPositionReport,
) {
    init {
        require(resourceId.isNotBlank())
        requireReaderClientId(clientId)
        requireReaderMutationId(mutationId)
        require(capturedAtEpochMillis >= 0)
    }
}

data class ReaderPositionLocalState(
    val resourceId: String,
    val clientId: String,
    val capturedAtEpochMillis: Long,
    val position: ReaderPositionReport,
) {
    init {
        require(resourceId.isNotBlank())
        requireReaderClientId(clientId)
        require(capturedAtEpochMillis >= 0)
    }

    fun toMutation(mutationId: String): ReaderProgressMutationV5 = ReaderProgressMutationV5(
        resourceId = resourceId,
        clientId = clientId,
        mutationId = mutationId,
        capturedAtEpochMillis = capturedAtEpochMillis,
        position = position,
    )
}

/** Read-only projection used by library surfaces; it deliberately contains no Locator. */
data class ReaderPositionPresentationSnapshot(
    val bookId: String,
    val resourceId: String,
    val capturedAtEpochMillis: Long,
    val presentation: ReaderPositionPresentation,
) {
    init {
        require(bookId.isNotBlank()) { "Reader presentation book id is blank" }
        require(resourceId.isNotBlank()) { "Reader presentation resource id is blank" }
        require(capturedAtEpochMillis >= 0) { "Reader presentation capture time is negative" }
    }
}

private const val MAXIMUM_HREF_LENGTH = 8_192
private const val MAXIMUM_TITLE_LENGTH = 4_096

internal fun requireReaderMutationId(value: String): String {
    require(READER_MUTATION_ID_PATTERN.matches(value)) {
        "Reader mutation id must be a UUID"
    }
    return value
}

internal fun requireReaderClientId(value: String): String {
    require(value.length in 1..MAXIMUM_CLIENT_ID_LENGTH && value.any { !it.isWhitespace() }) {
        "Reader client id must be 1..256 characters and contain a non-whitespace character"
    }
    return value
}

private val READER_MUTATION_ID_PATTERN = Regex(
    "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
)

private const val MAXIMUM_CLIENT_ID_LENGTH = 256
