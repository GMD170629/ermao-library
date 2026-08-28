package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.OnlinePublicationSession
import com.ermao.library.shared.modules.reader.application.OnlinePublicationReadResult
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
    private val onFailure: (com.ermao.library.shared.modules.reader.ReaderErrorCode) -> Unit,
) {
    suspend fun open(): Publication {
        val metadata = try { session.open() }
        catch (error: com.ermao.library.shared.modules.reader.application.OnlinePublicationFailure) {
            throw ReaderOpenFailure(com.ermao.library.shared.modules.reader.ReaderError(
                com.ermao.library.shared.modules.reader.readerErrorCodeForFailure(error.code, false),
            ), cause = error)
        }
        val manifest = requireNotNull(Manifest.fromJSON(JSONObject(metadata.manifestJson)))
        val positionsJson = JSONObject(metadata.positionsJson).getJSONArray("positions")
        val positions = (0 until positionsJson.length()).map { index ->
            requireNotNull(Locator.fromJSON(positionsJson.getJSONObject(index)))
        }
        val entries = (metadata.readingOrder + metadata.resources).map { requireNotNull(Url(it.href)) }.toSet()
        val container = object : Container<Resource> {
            override val entries = entries
            override fun get(url: Url): Resource? {
                if (url !in entries) return null
                return LazyResource {
                    when (val result = session.read(url.toString())) {
                        is OnlinePublicationReadResult.Content -> InMemoryResource(result.bytes)
                        is OnlinePublicationReadResult.Failure -> {
                            onFailure(result.errorCode)
                            FailureResource(ReadError.Decoding(IllegalStateException(result.code)))
                        }
                    }
                }
            }
            override fun close() = session.close()
        }
        return Publication(
            manifest = manifest,
            container = EpubContentSecurityPolicy.apply(container),
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
}
