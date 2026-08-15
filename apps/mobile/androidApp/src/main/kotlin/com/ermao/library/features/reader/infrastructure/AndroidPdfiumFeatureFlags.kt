package com.ermao.library.features.reader.infrastructure

import com.ermao.library.pdfium.ShukuPdfiumNative

internal object AndroidPdfiumFeatureFlags {
    /** Flip only after both locked artifacts and native physical-device acceptance are green. */
    private const val NATIVE_PDFIUM_RANGE_V1_ROLLOUT = false

    val NATIVE_PDFIUM_RANGE_V1: Boolean
        get() = NATIVE_PDFIUM_RANGE_V1_ROLLOUT && ShukuPdfiumNative.isAvailable()
}
