package com.ermao.library.features.reader.infrastructure

import com.ermao.library.pdfium.ShukuPdfiumNative

internal object AndroidPdfiumFeatureFlags {
    /** Keep enabled so physical-device acceptance exercises Range; the locked native artifact remains mandatory. */
    private const val NATIVE_PDFIUM_RANGE_V1_ROLLOUT = true

    val NATIVE_PDFIUM_RANGE_V1: Boolean
        get() = NATIVE_PDFIUM_RANGE_V1_ROLLOUT && ShukuPdfiumNative.isAvailable()
}
