package com.ermao.library.shared.modules.servers.infrastructure

import com.ermao.library.shared.modules.servers.domain.ServerCapabilities
import com.ermao.library.shared.modules.servers.domain.ServerCompatibility
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class ServerCompatibilityWire(
    val service: String,
    val serverIdentity: String,
    val serverVersion: String,
    val protocol: ServerProtocolWire,
    val readerSchemaVersion: Int,
    val capabilities: ServerCapabilitiesWire,
)

@Serializable
data class ServerProtocolWire(
    val version: Int,
    val minimumSupportedClientVersion: Int,
)

@Serializable
data class ServerCapabilitiesWire(
    val setup: Boolean,
    val cookieSession: Boolean,
    val readerV4: Boolean,
    val mediaRange: Boolean,
    val managedOfflineDownloads: Boolean,
    val workDetailManagement: Boolean = false,
)

fun ServerCompatibilityWire.toDomain(): ServerCompatibility = ServerCompatibility(
    service = service,
    serverIdentity = serverIdentity,
    serverVersion = serverVersion,
    protocolVersion = protocol.version,
    minimumSupportedClientVersion = protocol.minimumSupportedClientVersion,
    readerSchemaVersion = readerSchemaVersion,
    capabilities = ServerCapabilities(
        setup = capabilities.setup,
        cookieSession = capabilities.cookieSession,
        readerV4 = capabilities.readerV4,
        mediaRange = capabilities.mediaRange,
        managedOfflineDownloads = capabilities.managedOfflineDownloads,
        workDetailManagement = capabilities.workDetailManagement,
    ),
)
