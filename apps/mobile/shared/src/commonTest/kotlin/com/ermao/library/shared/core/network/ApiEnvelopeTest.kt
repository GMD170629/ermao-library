package com.ermao.library.shared.core.network

import com.ermao.library.shared.modules.servers.infrastructure.ServerCompatibilityWire
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlinx.serialization.json.Json

class ApiEnvelopeTest {
    private val decoder = ApiEnvelopeDecoder(Json { ignoreUnknownKeys = false })

    @Test
    fun decodesTheRealNestedCompatibilityContract() {
        val result = decoder.decode(
            200,
            COMPATIBILITY_FIXTURE,
            ServerCompatibilityWire.serializer(),
        )

        val success = assertIs<ApiResult.Success<ServerCompatibilityWire>>(result)
        assertEquals(3, success.value.protocol.minimumSupportedClientVersion)
        assertEquals(5, success.value.readerSchemaVersion)
        assertEquals(1, success.value.librarySchemaVersion)
    }

    @Test
    fun mapsFastApiValidationArrayAndParameters() {
        val result = decoder.decode(
            422,
            """{"ok":false,"error":{"message":"invalid","details":[{"loc":["body","email"],"message":"bad email","type":"value_error","input":"x"}],"params":{"limit":"50"}}}""",
            ServerCompatibilityWire.serializer(),
        )

        val error = assertIs<ApiResult.Failure>(result).error
        assertEquals("VALIDATION", error.code)
        assertEquals(listOf("value_error"), error.fieldErrors["email"])
        assertEquals("50", error.parameters["limit"])
    }

    @Test
    fun nestedSetupCodeTakesPriorityOverStatusFallback() {
        val result = decoder.decode(
            409,
            """{"ok":false,"error":{"message":"setup","details":{"code":"SETUP_REQUIRED"}}}""",
            ServerCompatibilityWire.serializer(),
        )
        assertEquals("SETUP_REQUIRED", assertIs<ApiResult.Failure>(result).error.code)
    }

    @Test
    fun usesTheFrozenFallbackCodes() {
        val expected = mapOf(404 to "NOT_FOUND", 412 to "CONFLICT", 422 to "VALIDATION", 503 to "UNAVAILABLE")
        expected.forEach { (status, code) ->
            val result = decoder.decode(
                status,
                """{"ok":false,"error":{"message":"failure"}}""",
                ServerCompatibilityWire.serializer(),
            )
            assertEquals(code, assertIs<ApiResult.Failure>(result).error.code)
        }
    }

    private companion object {
        val COMPATIBILITY_FIXTURE = """
            {"ok":true,"data":{"service":"ermao-books","serverIdentity":"server_fixture","serverVersion":"1.2.3","protocol":{"version":3,"minimumSupportedClientVersion":3},"readerSchemaVersion":5,"librarySchemaVersion":1,"capabilities":{"setup":true,"cookieSession":true,"readerV5":true,"mediaRange":true,"managedOfflineDownloads":true,"bookResourceAsset":true,"bookDetailManagement":false}}}
        """.trimIndent()
    }
}
