package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderLocation
import com.ermao.library.shared.modules.reader.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.ReaderOpaqueLocator
import org.readium.r2.shared.publication.Locator
import org.readium.r2.shared.publication.Publication

internal class ReadiumLocatorMapper {
    /** Serializes the SDK Locator as-is; no text projection or location repair. */
    fun opaqueLocator(locator: Locator): ReaderOpaqueLocator =
        ReaderOpaqueLocator.parse(locator.toJSON().toString())

    fun toDomain(locator: Locator): ReflowReaderLocation =
        ReflowReaderLocation(
            resourceKey = locator.href.toString(),
            progression = locator.locations.progression ?: 0.0,
            totalProgression = locator.locations.totalProgression,
            position = locator.locations.position,
            // Text/highlight and SDK-specific payloads remain owned by the
            // native engine.  A UI location is only a display/navigation
            // projection and is never used as the v5 persisted report.
        )

    /**
     * Resolves a domain navigation location to the SDK's public link locator.
     *
     * Progression/position values are deliberately not copied into this
     * locator. Those values belong to the SDK event that produced a report;
     * synthesizing them here would make a navigation request look like a
     * captured position.
     */
    fun resourceLocator(location: ReaderLocation, publication: Publication): Locator? {
        val reflow = location as? ReflowReaderLocation ?: return null
        val link = publication.readingOrder.firstOrNull { publication.url(it).toString() == reflow.resourceKey }
            ?: publication.readingOrder.firstOrNull { it.href.toString() == reflow.resourceKey }
            ?: return null
        return publication.locatorFromLink(link)
    }

}
