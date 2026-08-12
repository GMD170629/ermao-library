package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ContentFingerprint
import com.ermao.library.shared.modules.reader.EngineLocator
import com.ermao.library.shared.modules.reader.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.ReaderEngine
import com.ermao.library.shared.modules.reader.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.TextQuote
import org.json.JSONObject
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication

internal class ReadiumLocatorMapper {
    fun toDomain(locator: Locator, fingerprint: ContentFingerprint): ReflowReaderLocation =
        ReflowReaderLocation(
            resourceKey = locator.href.toString(),
            progression = locator.locations.progression ?: 0.0,
            totalProgression = locator.locations.totalProgression,
            position = locator.locations.position,
            textQuote = locator.text.highlight
                ?.takeIf(String::isNotBlank)
                ?.let { highlight ->
                    TextQuote(
                        exact = highlight,
                        prefix = locator.text.before?.takeIf(String::isNotBlank),
                        suffix = locator.text.after?.takeIf(String::isNotBlank),
                    )
                },
            engineLocator = EngineLocator(
                engine = ReaderEngine.Readium,
                platform = ReaderEnginePlatform.Android,
                version = READIUM_VERSION,
                payload = EngineLocatorPayload.parse(locator.toJSON().toString()),
            ),
            contentFingerprint = fingerprint,
        )

    fun exactEngineLocator(location: ReaderLocation, fingerprint: ContentFingerprint): Locator? {
        val reflow = location as? ReflowReaderLocation ?: return null
        if (reflow.contentFingerprint != fingerprint) return null
        val engineLocator = reflow.engineLocator ?: return null
        if (engineLocator.engine != ReaderEngine.Readium) return null
        val payload = engineLocator.payload.canonicalJson
        return Locator.fromJSON(JSONObject(payload))
    }

    fun publicEngineLocator(locator: EngineLocator): Locator? {
        if (locator.engine != ReaderEngine.Readium) return null
        return runCatching { Locator.fromJSON(JSONObject(locator.payload.canonicalJson)) }.getOrNull()
    }

    fun resourceProgressionLocator(location: ReaderLocation, publication: Publication): Locator? {
        val reflow = location as? ReflowReaderLocation ?: return null
        val link = publication.readingOrder.firstOrNull { publication.url(it).toString() == reflow.resourceKey }
            ?: publication.readingOrder.firstOrNull { it.href.toString() == reflow.resourceKey }
            ?: return null
        val base = publication.locatorFromLink(link) ?: return null
        return base.copyWithLocations(
            progression = reflow.progression,
            position = reflow.position,
            totalProgression = reflow.totalProgression,
        )
    }

    fun resourceProgressionLocator(
        resourceKey: String,
        progression: Double?,
        position: Int?,
        publication: Publication,
    ): Locator? {
        val link = publication.readingOrder.firstOrNull { publication.url(it).toString() == resourceKey }
            ?: publication.readingOrder.firstOrNull { it.href.toString() == resourceKey }
            ?: return null
        val base = publication.locatorFromLink(link) ?: return null
        return base.copyWithLocations(progression = progression, position = position)
    }

    private companion object {
        const val READIUM_VERSION = "3.3.0"
    }
}
