package com.ermao.library.shared.modules.servers.application

import com.ermao.library.shared.modules.servers.domain.ServerCapabilities
import com.ermao.library.shared.modules.servers.domain.ServerCompatibility
import com.ermao.library.shared.modules.servers.domain.ServerCompatibilityDecision
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ServerCompatibilityCheckerTest {
    private val checker = ServerCompatibilityChecker(3, setOf(3), setOf(4), setOf(1))

    @Test
    fun acceptsTheCurrentProtocol() {
        assertIs<ServerCompatibilityDecision.Compatible>(checker.check(compatibility()))
    }

    @Test
    fun rejectsAClientBelowTheServerMinimum() {
        val decision = assertIs<ServerCompatibilityDecision.Incompatible>(
            checker.check(compatibility(minimumClient = 4)),
        )
        assertEquals("CLIENT_UPDATE_REQUIRED", decision.reasonCode)
    }

    @Test
    fun rejectsAnUnsupportedServerProtocolEvenWhenClientIsNewEnough() {
        val decision = assertIs<ServerCompatibilityDecision.Incompatible>(
            checker.check(compatibility(protocol = 4)),
        )
        assertEquals("UNSUPPORTED_PROTOCOL_VERSION", decision.reasonCode)
    }

    @Test
    fun rejectsAServerThatDisablesReaderV4Capability() {
        val unsupported = compatibility().let { current ->
            current.copy(capabilities = current.capabilities.copy(readerV4 = false))
        }

        val decision = assertIs<ServerCompatibilityDecision.Incompatible>(checker.check(unsupported))

        assertEquals("READER_V4_REQUIRED", decision.reasonCode)
    }

    @Test
    fun rejectsThePreCutoverLibraryIdentityContract() {
        val decision = assertIs<ServerCompatibilityDecision.Incompatible>(
            checker.check(compatibility(librarySchema = 0)),
        )

        assertEquals("UNSUPPORTED_LIBRARY_SCHEMA", decision.reasonCode)
    }

    @Test
    fun rejectsAServerWithoutBookResourceAssetIdentity() {
        val unsupported = compatibility().let { current ->
            current.copy(capabilities = current.capabilities.copy(bookResourceAsset = false))
        }

        val decision = assertIs<ServerCompatibilityDecision.Incompatible>(checker.check(unsupported))

        assertEquals("BOOK_RESOURCE_ASSET_REQUIRED", decision.reasonCode)
    }

    private fun compatibility(
        protocol: Int = 3,
        minimumClient: Int = 3,
        librarySchema: Int = 1,
    ) = ServerCompatibility(
        service = "ermao-books",
        serverIdentity = "server",
        serverVersion = "not-used-for-protocol-comparison",
        protocolVersion = protocol,
        minimumSupportedClientVersion = minimumClient,
        readerSchemaVersion = 4,
        librarySchemaVersion = librarySchema,
        capabilities = ServerCapabilities(
            setup = true,
            cookieSession = true,
            readerV4 = true,
            mediaRange = true,
            managedOfflineDownloads = true,
            bookResourceAsset = true,
            bookDetailManagement = false,
        ),
    )
}
