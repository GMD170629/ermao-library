package com.ermao.library.shared.modules.library.domain

data class MediaVersion(
    val id: String,
    val mediaKind: MediaKind,
    val completed: Boolean,
    val volumeCount: Int,
    val sizeBytes: Long,
    /** The detail summary is bounded; use volumeCount to determine whether another page exists. */
    val volumes: List<Volume>,
)
