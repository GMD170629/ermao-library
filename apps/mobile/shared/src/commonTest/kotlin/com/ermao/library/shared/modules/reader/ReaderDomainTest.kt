package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.domain.toServerSnapshot
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json

class ReaderDomainTest {
    @Test
    fun progressJsonV4RoundTripsVersionedEngineLocator() {
        val codec = ReaderProgressJson()
        val progress = codec.decode(READER_PROGRESS_JSON_V4_GOLDEN)

        val encoded = codec.encode(progress)

        assertEquals(progress, codec.decode(encoded))
        assertEquals(Json.parseToJsonElement(READER_PROGRESS_JSON_V4_GOLDEN), Json.parseToJsonElement(encoded))
    }

    @Test
    fun legacyV1ProgressMigratesToVersionedIosReadiumLocator() {
        val decoded = ReaderProgressJson().decode(READER_PROGRESS_JSON_V1_GOLDEN)
        val locator = (decoded.location as ReflowReaderLocation).engineLocator

        assertEquals(ReaderEngine.Readium, locator?.engine)
        assertEquals(ReaderEnginePlatform.Ios, locator?.platform)
        assertEquals("3.8.0", locator?.version)
        assertTrue(checkNotNull(locator).payload.canonicalJson.contains("epubcfi"))
    }

    @Test
    fun engineLocatorRejectsPayloadAbove64KiB() {
        assertFailsWith<IllegalArgumentException> {
            EngineLocatorPayload.parse("""{"value":"${"x".repeat(65_537)}"}""")
        }
    }

    @Test
    fun engineLocatorAllowsA64KiBPayloadIndependentOfMetadataSize() {
        val payload = EngineLocatorPayload.parse("""{"v":"${"x".repeat(65_528)}"}""")

        val locator = EngineLocator(
            ReaderEngine.Readium,
            ReaderEnginePlatform.Android,
            "v".repeat(191),
            payload,
        )

        assertEquals(65_536, locator.payload.canonicalJson.encodeToByteArray().size)
    }

    @Test
    fun textQuoteEnforcesServerWireBounds() {
        TextQuote("x".repeat(8_192), "p".repeat(4_096), "s".repeat(4_096))

        assertFailsWith<IllegalArgumentException> { TextQuote("x".repeat(8_193)) }
        assertFailsWith<IllegalArgumentException> { TextQuote("x", prefix = "p".repeat(4_097)) }
        assertFailsWith<IllegalArgumentException> { TextQuote("x", suffix = "s".repeat(4_097)) }
    }

    @Test
    fun locatorOnlyReflowLocationIsValidAndProjectsExplicitPercent() {
        val locator = EngineLocator(
            ReaderEngine.Readium,
            ReaderEnginePlatform.Android,
            "3.3.0",
            EngineLocatorPayload.parse("""{"href":"chapter.xhtml"}"""),
        )
        val progress = ReaderProgress(
            "volume-1",
            ReflowReaderLocation(engineLocator = locator, contentFingerprint = fingerprint()),
            1,
            "android-client",
            percent = 37.0,
        )

        assertEquals(37.0, progress.toServerSnapshot(ReaderServerContentFingerprint("token")).percent)
    }

    @Test
    fun progressionOnlyReflowLocationIsAValidPublicAnchor() {
        val progress = ReaderProgress(
            "volume-1",
            ReflowReaderLocation(progression = 0.25, contentFingerprint = fingerprint()),
            1,
            "android-client",
        )

        val snapshot = progress.toServerSnapshot(ReaderServerContentFingerprint("token"))

        assertEquals(0.25, snapshot.anchor?.progression)
        assertEquals(null, snapshot.anchor?.resourceKey)
    }

    @Test
    fun nonReflowRemoteRestoreTriesCompatibleEngineBeforeStandardAnchor() {
        val engine = EngineLocator(
            ReaderEngine.Readium,
            ReaderEnginePlatform.Android,
            "3.3.0",
            EngineLocatorPayload.parse("""{"page":7}"""),
        )
        val remote = ReaderProgress(
            "volume-1",
            PdfReaderLocation(6, contentFingerprint = fingerprint(), engineLocator = engine),
            10,
            "android-client",
            percent = 25.0,
        ).toServerSnapshot(ReaderServerContentFingerprint("token"))
        val source = LocalReaderSource("volume-1", "PDF", ReaderFormat.Pdf, fingerprint())

        val plan = planReaderProgressRestore(null, remote, source)

        assertIs<ReaderRestorePublicEngineLocator>(plan.candidates[0])
        assertIs<ReaderRestorePdfPage>(plan.candidates[1])
        assertIs<ReaderRestoreTotalProgression>(plan.candidates[2])
    }

    @Test
    fun nonReflowEngineLocatorRoundTripsThroughLocalV4Json() {
        val engine = EngineLocator(
            ReaderEngine.Readium,
            ReaderEnginePlatform.Android,
            "3.3.0",
            EngineLocatorPayload.parse("""{"page":7}"""),
        )
        val progress = ReaderProgress(
            "volume-1",
            PdfReaderLocation(6, contentFingerprint = fingerprint(), engineLocator = engine),
            10,
            "android-client",
            percent = 25.0,
        )

        assertEquals(progress, ReaderProgressJson().decode(ReaderProgressJson().encode(progress)))
    }

    @Test
    fun localTieKeepsExactButNewerRemoteUsesPublicFallbackOrder() {
        val source = source()
        val local = progress(updatedAt = 2_000)
        val tie = ReaderProgressSnapshotV4(
            "volume-1",
            70.0,
            2_000,
            "ios",
            ReaderServerContentFingerprint("server-token"),
            anchor(),
        )
        val newer = tie.copy(updatedAtEpochMillis = 2_001)

        val localPlan = planReaderProgressRestore(local, tie, source)
        val remotePlan = planReaderProgressRestore(local, newer, source)

        assertTrue(localPlan.usesLocalExact)
        assertEquals(local, localPlan.localProgress)
        assertNull(remotePlan.localProgress)
        assertFalse(remotePlan.usesLocalExact)
        assertIs<ReaderRestorePublicEngineLocator>(remotePlan.candidates[0])
        assertIs<ReaderRestoreResourceProgression>(remotePlan.candidates[1])
        assertIs<ReaderRestoreQuotedText>(remotePlan.candidates[2])
        assertIs<ReaderRestorePosition>(remotePlan.candidates[3])
        assertIs<ReaderRestoreTotalProgression>(remotePlan.candidates[4])
    }

    @Test
    fun localFingerprintMismatchFallsBackOnlyToPercent() {
        val local = progress().copy(
            location = (progress().location as ReflowReaderLocation).copy(
                contentFingerprint = fingerprint('b'),
            ),
        )

        val plan = planReaderProgressRestore(local, null, source())

        assertFalse(plan.usesLocalExact)
        assertIs<ReaderRestoreTotalProgression>(plan.candidates.single())
    }

    @Test
    fun remoteStructuredFingerprintMismatchFallsBackOnlyToPercent() {
        val remote = ReaderProgressSnapshotV4(
            "volume-1",
            63.0,
            9_000,
            "ios",
            ReaderServerContentFingerprint("server-token"),
            anchor().copy(contentFingerprint = fingerprint('b')),
        )

        val plan = planReaderProgressRestore(null, remote, source())

        assertIs<ReaderRestoreTotalProgression>(plan.candidates.single())
    }

    @Test
    fun resourceOnlyRemoteAnchorPrecedesPercentFallback() {
        val remote = ReaderProgressSnapshotV4(
            "volume-1",
            10.0,
            9_000,
            "ios",
            ReaderServerContentFingerprint("server-token"),
            ReaderPublicAnchor(resourceKey = "EPUB/chapter.xhtml"),
        )

        val plan = planReaderProgressRestore(null, remote, source())

        val resource = assertIs<ReaderRestoreResourceProgression>(plan.candidates.first())
        assertEquals(null, resource.progression)
        assertIs<ReaderRestoreTotalProgression>(plan.candidates.last())
    }

    private fun progress(updatedAt: Long = 1_765_555_555_000) = ReaderProgress(
        sourceId = "volume-1",
        location = ReflowReaderLocation(
            resourceKey = "EPUB/chapter.xhtml",
            progression = 0.25,
            totalProgression = 0.5,
            position = 12,
            textQuote = TextQuote("anchor", "before", "after"),
            engineLocator = EngineLocator(
                ReaderEngine.Readium,
                ReaderEnginePlatform.Android,
                "3.3.0",
                EngineLocatorPayload.parse("""{"href":"EPUB/chapter.xhtml"}"""),
            ),
            contentFingerprint = fingerprint(),
        ),
        updatedAtEpochMillis = updatedAt,
        deviceId = "android-client",
    )

    private fun anchor() = ReaderPublicAnchor(
        engineLocator = EngineLocator(
            ReaderEngine.Readium,
            ReaderEnginePlatform.Ios,
            "3.8.0",
            EngineLocatorPayload.parse("""{"href":"EPUB/chapter.xhtml"}"""),
        ),
        resourceKey = "EPUB/chapter.xhtml",
        progression = 0.7,
        textQuote = TextQuote("anchor"),
        position = 42,
    )

    private fun source() = LocalReaderSource(
        "volume-1",
        "Book",
        ReaderFormat.Epub,
        fingerprint(),
    )

    private fun fingerprint(character: Char = 'a') = ContentFingerprint(
        "sha256:" + character.toString().repeat(64),
        "readium-kotlin:3.3.0",
        "epub-native-sanitized-v1",
    )
}

const val READER_PROGRESS_JSON_V1_GOLDEN = """
{
  "schema":"ermao.reader-progress",
  "version":1,
  "sourceId":"volume-1",
  "location":{
    "kind":"reflow",
    "resourceKey":"EPUB/chapter.xhtml",
    "progression":0.375,
    "totalProgression":0.625,
    "position":42,
    "engineLocator":{"href":"EPUB/chapter.xhtml","locations":{"cfi":"epubcfi(/6/14)"}},
    "contentFingerprint":{
      "originalFileHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "parserVersion":"readium-swift:3.8.0",
      "normalizationVersion":"epub-native-sanitized-v1"
    }
  },
  "updatedAtEpochMillis":1765555555000,
  "deviceId":"ios-client"
}
"""

/** Cross-platform exact local progress fixture for Android and iOS v4 stores. */
const val READER_PROGRESS_JSON_V4_GOLDEN = """
{
  "schema":"ermao.reader-progress",
  "version":4,
  "sourceId":"volume-1",
  "location":{
    "kind":"reflow",
    "resourceKey":"EPUB/chapter.xhtml",
    "progression":0.25,
    "totalProgression":0.5,
    "position":12,
    "textQuote":{"exact":"anchor","prefix":"before","suffix":"after"},
    "engineLocator":{"engine":"readium","platform":"android","version":"3.3.0","payload":{"href":"EPUB/chapter.xhtml"}},
    "contentFingerprint":{
      "originalFileHash":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "parserVersion":"readium-kotlin:3.3.0",
      "normalizationVersion":"epub-native-sanitized-v1"
    }
  },
  "updatedAtEpochMillis":1765555555000,
  "deviceId":"android-client"
}
"""
