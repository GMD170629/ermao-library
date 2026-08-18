package com.ermao.library.shared.modules.library.domain

const val IMPLICIT_WORK_VERSION_SOURCE_KEY = "__implicit__"

data class WorkVersion(
    val id: String,
    val sourceKey: String,
    val sourceName: String?,
    val completed: Boolean,
    val volumeCount: Int,
    val sizeBytes: Long,
    /** The detail summary is bounded; use volumeCount to determine whether another page exists. */
    val volumes: List<Volume>,
)
