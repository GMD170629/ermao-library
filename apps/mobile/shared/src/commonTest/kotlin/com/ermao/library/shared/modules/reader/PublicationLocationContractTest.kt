package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressJson
import com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressSyncStateJson
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class PublicationLocationContractTest {
    @Test
    fun exactPublicationLocationsRoundTripCanonically() {
        val values = listOf(
            ReflowablePublicationLocation(engineLocator()),
            PdfPublicationLocation(7, 0.375, engineLocator()),
            ComicPublicationLocation("images/page-008.jpg", 7, engineLocator()),
            AudioPublicationLocation("track-1", "chapter-2", 45_000, engineLocator()),
        )

        values.forEach { expected ->
            val decoded = PublicationLocation.parse(expected.canonicalJson())
            assertEquals(expected, decoded)
            assertEquals(expected.canonicalJson(), decoded.canonicalJson())
        }
    }

    @Test
    fun localProgressRoundTripsAllMorphologiesAtVersionSeven() {
        val locations = listOf(
            ReflowReaderLocation(
                resourceKey = "chapter.xhtml",
                engineLocator = engineLocator(),
            ),
            PdfReaderLocation(3, 0.25, engineLocator()),
            ComicReaderLocation("images/004.jpg", 3, engineLocator()),
            AudioReaderLocation("track-1", null, 1200, engineLocator()),
        )
        val codec = ReaderProgressJson()
        locations.forEach { location ->
            val progress = ReaderProgress("volume-1", location, 100, "device-1", 25.0)
            assertEquals(progress, codec.decode(codec.encode(progress)))
        }
    }

    @Test
    fun oldLocalDocumentsAndSyncStatesAreStrictlyRejected() {
        val progress = ReaderProgress(
            "volume-1",
            PdfReaderLocation(0, 0.0),
            100,
            "device-1",
            0.0,
        )
        val oldProgress = ReaderProgressJson().encode(progress).replace("\"version\":7", "\"version\":4")
        assertFailsWith<IllegalArgumentException> { ReaderProgressJson().decode(oldProgress) }
        assertFailsWith<IllegalArgumentException> {
            ReaderProgressSyncStateJson().decode(
                """{"schema":"ermao.reader-progress-sync","version":4,"confirmedRevision":0}""",
            )
        }
    }

    @Test
    fun invalidMorphologyAnchorsAreRejected() {
        assertFailsWith<IllegalArgumentException> { PdfPublicationLocation(0, Double.NaN) }
        assertFailsWith<IllegalArgumentException> { ComicPublicationLocation("../escape.jpg", 0) }
        assertFailsWith<IllegalArgumentException> {
            PublicationLocation.parse(
                """{"kind":"reflowable"}""",
            )
        }
        assertFailsWith<IllegalArgumentException> {
            PublicationLocation.parse(
                """{"kind":"pdf","pageIndex":0,"pageProgression":0.12345}""",
            )
        }
        assertFailsWith<IllegalArgumentException> {
            PublicationLocation.parse(
                """{"kind":"comic","unexpected":true,"pageIndex":0,"resourceHref":"page.jpg"}""",
            )
        }
    }

    @Test
    fun exactComparisonUsesMorphologySpecificAnchors() {
        val pdf = PdfPublicationLocation(4, 0.12344)
        assertEquals(0.1234, pdf.pageProgression)
        assertEquals(0.1234, PublicationLocation.parse(pdf.canonicalJson()).let {
            (it as PdfPublicationLocation).pageProgression
        })
        kotlin.test.assertTrue(pdf.canonicalJson().contains("\"pageProgression\":0.1234"))
        assertEquals(
            ExactLocationMatch.Exact,
            com.ermao.library.shared.modules.reader.domain.compareExactPublicationLocations(
                pdf,
                PdfPublicationLocation(4, 0.12343),
            ),
        )
        assertEquals(
            ExactLocationMatch.MorphologyMismatch,
            com.ermao.library.shared.modules.reader.domain.compareExactPublicationLocations(
                pdf,
                ComicPublicationLocation("page-5.jpg", 4),
            ),
        )
    }

    private fun engineLocator() = createEngineLocator(
        ReaderEngine.Readium,
        ReaderEnginePlatform.Android,
        "readium-kotlin:3.3.0",
        """{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#p1"}}""",
    )

}
