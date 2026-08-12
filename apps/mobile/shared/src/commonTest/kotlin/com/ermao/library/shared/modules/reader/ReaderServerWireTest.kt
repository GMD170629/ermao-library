package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
import com.ermao.library.shared.modules.reader.infrastructure.ReaderProgressResponseWire
import com.ermao.library.shared.modules.reader.infrastructure.ReaderServerWireMapper
import com.ermao.library.shared.modules.reader.domain.toServerSnapshot
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals

class ReaderServerWireTest {
    @Test
    fun v4PutContainsOnlyOverwriteIdentityTimestampPercentLocationAndServerToken() {
        val root = Json.parseToJsonElement(ReaderServerWireMapper().encodeProgressUpload(upload())).jsonObject
        val location = root.getValue("location").jsonObject

        assertEquals(
            setOf("schemaVersion", "clientId", "updatedAtEpochMillis", "percent", "location", "contentFingerprint"),
            root.keys,
        )
        assertEquals("android-client", root.getValue("clientId").jsonPrimitive.content)
        assertEquals("server-token", root.getValue("contentFingerprint").jsonPrimitive.content)
        assertEquals(
            setOf("kind", "resourceKey", "progression", "engineLocator", "contentFingerprint"),
            location.keys,
        )
        assertEquals("readium", location.getValue("engineLocator").jsonObject.getValue("engine").jsonPrimitive.content)
        assertEquals(
            "EPUB/chapter.xhtml",
            location.getValue("engineLocator").jsonObject.getValue("payload").jsonObject
                .getValue("href").jsonPrimitive.content,
        )
        assertEquals(ORIGINAL_HASH, location.getValue("contentFingerprint").jsonObject
            .getValue("originalFileHash").jsonPrimitive.content)
    }

    @Test
    fun responseMapsPublicSnapshotWithoutManufacturingLocalFingerprint() {
        val response = ReaderProgressResponseWire(
            Json.parseToJsonElement(
                """{"schemaVersion":4,"clientId":"ios-client","updatedAtEpochMillis":2222,"percent":80.0,"contentFingerprint":"server-token","location":{"kind":"reflow","resourceKey":"EPUB/remote.xhtml","progression":0.8,"engineLocator":{"engine":"readium","platform":"ios","version":"3.8.0","payload":{"href":"EPUB/remote.xhtml"}}}}""",
            ).jsonObject,
        )

        val snapshot = ReaderServerWireMapper().decodeSnapshot(response, "volume-1")

        assertEquals(2_222, snapshot.updatedAtEpochMillis)
        assertEquals("server-token", snapshot.serverContentFingerprint.value)
        assertEquals(ReaderEnginePlatform.Ios, snapshot.anchor?.engineLocator?.platform)
        assertEquals("EPUB/remote.xhtml", snapshot.anchor?.resourceKey)
    }

    @Test
    fun responseDoesNotAcceptV3TypeAndHrefFallbacks() {
        val response = ReaderProgressResponseWire(
            Json.parseToJsonElement(
                """{"schemaVersion":4,"clientId":"legacy-client","updatedAtEpochMillis":2222,"percent":80.0,"contentFingerprint":"server-token","location":{"type":"epub","href":"EPUB/legacy.xhtml","progression":0.8}}""",
            ).jsonObject,
        )

        val snapshot = ReaderServerWireMapper().decodeSnapshot(response, "volume-1")

        assertEquals(null, snapshot.anchor)
    }

    @Test
    fun progressionOnlyReflowWireIsAcceptedWithoutInventingAResource() {
        val base = upload()
        val progress = ReaderProgress(
            "volume-1",
            ReflowReaderLocation(
                progression = 0.3,
                contentFingerprint = ContentFingerprint(ORIGINAL_HASH, "readium-kotlin:3.3.0", "v1"),
            ),
            10,
            "android-client",
        )
        val root = Json.parseToJsonElement(
            ReaderServerWireMapper().encodeProgressUpload(
                base.copy(
                    snapshot = progress.toServerSnapshot(base.target.serverContentFingerprint),
                    localLocation = progress.location,
                ),
            ),
        ).jsonObject

        val location = root.getValue("location").jsonObject
        assertEquals(setOf("kind", "progression", "contentFingerprint"), location.keys)
        assertEquals("0.3", location.getValue("progression").jsonPrimitive.content)
    }

    @Test
    fun pdfComicAndAudioUseStandardOneBasedAndMillisecondLocations() {
        fun location(location: ReaderLocation, format: ReaderFormat, percent: Double): kotlinx.serialization.json.JsonObject {
            val base = upload()
            val progress = ReaderProgress("volume-1", location, 10, "android-client", percent)
            return Json.parseToJsonElement(
                ReaderServerWireMapper().encodeProgressUpload(
                    base.copy(
                        target = base.target.copy(sourceFormat = format),
                        snapshot = progress.toServerSnapshot(base.target.serverContentFingerprint),
                        localLocation = location,
                    ),
                ),
            ).jsonObject.getValue("location").jsonObject
        }
        val fingerprint = ContentFingerprint(ORIGINAL_HASH, "native:1", "v1")
        val engine = EngineLocator(
            ReaderEngine.Readium,
            ReaderEnginePlatform.Android,
            "3.3.0",
            EngineLocatorPayload.parse("""{"anchor":1}"""),
        )

        val pdf = location(PdfReaderLocation(6, contentFingerprint = fingerprint, engineLocator = engine), ReaderFormat.Pdf, 25.0)
        val comic = location(ComicReaderLocation(3, fingerprint, engine), ReaderFormat.Comic, 40.0)
        val audio = location(
            AudioReaderLocation("file-1", "chapter-2", 9_000, fingerprint, engine),
            ReaderFormat.Audio,
            50.0,
        )
        assertEquals(setOf("kind", "pageNumber", "engineLocator"), pdf.keys)
        assertEquals("pdf", pdf.getValue("kind").jsonPrimitive.content)
        assertEquals("7", pdf.getValue("pageNumber").jsonPrimitive.content)
        assertEquals(setOf("kind", "pageIndex", "engineLocator"), comic.keys)
        assertEquals("4", comic.getValue("pageIndex").jsonPrimitive.content)
        assertEquals(setOf("kind", "fileId", "chapterId", "positionMs", "engineLocator"), audio.keys)
        assertEquals("9000", audio.getValue("positionMs").jsonPrimitive.content)
    }

    private fun upload(): ReaderProgressUpload {
        val location = ReflowReaderLocation(
            "EPUB/chapter.xhtml",
            0.4,
            0.6,
            engineLocator = EngineLocator(
                ReaderEngine.Readium,
                ReaderEnginePlatform.Android,
                "3.3.0",
                EngineLocatorPayload.parse("""{"href":"EPUB/chapter.xhtml"}"""),
            ),
            contentFingerprint = ContentFingerprint(ORIGINAL_HASH, "readium-kotlin:3.3.0", "v1"),
        )
        val target = ReaderProgressSyncTarget(
            ReaderSyncNamespace("server", "user", 1),
            "work-1",
            "volume-1",
            ReaderFormat.Epub,
            ReaderServerContentFingerprint("server-token"),
        )
        return ReaderProgressUpload(
            target,
            ReaderProgressSnapshotV4(
                "volume-1",
                60.0,
                1_234,
                "android-client",
                ReaderServerContentFingerprint("server-token"),
                null,
            ),
            location,
        )
    }

    private companion object {
        const val ORIGINAL_HASH = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    }
}
