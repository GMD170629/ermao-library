package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.OnlinePublicationSession
import com.ermao.library.shared.modules.reader.OnlinePublicationFailure
import com.ermao.library.shared.modules.reader.OnlinePublicationReadContent
import com.ermao.library.shared.modules.reader.OnlinePublicationReadFailure
import com.ermao.library.shared.modules.reader.OnlinePublicationStage
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import org.json.JSONException
import org.json.JSONObject
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Manifest
import org.readium.r2.shared.publication.Publication
import org.readium.r2.shared.publication.services.PositionsService
import org.readium.r2.shared.util.Url
import org.readium.r2.shared.util.data.Container
import org.readium.r2.shared.util.data.ReadError
import org.readium.r2.shared.util.resource.FailureResource
import org.readium.r2.shared.util.resource.InMemoryResource
import org.readium.r2.shared.util.resource.LazyResource
import org.readium.r2.shared.util.resource.Resource

/** Native binding only: KMP owns access, validation, cancellation and the bounded body window. */
internal class RemoteReflowableReadiumPublicationFactory(
    private val session: OnlinePublicationSession,
    private val onFailure: (ReaderError) -> Unit,
) {
    suspend fun open(): Publication {
        val metadata = try { session.open() }
        catch (error: OnlinePublicationFailure) {
            throw ReaderOpenFailure(error.readerError, cause = error)
        }
        val manifest = decodeMetadata(OnlinePublicationStage.Manifest) {
            requireNotNull(Manifest.fromJSON(JSONObject(metadata.manifestJson)))
        }
        val positions = decodeMetadata(OnlinePublicationStage.Positions) {
            val positionsJson = JSONObject(metadata.positionsJson).getJSONArray("positions")
            (0 until positionsJson.length()).map { index ->
                requireNotNull(Locator.fromJSON(positionsJson.getJSONObject(index)))
            }
        }
        val entries = (metadata.readingOrder + metadata.resources).map { requireNotNull(Url(it.href)) }.toSet()
        val container = object : Container<Resource> {
            override val entries = entries
            override fun get(url: Url): Resource? {
                if (url !in entries) return null
                return LazyResource {
                    when (val result = session.read(url.toString())) {
                        is OnlinePublicationReadContent -> InMemoryResource(result.bytes)
                        is OnlinePublicationReadFailure -> {
                            onFailure(result.readerError)
                            FailureResource(ReadError.Decoding(IllegalStateException(result.code, result.cause)))
                        }
                    }
                }
            }
            override fun close() = session.close()
        }
        return Publication(
            manifest = manifest,
            container = EpubContentSecurityPolicy.apply(container) { cause ->
                onFailure(ReaderError(
                    ReaderErrorCode.SecurityRejected,
                    mapOf("code" to "PUBLICATION_SECURITY_REJECTED", "stage" to "chapter", "source" to "security"),
                    cause = cause,
                ))
            },
            servicesBuilder = Publication.ServicesBuilder(
                positions = {
                    object : PositionsService {
                        override suspend fun positionsByReadingOrder(): List<List<Locator>> =
                            manifest.readingOrder.map { link -> positions.filter { it.href == link.href } }
                    }
                },
            ),
        )
    }

    private inline fun <T> decodeMetadata(stage: OnlinePublicationStage, decode: () -> T): T = try {
        decode()
    } catch (error: JSONException) {
        throw metadataFailure(stage, error)
    } catch (error: IllegalArgumentException) {
        throw metadataFailure(stage, error)
    }

    private fun metadataFailure(stage: OnlinePublicationStage, cause: Exception): ReaderOpenFailure {
        val failure = OnlinePublicationFailure.invalidMetadata(stage, cause)
        return ReaderOpenFailure(failure.readerError, cause = failure)
    }
}
