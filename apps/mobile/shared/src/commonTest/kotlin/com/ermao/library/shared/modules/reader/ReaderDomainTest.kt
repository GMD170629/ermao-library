package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.PendingVsServerDecision as StartupDecision
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ReaderDomainTest {
    @Test
    fun exactComparatorRequiresHrefAndBlockAnchor() {
        val expected = envelope("#chapter-title", "same")

        assertEquals(ExactBlockMatch.Exact, compare(expected, envelope("#chapter-title", "same")))
        assertEquals(ExactBlockMatch.AnchorMismatch, compare(expected, envelope("#other", "other")))
        assertEquals(
            ExactBlockMatch.ResourceMismatch,
            compare(expected, envelope("#chapter-title", "same", href = "other.xhtml")),
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
        val remote = ReaderProgressSnapshotV4("volume-1", "ios-client", 9, envelope("#remote", "remote"), 80.0, 2_000, 2_000)

        assertIs<ReaderRestorePublicEngineLocator>(planReaderProgressRestore(local, remote, source).candidates.single())
        assertIs<ReaderRestorePublicEngineLocator>(planReaderProgressRestore(null, remote, source).candidates.single())
    }

    @Test
    fun startupUsesTheNewestValidPositionAndKeepsTheOtherAsANonBlockingAlternative() {
        val local = progress(updatedAt = 3_000)
        val remote = ReaderProgressSnapshotV4(
            "volume-1", "ios-client", 9, envelope("#remote", "remote"), 80.0, 4_000, 2_000,
        )

        val decision = decideReaderResume(local, remote, source())

        assertEquals(ReaderResumeSource.Local, decision.selected?.source)
        assertEquals(ReaderResumeSource.Server, decision.alternative?.source)
    }

    @Test
    fun serverWinsEqualTimestampAndLegacySnapshotFallsBackToReceivedTime() {
        val local = progress(updatedAt = 2_000)
        val remote = ReaderProgressSnapshotV4(
            "volume-1", "ios-client", 9, envelope("#remote", "remote"), 80.0, 2_000,
        )

        val decision = decideReaderResume(local, remote, source())

        assertEquals(ReaderResumeSource.Server, decision.selected?.source)
        assertEquals(2_000, decision.selected?.capturedAtEpochMillis)
    }

    @Test
    fun semanticallyIdenticalAnchorRestoresWithoutAlternative() {
        val local = progress(updatedAt = 1_000)
        val remote = ReaderProgressSnapshotV4(
            "volume-1", "ios-client", 9, envelope("#chapter-title", "same"), 80.0, 2_000, 2_000,
        )

        val decision = decideReaderResume(local, remote, source())

        assertEquals(ReaderResumeSource.Server, decision.selected?.source)
        assertNull(decision.alternative)
    }

    @Test
    fun pendingAgainstNewerServerResolvesWithoutAStartupChoice() {
        val local = progress(updatedAt = 3_000)
        val pending = createReaderProgressUpload(
            ReaderProgressSyncTarget(ReaderSyncNamespace("server", "user", 1), "work-1", "volume-1", ReaderFormat.Epub),
            local,
            4,
            "mutation-1",
        ).mutation
        val remote = ReaderProgressSnapshotV4(
            "volume-1", "ios-client", 5, envelope("#remote", "remote"), 80.0, 4_000, 4_000,
        )

        val decision = decidePendingVsServerStartup(
            local,
            ReaderProgressDurableState(confirmedRevision = 4, pending = pending),
            remote,
            source(),
        )

        val useServer = assertIs<StartupDecision.UseServer>(decision)
        assertTrue(useServer.discardPending)
    }

    @Test
    fun normalizationChangeKeepsExactRestoreForTheSameOriginalFile() {
        val upgraded = ReaderProgressSnapshotV4(
            "volume-1",
            "ios-client",
            9,
            envelope("#remote", "remote"),
            80.0,
            2_000,
        )

        assertEquals(1, planReaderProgressRestore(null, upgraded, source()).candidates.size)
    }

    @Test
    fun originalFileChangeStillOffersTheSemanticRestoreForTheSameVolume() {
        val mismatch = ReaderProgressSnapshotV4(
            "volume-1",
            "ios-client",
            9,
            envelope("#remote", "remote"),
            80.0,
            2_000,
        )

        assertEquals(1, planReaderProgressRestore(null, mismatch, source()).candidates.size)
    }

    @Test
    fun localCodecRejectsPreReleaseLegacyAndProgressionOnlyDocuments() {
        assertFailsWith<IllegalArgumentException> {
            ReaderProgressJson().decode("""{"schema":"ermao.reader-progress","version":1}""")
        }
        assertFailsWith<IllegalArgumentException> {
            ReaderProgress(
                "volume-1",
                ReflowReaderLocation("part00000.html", 0.5),
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
        ),
        updatedAt,
        "client",
    )

    private fun source() = LocalReaderSource("volume-1", "Book", ReaderFormat.Epub)

    private fun compare(expected: ReadiumLocatorEnvelope, actual: ReadiumLocatorEnvelope) =
        com.ermao.library.shared.modules.reader.domain.compareExactReadiumBlocks(expected, actual)

    private fun envelope(
        selector: String?,
        highlight: String,
        before: String? = null,
        href: String = "part00000.html",
    ): ReadiumLocatorEnvelope {
        val selectorJson = selector?.let { "\"cssSelector\":\"$it\"," } ?: ""
        val beforeJson = before?.let { "\"before\":\"$it\"," } ?: ""
        return ReadiumLocatorEnvelope.parse(
            """{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","payload":{"href":"$href","type":"application/xhtml+xml","locations":{$selectorJson"progression":0.42},"text":{$beforeJson"highlight":"$highlight"}}}""",
        )
    }
}
