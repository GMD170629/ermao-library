package com.ermao.library.features.reader.application

/**
 * The position candidate selected before a Reader engine is opened.
 *
 * This is deliberately explicit instead of using a nullable server snapshot
 * as a sentinel. A server snapshot being absent does not mean that a local
 * confirmed position may be used: only an already durable pending mutation
 * owns startup restore (with LocalOnly as the explicit local-file exception).
 */
internal enum class ReaderStartupPositionSource {
    ExplicitTarget,
    LocalPending,
    ServerSnapshot,
    Start,
    LocalOnly,
}

internal fun selectReaderStartupPositionSource(
    hasExplicitTarget: Boolean,
    hasLocalPending: Boolean,
    hasServerSnapshot: Boolean,
    localOnlySource: Boolean,
): ReaderStartupPositionSource = when {
    hasExplicitTarget -> ReaderStartupPositionSource.ExplicitTarget
    localOnlySource -> ReaderStartupPositionSource.LocalOnly
    hasLocalPending -> ReaderStartupPositionSource.LocalPending
    hasServerSnapshot -> ReaderStartupPositionSource.ServerSnapshot
    else -> ReaderStartupPositionSource.Start
}
