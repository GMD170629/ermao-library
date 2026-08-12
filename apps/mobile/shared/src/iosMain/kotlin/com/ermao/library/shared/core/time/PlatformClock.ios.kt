package com.ermao.library.shared.core.time

import platform.Foundation.NSDate

internal actual fun currentEpochMillis(): Long =
    ((NSDate().timeIntervalSinceReferenceDate + UNIX_REFERENCE_OFFSET_SECONDS) * 1_000.0).toLong()

private const val UNIX_REFERENCE_OFFSET_SECONDS = 978_307_200.0
