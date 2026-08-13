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
            ReflowablePublicationLocation(fingerprint(), engineLocator()),
            PdfPublicationLocation(fingerprint(), 7, 0.375, engineLocator()),
            ComicPublicationLocation(fingerprint(), "images/page-008.jpg", 7, engineLocator()),
            AudioPublicationLocation(fingerprint(), "track-1", "chapter-2", 45_000, engineLocator()),
        )

        values.forEach { expected ->
            val decoded = PublicationLocation.parse(expected.canonicalJson())
            assertEquals(expected, decoded)
            assertEquals(expected.canonicalJson(), decoded.canonicalJson())
        }
    }

    @Test
    fun localProgressRoundTripsAllMorphologiesAtVersionFive() {
        val locations = listOf(
            ReflowReaderLocation(
                resourceKey = "chapter.xhtml",
                engineLocator = engineLocator(),
                contentFingerprint = contentFingerprint(),
            ),
            PdfReaderLocation(3, 0.25, contentFingerprint(), engineLocator()),
            ComicReaderLocation("images/004.jpg", 3, contentFingerprint(), engineLocator()),
            AudioReaderLocation("track-1", null, 1200, contentFingerprint(), engineLocator()),
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
            PdfReaderLocation(0, 0.0, contentFingerprint()),
            100,
            "device-1",
            0.0,
        )
        val oldProgress = ReaderProgressJson().encode(progress).replace("\"version\":5", "\"version\":4")
        assertFailsWith<IllegalArgumentException> { ReaderProgressJson().decode(oldProgress) }
        assertFailsWith<IllegalArgumentException> {
            ReaderProgressSyncStateJson().decode(
                """{"schema":"ermao.reader-progress-sync","version":4,"confirmedRevision":0}""",
            )
        }
    }

    @Test
    fun invalidMorphologyAnchorsAreRejected() {
        assertFailsWith<IllegalArgumentException> { PdfPublicationLocation(fingerprint(), 0, Double.NaN) }
        assertFailsWith<IllegalArgumentException> { ComicPublicationLocation(fingerprint(), "../escape.jpg", 0) }
        assertFailsWith<IllegalArgumentException> {
            PublicationLocation.parse(
                """{"kind":"reflowable","publication":${fingerprintJson()}}""",
            )
        }
        assertFailsWith<IllegalArgumentException> {
            PublicationLocation.parse(
                """{"kind":"pdf","publication":${fingerprintJson()},"pageIndex":0,"pageProgression":0.12345}""",
            )
        }
        assertFailsWith<IllegalArgumentException> {
            PublicationLocation.parse(
                """{"kind":"comic","publication":${fingerprintJson().dropLast(1)},"unexpected":true},"pageIndex":0,"resourceHref":"page.jpg"}""",
            )
        }
    }

    @Test
    fun exactComparisonUsesMorphologySpecificAnchors() {
        val pdf = PdfPublicationLocation(fingerprint(), 4, 0.12344)
        assertEquals(0.1234, pdf.pageProgression)
        assertEquals(0.1234, PublicationLocation.parse(pdf.canonicalJson()).let {
            (it as PdfPublicationLocation).pageProgression
        })
        kotlin.test.assertTrue(pdf.canonicalJson().contains("\"pageProgression\":0.1234"))
        assertEquals(
            ExactLocationMatch.Exact,
            com.ermao.library.shared.modules.reader.domain.compareExactPublicationLocations(
                pdf,
                PdfPublicationLocation(fingerprint(), 4, 0.12343),
            ),
        )
        assertEquals(
            ExactLocationMatch.MorphologyMismatch,
            com.ermao.library.shared.modules.reader.domain.compareExactPublicationLocations(
                pdf,
                ComicPublicationLocation(fingerprint(), "page-5.jpg", 4),
            ),
        )
    }

    private fun engineLocator() = createEngineLocator(
        ReaderEngine.Readium,
        ReaderEnginePlatform.Android,
        "readium-kotlin:3.3.0",
        """{"href":"chapter.xhtml","type":"application/xhtml+xml","locations":{"cssSelector":"#p1"}}""",
    )

    private fun contentFingerprint() = ContentFingerprint(HASH, "parser-v1", "normalization-v1")
    private fun fingerprint() = PublicationFingerprint(HASH, "parser-v1", "normalization-v1")
    private fun fingerprintJson() = fingerprint().let {
        """{"originalFileHash":"${it.originalFileHash}","parser":"${it.parser}","normalization":"${it.normalization}"}"""
    }

    private companion object {
        const val HASH = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
}
