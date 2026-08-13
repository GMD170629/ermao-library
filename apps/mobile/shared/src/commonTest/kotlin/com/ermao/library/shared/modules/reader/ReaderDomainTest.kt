package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull

class ReaderDomainTest {
    @Test
    fun exactComparatorRequiresFingerprintHrefAndBlockAnchor() {
        val expected = envelope("#chapter-title", "same")

        assertEquals(ExactBlockMatch.Exact, compare(expected, envelope("#chapter-title", "same")))
        assertEquals(ExactBlockMatch.AnchorMismatch, compare(expected, envelope("#other", "other")))
        assertEquals(
            ExactBlockMatch.FingerprintMismatch,
            compare(expected, envelope("#chapter-title", "same", hash = "b".repeat(64))),
        )
    }

    @Test
    fun exactComparatorCanUseBoundedNormalizedText() {
        val expected = envelope(null, "Café 正文", before = "前  文")
        val recaptured = envelope(null, "Café 正文", before = "前 文")

        assertEquals(ExactBlockMatch.Exact, compare(expected, recaptured))
        assertEquals(
            ExactBlockMatch.AnchorMismatch,
            compare(expected, envelope(null, "Café 正文")),
        )
    }

    @Test
    fun localAndRemoteRestoreNeverProduceApproximateCandidates() {
        val source = source()
        val local = progress()
        val remote = ReaderProgressSnapshotV4("volume-1", 9, envelope("#remote", "remote"), 80.0, 2_000, 2_000)

        assertIs<ReaderRestorePublicEngineLocator>(planReaderProgressRestore(local, remote, source).candidates.single())
        assertIs<ReaderRestorePublicEngineLocator>(planReaderProgressRestore(null, remote, source).candidates.single())
    }

    @Test
    fun newestExactResumeWinsAndOlderDifferentAnchorIsOffered() {
        val local = progress(updatedAt = 3_000)
        val remote = ReaderProgressSnapshotV4(
            "volume-1", 9, envelope("#remote", "remote"), 80.0, 4_000, 2_000,
        )

        val localWins = decideReaderResume(local, remote, source())

        assertEquals(ReaderResumeSource.Local, localWins.selected?.source)
        assertEquals(ReaderResumeSource.Server, localWins.alternative?.source)
    }

    @Test
    fun serverWinsEqualTimestampAndLegacySnapshotFallsBackToReceivedTime() {
        val local = progress(updatedAt = 2_000)
        val remote = ReaderProgressSnapshotV4(
            "volume-1", 9, envelope("#remote", "remote"), 80.0, 2_000,
        )

        val decision = decideReaderResume(local, remote, source())

        assertEquals(ReaderResumeSource.Server, decision.selected?.source)
        assertEquals(2_000, decision.selected?.capturedAtEpochMillis)
    }

    @Test
    fun semanticallyIdenticalAnchorRestoresWithoutAlternative() {
        val local = progress(updatedAt = 1_000)
        val remote = ReaderProgressSnapshotV4(
            "volume-1", 9, envelope("#chapter-title", "same"), 80.0, 2_000, 2_000,
        )

        val decision = decideReaderResume(local, remote, source())

        assertEquals(ReaderResumeSource.Server, decision.selected?.source)
        assertNull(decision.alternative)
    }

    @Test
    fun fingerprintMismatchRefusesAutomaticRestoreInsteadOfUsingPercent() {
        val mismatch = ReaderProgressSnapshotV4(
            "volume-1",
            9,
            envelope("#remote", "remote", hash = "b".repeat(64)),
            80.0,
            2_000,
        )

        assertEquals(emptyList(), planReaderProgressRestore(null, mismatch, source()).candidates)
    }

    @Test
    fun localCodecRejectsPreReleaseLegacyAndProgressionOnlyDocuments() {
        assertFailsWith<IllegalArgumentException> {
            ReaderProgressJson().decode("""{"schema":"ermao.reader-progress","version":1}""")
        }
        assertFailsWith<IllegalArgumentException> {
            ReaderProgress(
                "volume-1",
                ReflowReaderLocation("part00000.html", 0.5, contentFingerprint = fingerprint()),
                1,
                "client",
            )
        }
    }

    private fun progress(updatedAt: Long = 1) = ReaderProgress(
        "volume-1",
        ReflowReaderLocation(
            resourceKey = "part00000.html",
            engineLocator = envelope("#chapter-title", "same").asEngineLocator(),
            contentFingerprint = fingerprint(),
        ),
        updatedAt,
        "client",
    )

    private fun source() = LocalReaderSource("volume-1", "Book", ReaderFormat.Epub, fingerprint())

    private fun fingerprint() = ContentFingerprint("sha256:" + "a".repeat(64), PARSER, NORMALIZATION)

    private fun compare(expected: ReadiumLocatorEnvelope, actual: ReadiumLocatorEnvelope) =
        com.ermao.library.shared.modules.reader.domain.compareExactReadiumBlocks(expected, actual)

    private fun envelope(
        selector: String?,
        highlight: String,
        before: String? = null,
        hash: String = "a".repeat(64),
    ): ReadiumLocatorEnvelope {
        val selectorJson = selector?.let { "\"cssSelector\":\"$it\"," } ?: ""
        val beforeJson = before?.let { "\"before\":\"$it\"," } ?: ""
        return ReadiumLocatorEnvelope.parse(
            """{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","publication":{"originalFileHash":"$hash","parser":"$PARSER","normalization":"$NORMALIZATION"},"payload":{"href":"part00000.html","type":"application/xhtml+xml","locations":{$selectorJson"progression":0.42},"text":{$beforeJson"highlight":"$highlight"}}}""",
        )
    }

    private companion object {
        const val PARSER = "readium:epub"
        const val NORMALIZATION = "epub-v1"
    }
}
