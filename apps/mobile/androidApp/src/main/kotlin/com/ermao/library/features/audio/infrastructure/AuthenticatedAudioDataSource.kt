package com.ermao.library.features.audio.infrastructure

import android.content.Context
import android.net.Uri
import androidx.media3.common.C
import androidx.media3.datasource.DataSource
import androidx.media3.datasource.DataSpec
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.datasource.TransferListener
import com.ermao.library.shared.modules.audio.AudioAsset
import com.ermao.library.shared.modules.audio.AudioMediaContent
import com.ermao.library.shared.modules.audio.AudioMediaOpenFailure
import com.ermao.library.shared.modules.audio.AudioMediaTransport
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking

/**
 * Request context handed to the shared authenticated media transport.
 *
 * The Android player never constructs cookies, TLS settings, redirect rules, or authorization
 * headers. The KMP/network composition root supplies this port and retains ownership of all
 * response validation.
 */
data class AuthenticatedAudioDataSourceRequest(
    val namespaceKey: String,
    val uri: Uri,
    val dataSpec: DataSpec,
) {
    init {
        require(namespaceKey.isNotBlank()) { "Audio media namespace is blank" }
        require(uri.scheme.equals("http", ignoreCase = true) || uri.scheme.equals("https", ignoreCase = true)) {
            "Authenticated audio transport requires an HTTP(S) URI"
        }
    }
}

fun interface AuthenticatedAudioDataSourceProvider {
    /** Creates one request-scoped source while preserving shared cancellation and Range rules. */
    fun create(request: AuthenticatedAudioDataSourceRequest): DataSource
}

/** Stable failure used when a namespace has no authenticated KMP transport registration. */
class AuthenticatedAudioTransportUnavailableException : IOException(
    "AUDIO_AUTHENTICATED_STREAM_UNAVAILABLE",
)

/**
 * Process-level composition registry. Entries are replaced atomically when the verified session
 * or server changes, so a stale Media3 callback cannot use another namespace's transport.
 */
class AndroidAudioTransportRegistry {
    private val registrations = ConcurrentHashMap<String, Registration>()

    fun register(
        namespaceKey: String,
        transport: AudioMediaTransport,
        assetsByUri: Map<String, AudioAsset>,
    ) {
        require(namespaceKey.isNotBlank()) { "Audio transport namespace is blank" }
        require(assetsByUri.isNotEmpty()) { "Audio transport requires at least one asset" }
        registrations[namespaceKey] = Registration(transport, assetsByUri.toMap())
    }

    fun remove(namespaceKey: String) {
        registrations.remove(namespaceKey)
    }

    fun clear() {
        registrations.clear()
    }

    internal fun resolve(namespaceKey: String, uri: Uri): ResolvedAsset? {
        val registration = registrations[namespaceKey] ?: return null
        val asset = registration.assetsByUri[uri.toString()] ?: return null
        return ResolvedAsset(registration.transport, asset)
    }

    private data class Registration(
        val transport: AudioMediaTransport,
        val assetsByUri: Map<String, AudioAsset>,
    )

    internal data class ResolvedAsset(
        val transport: AudioMediaTransport,
        val asset: AudioAsset,
    )
}

/** Media3 adapter over the shared KMP incremental authenticated-stream port. */
class RegisteredAuthenticatedAudioDataSourceProvider(
    private val registry: AndroidAudioTransportRegistry,
) : AuthenticatedAudioDataSourceProvider {
    override fun create(request: AuthenticatedAudioDataSourceRequest): DataSource {
        val resolved = registry.resolve(request.namespaceKey, request.uri)
            ?: throw AuthenticatedAudioTransportUnavailableException()
        return KmpAudioMediaDataSource(
            transport = resolved.transport,
            asset = resolved.asset,
            sourceUri = request.uri,
        )
    }
}

/**
 * Fail-closed composition fallback used before a verified session registers a KMP transport.
 * Local `file://`, `content://`, and `asset://` artifacts remain available through the factory.
 */
object RejectingAuthenticatedAudioDataSourceProvider : AuthenticatedAudioDataSourceProvider {
    override fun create(request: AuthenticatedAudioDataSourceRequest): DataSource {
        throw AuthenticatedAudioTransportUnavailableException()
    }
}

/**
 * Adapts shared authenticated streams to Media3 while leaving local artifact handling to the
 * platform. Each engine read awaits only one bounded chunk; the response is never fully buffered.
 */
class LocalOrAuthenticatedAudioDataSourceFactory(
    private val context: Context,
    private val provider: AuthenticatedAudioDataSourceProvider,
) : DataSource.Factory {
    private val localFactory = DefaultDataSource.Factory(context.applicationContext)

    override fun createDataSource(): DataSource = LocalOrAuthenticatedAudioDataSource(
        localFactory = localFactory,
        provider = provider,
    )
}

private class LocalOrAuthenticatedAudioDataSource(
    private val localFactory: DataSource.Factory,
    private val provider: AuthenticatedAudioDataSourceProvider,
) : DataSource {
    private val transferListeners = mutableListOf<TransferListener>()
    private var delegate: DataSource? = null

    override fun addTransferListener(transferListener: TransferListener) {
        transferListeners += transferListener
        delegate?.addTransferListener(transferListener)
    }

    override fun open(dataSpec: DataSpec): Long {
        val uri = dataSpec.uri
        val scheme = uri.scheme?.lowercase()
        val selected = when (scheme) {
            "file", "content", "asset" -> localFactory.createDataSource()
            "http", "https" -> {
                val namespaceKey = dataSpec.key
                    ?.takeIf(String::isNotBlank)
                    ?: throw AuthenticatedAudioTransportUnavailableException()
                provider.create(
                    AuthenticatedAudioDataSourceRequest(
                        namespaceKey = namespaceKey,
                        uri = uri,
                        dataSpec = dataSpec,
                    ),
                )
            }
            else -> throw IOException("AUDIO_MEDIA_SCHEME_UNSUPPORTED")
        }
        delegate = selected
        transferListeners.forEach(selected::addTransferListener)
        return try {
            selected.open(dataSpec)
        } catch (error: Throwable) {
            delegate = null
            runCatching { selected.close() }
            throw error
        }
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int =
        (delegate ?: throw IOException("AUDIO_DATA_SOURCE_NOT_OPEN")).read(buffer, offset, length)

    override fun getUri(): Uri? = delegate?.uri

    override fun close() {
        val active = delegate ?: return
        delegate = null
        active.close()
    }
}

private class KmpAudioMediaDataSource(
    private val transport: AudioMediaTransport,
    private val asset: AudioAsset,
    private val sourceUri: Uri,
) : DataSource {
    private var stream: com.ermao.library.shared.modules.audio.AudioMediaStream? = null

    override fun addTransferListener(transferListener: TransferListener) = Unit

    override fun open(dataSpec: DataSpec): Long {
        val rangeStart = dataSpec.position
        require(rangeStart >= 0) { "Audio range start is negative" }
        if (rangeStart >= asset.sizeBytes) throw IOException("AUDIO_RANGE_INVALID")
        val rangeEnd = dataSpec.length
            .takeIf { it != C.LENGTH_UNSET.toLong() }
            ?.let { length ->
                if (length <= 0) throw IOException("AUDIO_RANGE_INVALID")
                rangeStart + length - 1
            }
        val opened = runBlocking(Dispatchers.IO) {
            transport.open(asset, rangeStart = rangeStart, rangeEndInclusive = rangeEnd)
        }
        val content = when (opened) {
            is AudioMediaContent -> opened.stream
            is AudioMediaOpenFailure -> throw IOException(opened.error.code)
        }
        stream = content
        return content.metadata.contentLength ?: C.LENGTH_UNSET.toLong()
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        if (length == 0) return 0
        val active = stream ?: throw IOException("AUDIO_DATA_SOURCE_NOT_OPEN")
        val chunk = runBlocking(Dispatchers.IO) { active.read(length) }
        if (chunk.isEmpty()) return C.RESULT_END_OF_INPUT
        chunk.copyInto(buffer, destinationOffset = offset, startIndex = 0, endIndex = chunk.size)
        return chunk.size
    }

    override fun getUri(): Uri = sourceUri

    override fun close() {
        stream?.close()
        stream = null
    }
}
