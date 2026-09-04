package com.ermao.library.shared.modules.reader.infrastructure

import java.io.File
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The contract fixtures live in packages/reader-contracts, so both mobile platforms exercise the
 * same JSON rather than maintaining a second hand-copied fixture set.  This host test is wired to
 * the repository fixture directory by shared/build.gradle.kts.
 */
class ReaderV5ContractFixtureTest {
    private val json = Json { ignoreUnknownKeys = false }
    private val mapper = ReaderV5ServerWireMapper()
    private val reportJson = ReaderPositionReportJson(mapper)

    @Test
    fun allReaderV5FormatFixturesRoundTripTheirPositionWithoutLosingLocatorFields() {
        listOf("reflowable-empty-highlight", "pdf", "comic", "audio").forEach { name ->
            val root = fixture(name)
            assertEquals(5L, root.requiredLong("schemaVersion"))
            assertTrue(root.requiredString("clientId").isNotBlank())
            assertTrue(root.requiredString("mutationId").isNotBlank())

            val originalPosition = root.requiredObject("position")
            val originalLocator = originalPosition.requiredObject("locator")
            val report = mapper.decodePosition(originalPosition)
            val encoded = json.parseToJsonElement(reportJson.encode(report)).jsonObject
            assertJsonEquivalent(originalPosition, encoded)

            val decoded = reportJson.decode(encoded.toString())
            assertJsonEquivalent(
                originalLocator,
                json.parseToJsonElement(decoded.locator.canonicalJson),
            )
            assertJsonEquivalent(
                originalPosition.requiredObject("presentation"),
                mapper.encodePosition(decoded).requiredObject("presentation"),
            )
        }
    }

    @Test
    fun fixturePresentationRemainsIndependentFromOpaqueLocatorProgression() {
        val reflow = fixture("reflowable-empty-highlight").requiredObject("position")
        val locator = reflow.requiredObject("locator")
        val presentation = reflow.requiredObject("presentation")
        assertEquals(0.25, locator.requiredObject("locations").requiredDouble("totalProgression"))
        assertEquals(0.99, presentation.requiredDouble("totalProgression"))

        val audio = fixture("audio").requiredObject("position")
        assertEquals(0.35, audio.requiredObject("locator").requiredObject("locations").requiredDouble("totalProgression"))
        assertEquals(0.35, audio.requiredObject("presentation").requiredDouble("totalProgression"))
    }

    private fun fixture(name: String): JsonObject {
        val root = File(
            requireNotNull(System.getProperty("readerV5FixtureRoot")) {
                "readerV5FixtureRoot was not configured"
            },
            "$name.json",
        )
        assertTrue(root.isFile, "Reader v5 fixture does not exist: ${root.absolutePath}")
        return json.parseToJsonElement(root.readText()).jsonObject
    }
}

private fun JsonObject.requiredObject(name: String): JsonObject =
    get(name) as? JsonObject ?: error("Missing object: $name")

private fun JsonObject.requiredString(name: String): String =
    (get(name) as? JsonPrimitive)?.content?.takeIf(String::isNotBlank)
        ?: error("Missing string: $name")

private fun JsonObject.requiredLong(name: String): Long =
    (get(name) as? JsonPrimitive)?.longOrNull ?: error("Missing long: $name")

private fun JsonObject.requiredDouble(name: String): Double =
    (get(name) as? JsonPrimitive)?.doubleOrNull ?: error("Missing double: $name")

private fun assertJsonEquivalent(expected: JsonElement, actual: JsonElement) {
    when {
        expected is JsonObject && actual is JsonObject -> {
            assertEquals(expected.keys, actual.keys)
            expected.keys.forEach { key ->
                assertJsonEquivalent(expected.getValue(key), actual.getValue(key))
            }
        }
        expected is JsonArray && actual is JsonArray -> {
            assertEquals(expected.size, actual.size)
            expected.indices.forEach { index -> assertJsonEquivalent(expected[index], actual[index]) }
        }
        expected == JsonNull || actual == JsonNull -> assertEquals(expected, actual)
        expected is JsonPrimitive && actual is JsonPrimitive -> {
            if (expected.isString || actual.isString) {
                assertEquals(expected.content, actual.content)
            } else {
                assertEquals(expected.doubleOrNull, actual.doubleOrNull)
            }
        }
        else -> assertEquals(expected, actual)
    }
}
