package com.ermao.library.shared.modules.reader.application

import com.ermao.library.shared.modules.reader.domain.ReaderLocation
import com.ermao.library.shared.modules.reader.domain.ReaderPreferences
import com.ermao.library.shared.modules.reader.domain.ReaderSource
import com.ermao.library.shared.modules.reader.domain.ReflowReaderLocation
import com.ermao.library.shared.modules.reader.domain.ComicReaderLocation
import kotlinx.coroutines.flow.StateFlow

fun interface ReaderClock {
    fun nowEpochMillis(): Long
}

fun interface ReaderDeviceIdentity {
    fun stableDeviceId(): String
}

data class ReaderOpenRequest(
    val source: ReaderSource,
    val initialLocation: ReaderLocation?,
    val initialPreferences: ReaderPreferences,
)

data class ReaderTocEntry(
    val title: String,
    val location: ReaderLocation,
    val children: List<ReaderTocEntry> = emptyList(),
    val id: String = title,
    val index: Int = 0,
    val target: ReaderNavigationTarget = ReaderNavigationTarget.from(location),
) {
    init {
        require(title.isNotBlank()) { "Reader table-of-contents title is blank" }
    }
}

@kotlinx.serialization.Serializable
sealed interface ReaderNavigationTarget {
    @kotlinx.serialization.Serializable
    data class Reflowable(val href: String) : ReaderNavigationTarget
    @kotlinx.serialization.Serializable
    data class Pdf(val pageIndex: Int) : ReaderNavigationTarget
    @kotlinx.serialization.Serializable
    data class Comic(val pageIndex: Int, val resourceHref: String) : ReaderNavigationTarget
    @kotlinx.serialization.Serializable
    data class Invalid(val reasonCode: String = "READER_NAVIGATION_TARGET_INVALID") : ReaderNavigationTarget

    companion object {
        fun from(location: ReaderLocation): ReaderNavigationTarget = when (location) {
            is ReflowReaderLocation -> location.resourceKey
                ?.let(ReaderNavigationTarget::Reflowable)
                ?: Invalid()
            is com.ermao.library.shared.modules.reader.domain.PdfReaderLocation -> Pdf(location.pageIndex)
            is ComicReaderLocation -> Comic(location.pageIndex, location.resourceHref)
            else -> Invalid()
        }
    }
}

sealed interface ReaderNavigationResult {
    data class Completed(val moved: Boolean) : ReaderNavigationResult
    data class Rejected(val reasonCode: String) : ReaderNavigationResult {
        init {
            require(reasonCode.isNotBlank())
        }
    }
}

sealed interface ReaderCommandResult {
    data object Completed : ReaderCommandResult

    data class Rejected(val reasonCode: String, val cause: Throwable? = null) : ReaderCommandResult {
        init {
            require(reasonCode.isNotBlank()) { "Reader rejection reason is blank" }
        }
    }
}

interface ReaderEnginePort {
    val currentLocation: StateFlow<ReaderLocation?>
    val preferences: StateFlow<ReaderPreferences>

    suspend fun open(request: ReaderOpenRequest): ReaderCommandResult

    suspend fun goPrevious(): ReaderCommandResult

    suspend fun goNext(): ReaderCommandResult

    suspend fun goTo(location: ReaderLocation): ReaderCommandResult

    suspend fun tableOfContents(): List<ReaderTocEntry>

    suspend fun updatePreferences(preferences: ReaderPreferences): ReaderCommandResult

    suspend fun close()
}
