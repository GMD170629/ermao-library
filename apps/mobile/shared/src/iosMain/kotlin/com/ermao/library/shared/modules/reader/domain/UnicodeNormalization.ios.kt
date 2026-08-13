@file:Suppress("CAST_NEVER_SUCCEEDS")

package com.ermao.library.shared.modules.reader.domain

import platform.Foundation.NSString
import platform.Foundation.precomposedStringWithCanonicalMapping

internal actual fun String.normalizeUnicodeNfc(): String =
    // Kotlin/Native bridges String to NSString at the Objective-C boundary; the compiler
    // cannot model this documented mapped-type cast and reports a false-positive warning.
    (this as NSString).precomposedStringWithCanonicalMapping
