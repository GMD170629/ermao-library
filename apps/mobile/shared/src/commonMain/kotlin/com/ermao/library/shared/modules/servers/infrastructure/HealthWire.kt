package com.ermao.library.shared.modules.servers.infrastructure

import kotlinx.serialization.Serializable

@Serializable
internal data class ServiceHealthWire(
    val service: String,
    val status: String,
)
