package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ContentFingerprint
import com.ermao.library.shared.modules.reader.EngineLocator
import com.ermao.library.shared.modules.reader.EngineLocatorPayload
import com.ermao.library.shared.modules.reader.ReaderEngine
import com.ermao.library.shared.modules.reader.ReaderEnginePlatform
import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReadiumLocatorEnvelope
import com.ermao.library.shared.modules.reader.ExactBlockMatch
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
                        exact = highlight.takeUnicodeCodePoints(ReadiumLocatorEnvelope.MAXIMUM_HIGHLIGHT_LENGTH),
                        prefix = locator.text.before?.takeIf(String::isNotBlank)
                            ?.takeUnicodeCodePoints(ReadiumLocatorEnvelope.MAXIMUM_CONTEXT_LENGTH),
                        suffix = locator.text.after?.takeIf(String::isNotBlank)
                            ?.takeUnicodeCodePoints(ReadiumLocatorEnvelope.MAXIMUM_CONTEXT_LENGTH),
                    )
                },
            engineLocator = EngineLocator(
                engine = ReaderEngine.Readium,
                platform = ReaderEnginePlatform.Android,
                version = READIUM_VERSION,
                payload = EngineLocatorPayload.parse(boundedPayload(locator).toString()),
            ),
            contentFingerprint = fingerprint,
        )

    fun exactEnvelope(locator: Locator, fingerprint: ContentFingerprint): ReadiumLocatorEnvelope? =
        ReadiumLocatorEnvelope.from(toDomain(locator, fingerprint))

    fun compareExactBlock(
        expected: ReadiumLocatorEnvelope,
        recaptured: Locator,
        fingerprint: ContentFingerprint,
    ): ExactBlockMatch {
        val actual = exactEnvelope(recaptured, fingerprint) ?: return ExactBlockMatch.AnchorMismatch
        return com.ermao.library.shared.modules.reader.domain.compareExactProgressReadiumBlocks(expected, actual)
    }

    fun exactEngineLocator(location: ReaderLocation): Locator? {
        val reflow = location as? ReflowReaderLocation ?: return null
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
        const val READIUM_VERSION = "readium-kotlin:3.3.0"
    }

    private fun boundedPayload(locator: Locator): JSONObject = locator.toJSON().also { root ->
        root.optJSONObject("text")?.let { text ->
            truncate(text, "highlight", ReadiumLocatorEnvelope.MAXIMUM_HIGHLIGHT_LENGTH)
            truncate(text, "before", ReadiumLocatorEnvelope.MAXIMUM_CONTEXT_LENGTH)
            truncate(text, "after", ReadiumLocatorEnvelope.MAXIMUM_CONTEXT_LENGTH)
        }
    }

    private fun truncate(value: JSONObject, key: String, maximum: Int) {
        val text = value.optString(key).takeIf(String::isNotBlank) ?: return
        if (text.codePointCount(0, text.length) > maximum) {
            value.put(key, text.takeUnicodeCodePoints(maximum))
        }
    }
}

private fun String.takeUnicodeCodePoints(maximum: Int): String =
    substring(0, offsetByCodePoints(0, minOf(maximum, codePointCount(0, length))))
