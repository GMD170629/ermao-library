package com.ermao.library.shared.core.storage

/** Non-null bridge result that keeps an absent payload distinct from an Objective-C error. */
data class PlatformStoragePayload(val value: String?)

/** Stable failure type for storage implementations supplied by each platform. */
class PlatformStorageException(
    message: String,
    cause: Throwable? = null,
) : Exception(message, cause)
