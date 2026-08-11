package com.ermao.library.shared.modules.servers.application

import com.ermao.library.shared.modules.servers.domain.ServerCompatibility
import com.ermao.library.shared.modules.servers.domain.ServerCompatibilityDecision

class ServerCompatibilityChecker(
    private val clientProtocolVersion: Int,
    private val supportedServerProtocolVersions: Set<Int>,
    private val supportedReaderSchemaVersions: Set<Int>,
) {
    fun check(compatibility: ServerCompatibility): ServerCompatibilityDecision {
        if (compatibility.service != EXPECTED_SERVICE) {
            return ServerCompatibilityDecision.Incompatible("UNEXPECTED_SERVICE")
        }
        if (compatibility.serverIdentity.isBlank()) {
            return ServerCompatibilityDecision.Incompatible("MISSING_SERVER_IDENTITY")
        }
        if (compatibility.protocolVersion !in supportedServerProtocolVersions) {
            return ServerCompatibilityDecision.Incompatible("UNSUPPORTED_PROTOCOL_VERSION")
        }
        if (clientProtocolVersion < compatibility.minimumSupportedClientVersion) {
            return ServerCompatibilityDecision.Incompatible("CLIENT_UPDATE_REQUIRED")
        }
        if (compatibility.readerSchemaVersion !in supportedReaderSchemaVersions) {
            return ServerCompatibilityDecision.Incompatible("UNSUPPORTED_READER_SCHEMA")
        }
        if (!compatibility.capabilities.cookieSession) {
            return ServerCompatibilityDecision.Incompatible("COOKIE_SESSION_REQUIRED")
        }
        return ServerCompatibilityDecision.Compatible(compatibility)
    }

    private companion object {
        const val EXPECTED_SERVICE = "ermao-books"
    }
}
