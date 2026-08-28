package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.RemoteReflowableReaderSource
import com.ermao.library.shared.modules.reader.domain.ReaderError
import com.ermao.library.shared.modules.reader.domain.ReaderErrorCode
import com.ermao.library.shared.modules.reader.domain.readerErrorCodeForFailure
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlin.text.CharacterCodingException
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

data class OnlinePublicationResource(val href: String, val mediaType: String)

data class OnlinePublicationMetadata(
    val manifestJson: String,
    val positionsJson: String,
    val readingOrder: List<OnlinePublicationResource>,
    val resources: List<OnlinePublicationResource>,
)

enum class OnlinePublicationStage(val wireValue: String) {
    Manifest("manifest"),
    Positions("positions"),
    Chapter("chapter"),
    Resource("resource"),
}

sealed interface OnlinePublicationReadResult {
    data class Content(val bytes: ByteArray) : OnlinePublicationReadResult
    data class Failure(
        val code: String,
        val stage: OnlinePublicationStage? = null,
        val cause: Throwable? = null,
        val source: String = "server",
    ) : OnlinePublicationReadResult {
        val errorCode: ReaderErrorCode
            get() = readerErrorCodeForFailure(code, false)
        val readerError: ReaderError
            get() = onlinePublicationReaderError(code, stage, cause, source)
    }
}

/** The transport can only read a bounded publication resource, never publish an offline file. */
interface PublicationResourcePort {
    suspend fun read(apiPath: String, maximumBytes: Int, mediaTypes: Set<String>): OnlinePublicationReadResult
    fun close()
}

class OnlinePublicationFailure(
    val code: String,
    val stage: OnlinePublicationStage? = null,
    cause: Throwable? = null,
    val source: String = "application",
) : Exception(code, cause) {
    val errorCode: ReaderErrorCode
        get() = readerErrorCodeForFailure(code, false)
    val readerError: ReaderError
        get() = onlinePublicationReaderError(code, stage, cause, source)

    companion object {
        /** Translates a decoder rejection without adding metadata validation. */
        @Throws(IllegalArgumentException::class)
        fun invalidMetadata(stage: OnlinePublicationStage, cause: Throwable? = null): OnlinePublicationFailure =
            OnlinePublicationFailure(
                code = when (stage) {
                    OnlinePublicationStage.Manifest -> "PUBLICATION_MANIFEST_INVALID"
                    OnlinePublicationStage.Positions -> "PUBLICATION_POSITIONS_INVALID"
                    else -> throw IllegalArgumentException("Metadata failures require a manifest or positions stage")
                },
                stage = stage,
                cause = cause,
                source = "parser",
            )
    }
}

private fun onlinePublicationReaderError(code: String, stage: OnlinePublicationStage?, cause: Throwable?, source: String): ReaderError = ReaderError(
    code = readerErrorCodeForFailure(code, false),
    safeContext = buildMap {
        put("code", code)
        put("source", source)
        stage?.let { put("stage", it.wireValue) }
    },
    cause = cause,
)

/** One account-scoped reading session owns validation, request coalescing and the body window. */
class OnlinePublicationSession(
    private val source: RemoteReflowableReaderSource,
    private val port: PublicationResourcePort,
) {
    private data class State(
        val closed: Boolean = false,
        val chapterHref: String? = null,
        val bodies: Map<String, ByteArray> = emptyMap(),
    )
    private val state = MutableStateFlow(State())
    private val requests = Mutex()
    private val json = Json { ignoreUnknownKeys = true }
    private var metadata: OnlinePublicationMetadata? = null

    @Throws(OnlinePublicationFailure::class, CancellationException::class)
    suspend fun open(): OnlinePublicationMetadata = requests.withLock {
        checkOpen(OnlinePublicationStage.Manifest)
        metadata?.let { return@withLock it }
        val manifestText = requiredText(source.manifestApiPath, OnlinePublicationStage.Manifest)
        val (order, resources) = validateMetadata(OnlinePublicationStage.Manifest) {
            val manifest = json.decodeFromString<ManifestWire>(manifestText)
            require(manifest.readingOrder.isNotEmpty())
            val order = manifest.readingOrder.map { it.validated() }
            val resources = manifest.resources.map { it.validated() }
            require((order + resources).map { it.href }.distinct().size == order.size + resources.size)
            order to resources
        }
        val positionsText = requiredText(source.positionsApiPath, OnlinePublicationStage.Positions)
        validateMetadata(OnlinePublicationStage.Positions) {
            val positions = json.decodeFromString<PositionsWire>(positionsText)
            require(positions.positions.isNotEmpty() && positions.positions.all { position ->
                order.any { it.href == position.href && it.mediaType == position.type }
            })
        }
        checkOpen(OnlinePublicationStage.Positions)
        OnlinePublicationMetadata(manifestText, positionsText, order, resources).also { metadata = it }
    }

    @Throws(OnlinePublicationFailure::class, CancellationException::class)
    suspend fun read(href: String): OnlinePublicationReadResult = requests.withLock {
        val stage = if (metadata?.readingOrder?.any { it.href == href } == true) {
            OnlinePublicationStage.Chapter
        } else OnlinePublicationStage.Resource
        if (state.value.closed) return@withLock OnlinePublicationReadResult.Failure("PUBLICATION_CLOSED", stage)
        val publication = metadata ?: return@withLock OnlinePublicationReadResult.Failure("PUBLICATION_NOT_OPEN", stage)
        val resource = (publication.readingOrder + publication.resources).firstOrNull { it.href == href }
            ?: return@withLock OnlinePublicationReadResult.Failure("PUBLICATION_RESOURCE_NOT_FOUND", stage)
        val chapterIndex = publication.readingOrder.indexOfFirst { it.href == href }
        if (chapterIndex >= 0) {
            val window = publication.readingOrder
                .slice(maxOf(0, chapterIndex - 1)..minOf(publication.readingOrder.lastIndex, chapterIndex + 1))
                .map { it.href }.toSet()
            state.update { current ->
                if (current.closed || current.chapterHref == href) current
                // Ancillary resources belong to the chapter that requested them. Never
                // carry old images/fonts across an unbounded sequence of chapter visits.
                else current.copy(chapterHref = href, bodies = current.bodies.filterKeys { it in window })
            }
        }
        state.value.bodies[href]?.let { return@withLock OnlinePublicationReadResult.Content(it) }
        val result = port.read(
            source.manifestApiPath.removeSuffix("manifest.json") + href,
            if (resource.mediaType in MARKUP_TYPES) MAXIMUM_CHAPTER_BYTES else MAXIMUM_RESOURCE_BYTES,
            setOf(resource.mediaType),
        )
        if (state.value.closed) return@withLock OnlinePublicationReadResult.Failure("PUBLICATION_CLOSED", stage)
        if (result is OnlinePublicationReadResult.Content) {
            state.update { current ->
                if (current.closed) current else {
                    val retained = current.bodies.toMutableMap()
                    retained.remove(href)
                    retained[href] = result.bytes
                    var size = retained.values.sumOf { it.size.toLong() }
                    while (size > MAXIMUM_CACHE_BYTES || retained.size > MAXIMUM_CACHED_RESOURCES) {
                        val oldest = retained.keys.first()
                        size -= requireNotNull(retained.remove(oldest)).size
                    }
                    current.copy(bodies = retained)
                }
            }
        }
        when (result) {
            is OnlinePublicationReadResult.Content -> result
            is OnlinePublicationReadResult.Failure -> result.copy(stage = stage)
        }
    }

    fun close() {
        state.update { State(closed = true) }
        port.close()
    }

    private fun checkOpen(stage: OnlinePublicationStage) {
        if (state.value.closed) throw OnlinePublicationFailure("PUBLICATION_CLOSED", stage)
    }

    private suspend fun requiredText(path: String, stage: OnlinePublicationStage): String =
        when (val result = port.read(path, MAXIMUM_CHAPTER_BYTES, JSON_TYPES)) {
            is OnlinePublicationReadResult.Content -> validateMetadata(stage) {
                result.bytes.decodeToString(throwOnInvalidSequence = true)
            }
            is OnlinePublicationReadResult.Failure -> throw OnlinePublicationFailure(result.code, stage, result.cause, result.source)
        }

    private inline fun <T> validateMetadata(stage: OnlinePublicationStage, decode: () -> T): T = try {
        decode()
    } catch (error: CharacterCodingException) {
        throw OnlinePublicationFailure.invalidMetadata(stage, error)
    } catch (error: IllegalArgumentException) {
        throw OnlinePublicationFailure.invalidMetadata(stage, error)
    }

    @Serializable
    private data class ManifestWire(val readingOrder: List<LinkWire>, val resources: List<LinkWire> = emptyList())

    @Serializable
    private data class PositionsWire(val positions: List<LinkWire>)

    @Serializable
    private data class LinkWire(val href: String, val type: String) {
        fun validated(): OnlinePublicationResource {
            require(href.isNotBlank() && !href.startsWith('/'))
            val encoded = href.encodeToByteArray()
            val bytes = ByteArray(encoded.size)
            var input = 0
            var output = 0
            while (input < encoded.size) {
                val value = encoded[input++].toInt() and 0xff
                if (value != '%'.code) bytes[output++] = value.toByte()
                else {
                    require(input + 2 <= encoded.size)
                    val hex = encoded.copyOfRange(input, input + 2).decodeToString()
                    val decodedByte = requireNotNull(hex.toIntOrNull(16))
                    // Reject encoded path delimiters and double escaping before decoding UTF-8.
                    require(decodedByte.toChar() !in "/\\?#:%")
                    bytes[output++] = decodedByte.toByte()
                    input += 2
                }
            }
            val decoded = try { bytes.decodeToString(endIndex = output, throwOnInvalidSequence = true) }
            catch (error: CharacterCodingException) {
                throw IllegalArgumentException("PUBLICATION_RESOURCE_HREF_INVALID", error)
            }
            require(decoded.none { it.isISOControl() || it in ":\\?#" } &&
                decoded.split('/').none { it.isBlank() || it == "." || it == ".." })
            require(type.isNotBlank())
            return OnlinePublicationResource(href, type)
        }
    }

    private companion object {
        const val MAXIMUM_CHAPTER_BYTES = 8 * 1024 * 1024
        const val MAXIMUM_RESOURCE_BYTES = 32 * 1024 * 1024
        const val MAXIMUM_CACHE_BYTES = 64L * 1024 * 1024
        const val MAXIMUM_CACHED_RESOURCES = 64
        val MARKUP_TYPES = setOf("application/xhtml+xml", "text/html")
        val JSON_TYPES = setOf("application/json", "application/webpub+json", "application/vnd.readium.position-list+json")
    }
}
