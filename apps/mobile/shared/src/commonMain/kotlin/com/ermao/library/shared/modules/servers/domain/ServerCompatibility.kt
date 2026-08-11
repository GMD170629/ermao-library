package com.ermao.library.shared.modules.servers.domain

data class ServerCompatibility(
    val service: String,
    val serverIdentity: String,
    val serverVersion: String,
    val protocolVersion: Int,
    val minimumSupportedClientVersion: Int,
    val readerSchemaVersion: Int,
    val capabilities: ServerCapabilities,
)

data class ServerCapabilities(
    val setup: Boolean,
    val cookieSession: Boolean,
    val readerV3: Boolean,
    val mediaRange: Boolean,
    val managedOfflineDownloads: Boolean,
)

sealed interface ServerCompatibilityDecision {
    data class Compatible(val compatibility: ServerCompatibility) : ServerCompatibilityDecision

    data class Incompatible(val reasonCode: String) : ServerCompatibilityDecision
}
