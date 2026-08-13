package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.application.ReaderProgressUpload
import com.ermao.library.shared.modules.reader.infrastructure.ReaderServerWireMapper
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ReaderServerWireTest {
    @Test
    fun canonicalRequestContainsOnlyExactRevisionMutationFields() {
        val root = Json.parseToJsonElement(ReaderServerWireMapper().encodeProgressUpload(upload())).jsonObject

        assertEquals(
            setOf("schemaVersion", "clientId", "mutationId", "baseRevision", "capturedAtEpochMillis", "locator"),
            root.keys,
        )
        assertEquals("android-client", root.getValue("clientId").jsonPrimitive.content)
        assertEquals("17", root.getValue("baseRevision").jsonPrimitive.content)
        val locator = root.getValue("locator").jsonObject
        assertEquals("reflowable", locator.getValue("kind").jsonPrimitive.content)
        assertEquals("readium", locator.getValue("engineLocator").jsonObject.getValue("engine").jsonPrimitive.content)
        assertEquals("android", locator.getValue("engineLocator").jsonObject.getValue("platform").jsonPrimitive.content)
        assertEquals("sha256:$ORIGINAL_HASH", locator.getValue("publication").jsonObject
            .getValue("originalFileHash").jsonPrimitive.content)
    }

    @Test
    fun canonicalFlatSnapshotIsStrictlyDecoded() {
        val root = Json.parseToJsonElement(
            """{"schemaVersion":4,"revision":18,"locator":$PUBLICATION_LOCATION,"displayPercent":32.7,"receivedAtEpochMillis":1786500000100,"capturedAtEpochMillis":1786499999000}""",
        ).jsonObject

        val snapshot = ReaderServerWireMapper().decodeSnapshot(root, "volume-1")

        assertEquals(18, snapshot.revision)
        assertEquals(32.7, snapshot.displayPercent)
        assertEquals(ReaderEnginePlatform.Android, snapshot.locator.platform)
        assertEquals(1_786_499_999_000, snapshot.capturedAtEpochMillis)
    }

    @Test
    fun progressionOnlyLocatorIsRejected() {
        val invalid = LOCATOR.replace(
            "\"cssSelector\":\"#chapter-title\",\"fragments\":[\"chapter-title\"],",
            "",
        ).replace(",\"text\":{\"highlight\":\"天地玄黄，宇宙洪荒\"}", "")

        assertFailsWith<IllegalArgumentException> { PublicationLocation.parse(reflowable(invalid)) }
    }

    private fun upload() = ReaderProgressUpload(
        ReaderProgressSyncTarget(
            ReaderSyncNamespace("server", "user", 1),
            "work-1",
            "volume-1",
            ReaderFormat.Epub,
        ),
        ReaderProgressMutation(
            sourceId = "volume-1",
            clientId = "android-client",
            mutationId = "58a3ac3c-52d0-41ed-9c85-0524b532f25b",
            baseRevision = 17,
            capturedAtEpochMillis = 1_786_500_000_000,
            locator = PublicationLocation.parse(PUBLICATION_LOCATION),
        ),
    )

    private companion object {
        const val ORIGINAL_HASH = "f2b9fdd81234567890abcdef1234567890abcdef1234567890abcdef12345678"
        val PUBLICATION_LOCATION = reflowable(LOCATOR)
        const val LOCATOR = """{"engine":"readium","platform":"android","version":"readium-kotlin:3.3.0","publication":{"originalFileHash":"$ORIGINAL_HASH","parser":"libmobi:0.12@85dcfe","normalization":"ermao-mobi-core-v1"},"payload":{"href":"part00000.html","type":"application/xhtml+xml","locations":{"cssSelector":"#chapter-title","fragments":["chapter-title"],"progression":0.42,"position":17},"text":{"highlight":"天地玄黄，宇宙洪荒"}}}"""
    }
}

private fun reflowable(envelope: String): String {
    val root = Json.parseToJsonElement(envelope).jsonObject
    return """{"kind":"reflowable","publication":${root.getValue("publication")},"engineLocator":{"engine":${root.getValue("engine")},"platform":${root.getValue("platform")},"version":${root.getValue("version")},"payload":${root.getValue("payload")}}}"""
}
