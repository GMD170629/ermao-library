package com.ermao.library.shared.modules.servers.application

import com.ermao.library.shared.modules.servers.domain.ServerCompatibility
import com.ermao.library.shared.modules.servers.domain.ServerCompatibilityDecision

class ServerCompatibilityChecker(
    private val clientProtocolVersion: Int,
    private val supportedServerProtocolVersions: Set<Int>,
    private val supportedReaderSchemaVersions: Set<Int>,
    private val supportedLibrarySchemaVersions: Set<Int>,
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
        if (compatibility.librarySchemaVersion !in supportedLibrarySchemaVersions) {
            return ServerCompatibilityDecision.Incompatible("UNSUPPORTED_LIBRARY_SCHEMA")
        }
        if (!compatibility.capabilities.cookieSession) {
            return ServerCompatibilityDecision.Incompatible("COOKIE_SESSION_REQUIRED")
        }
        if (!compatibility.capabilities.readerV5) {
            return ServerCompatibilityDecision.Incompatible("READER_V5_REQUIRED")
        }
        if (!compatibility.capabilities.bookResourceAsset) {
            return ServerCompatibilityDecision.Incompatible("BOOK_RESOURCE_ASSET_REQUIRED")
        }
        if (!compatibility.capabilities.managedOfflineDownloads) {
            return ServerCompatibilityDecision.Incompatible("MOBILE_DOWNLOADS_REQUIRED")
        }
        return ServerCompatibilityDecision.Compatible(compatibility)
    }

    private companion object {
        const val EXPECTED_SERVICE = "ermao-books"
    }
}
