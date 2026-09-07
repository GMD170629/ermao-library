package com.ermao.library.features.reader.application

/**
 * The position candidate selected before a Reader engine is opened.
 *
 * This is deliberately explicit instead of using a nullable server snapshot
 * as a sentinel. A server snapshot being absent does not mean that a local
 * confirmed position may be used. A recoverable query failure explicitly permits
 * the same resource's durable local position; an authoritative empty result does not.
 */
internal enum class ReaderStartupPositionSource {
    ExplicitTarget,
    LocalPending,
    ServerSnapshot,
    Start,
    LocalOnly,
    LocalFallback,
}

internal fun selectReaderStartupPositionSource(
    hasExplicitTarget: Boolean,
    hasLocalPending: Boolean,
    hasServerSnapshot: Boolean,
    localOnlySource: Boolean,
    serverUnavailable: Boolean = false,
): ReaderStartupPositionSource = when {
    hasExplicitTarget -> ReaderStartupPositionSource.ExplicitTarget
    localOnlySource -> ReaderStartupPositionSource.LocalOnly
    hasLocalPending -> ReaderStartupPositionSource.LocalPending
    hasServerSnapshot -> ReaderStartupPositionSource.ServerSnapshot
    serverUnavailable -> ReaderStartupPositionSource.LocalFallback
    else -> ReaderStartupPositionSource.Start
}
