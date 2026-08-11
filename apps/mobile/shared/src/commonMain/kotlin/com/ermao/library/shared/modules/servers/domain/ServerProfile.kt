package com.ermao.library.shared.modules.servers.domain

import kotlinx.serialization.Serializable

data class ServerProfile(
    val id: String,
    val displayName: String,
    val baseUrl: ServerBaseUrl,
    val serverIdentity: String,
    val isActive: Boolean,
    val tlsMode: TlsMode,
)

/** Flat immutable projection for the Objective-C-compatible Swift framework boundary. */
data class ServerProfileSnapshot(
    val id: String,
    val displayName: String,
    val baseUrl: String,
    val serverIdentity: String,
    val isActive: Boolean,
    val tlsMode: TlsMode,
)

fun ServerProfile.toSnapshot(): ServerProfileSnapshot = ServerProfileSnapshot(
    id = id,
    displayName = displayName,
    baseUrl = baseUrl.value,
    serverIdentity = serverIdentity,
    isActive = isActive,
    tlsMode = tlsMode,
)

data class ServerConnectionDraft(
    val displayName: String,
    val rawBaseUrl: String,
    val tlsMode: TlsMode = TlsMode.SystemTrust,
)

@Serializable
enum class TlsMode {
    SystemTrust,
    InsecureSkipAllValidation,
}
