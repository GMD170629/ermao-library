package com.ermao.library.features.reader.infrastructure

import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerialName
import kotlinx.serialization.json.Json
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

@RunWith(Parameterized::class)
class TxtReadiumPublicationFactoryTest(private val fixture: DecodingCase) {
    @Test
    fun `strict decoder conforms to the shared TXT decoding contract`() {
        val bytes = fixture.sourceHex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        if (fixture.expectedText == null) {
            assertFailsWith<IllegalArgumentException>(fixture.id) {
                StrictTxtDecoder.decode(bytes)
            }
        } else {
            assertEquals(fixture.expectedText, StrictTxtDecoder.decode(bytes), fixture.id)
        }
    }

    @Serializable
    data class DecodingCase(
        val id: String,
        val sourceHex: String,
        val expectedText: String?,
        val decoderOverrides: DecoderOverrides? = null,
    ) {
        override fun toString(): String = id
    }

    @Serializable
    data class DecoderOverrides(
        @SerialName("apple-foundation") val appleFoundation: DecodingExpectation? = null,
    )

    @Serializable
    data class DecodingExpectation(val expectedText: String?)

    @Serializable
    private data class DecodingFixtures(
        val schema: String,
        val version: Int,
        val cases: List<DecodingCase>,
    )

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun fixtures(): List<DecodingCase> {
            val source = checkNotNull(
                TxtReadiumPublicationFactoryTest::class.java.getResourceAsStream("/txt-decoding-v1.json"),
            ) { "Shared TXT decoding fixtures must be on the test classpath" }
            val fixtures = source.bufferedReader(Charsets.UTF_8).use {
                Json.decodeFromString<DecodingFixtures>(it.readText())
            }
            assertEquals("ermao.txt-decoding", fixtures.schema)
            assertEquals(1, fixtures.version)
            assertTrue(fixtures.cases.isNotEmpty())
            assertEquals(fixtures.cases.size, fixtures.cases.map { it.id }.toSet().size)
            return fixtures.cases
        }
    }
}
