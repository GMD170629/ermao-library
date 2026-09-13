@file:Suppress("CAST_NEVER_SUCCEEDS")

package com.ermao.library.shared.modules.library.domain

import platform.Foundation.NSString
import platform.Foundation.precomposedStringWithCompatibilityMapping

internal actual fun normalizeTagCompatibility(value: String): String =
    (value as NSString).precomposedStringWithCompatibilityMapping
