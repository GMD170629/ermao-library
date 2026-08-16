package com.ermao.library.shared.modules.auth.domain

import platform.Foundation.NSDate
import platform.Foundation.timeIntervalSince1970

internal actual fun platformEpochMillis(): Long = (NSDate().timeIntervalSince1970 * 1_000.0).toLong()
