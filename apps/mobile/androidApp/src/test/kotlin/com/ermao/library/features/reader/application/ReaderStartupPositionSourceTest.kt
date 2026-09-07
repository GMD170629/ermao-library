package com.ermao.library.features.reader.application

import kotlin.test.assertEquals
import org.junit.Test

class ReaderStartupPositionSourceTest {
    @Test
    fun explicitTargetAlwaysWins() {
        assertEquals(
            ReaderStartupPositionSource.ExplicitTarget,
            selectReaderStartupPositionSource(
                hasExplicitTarget = true,
                hasLocalPending = true,
                hasServerSnapshot = true,
                localOnlySource = true,
            ),
        )
    }

    @Test
    fun localOnlySourceMayUseConfirmedLocalPosition() {
        assertEquals(
            ReaderStartupPositionSource.LocalOnly,
            selectReaderStartupPositionSource(
                hasExplicitTarget = false,
                hasLocalPending = false,
                hasServerSnapshot = false,
                localOnlySource = true,
            ),
        )
    }

    @Test
    fun pendingWinsOverServerSnapshot() {
        assertEquals(
            ReaderStartupPositionSource.LocalPending,
            selectReaderStartupPositionSource(
                hasExplicitTarget = false,
                hasLocalPending = true,
                hasServerSnapshot = true,
                localOnlySource = false,
            ),
        )
    }

    @Test
    fun serverWinsOnlyWhenThereIsNoPendingMutation() {
        assertEquals(
            ReaderStartupPositionSource.ServerSnapshot,
            selectReaderStartupPositionSource(
                hasExplicitTarget = false,
                hasLocalPending = false,
                hasServerSnapshot = true,
                localOnlySource = false,
            ),
        )
    }

    @Test
    fun emptySynchronizedStateStartsAtBeginning() {
        assertEquals(
            ReaderStartupPositionSource.Start,
            selectReaderStartupPositionSource(
                hasExplicitTarget = false,
                hasLocalPending = false,
                hasServerSnapshot = false,
                localOnlySource = false,
            ),
        )
    }
    @Test
    fun unavailableServerUsesConfirmedLocalPositionWithoutOverridingPendingOrServer() {
        assertEquals(
            ReaderStartupPositionSource.LocalFallback,
            selectReaderStartupPositionSource(false, false, false, false, serverUnavailable = true),
        )
        assertEquals(
            ReaderStartupPositionSource.LocalPending,
            selectReaderStartupPositionSource(false, true, false, false, serverUnavailable = true),
        )
        assertEquals(
            ReaderStartupPositionSource.ServerSnapshot,
            selectReaderStartupPositionSource(false, false, true, false, serverUnavailable = true),
        )
        assertEquals(
            ReaderStartupPositionSource.ExplicitTarget,
            selectReaderStartupPositionSource(true, false, false, false, serverUnavailable = true),
        )
        // An authoritative empty response (or a nonrecoverable failure) does not opt in.
        assertEquals(
            ReaderStartupPositionSource.Start,
            selectReaderStartupPositionSource(false, false, false, false, serverUnavailable = false),
        )
    }

}
