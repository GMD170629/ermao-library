package com.ermao.library.shared.modules.reader

import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_CHUNK_BYTES
import com.ermao.library.shared.modules.reader.domain.PDF_RANGE_MAX_REQUEST_BYTES
import com.ermao.library.shared.modules.reader.domain.PdfByteRange
import com.ermao.library.shared.modules.reader.domain.PdfRangeCacheIdentity
import com.ermao.library.shared.modules.reader.domain.ReaderSyncNamespace
import com.ermao.library.shared.modules.reader.domain.planPdfByteRanges
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class PdfRangePolicyTest {
    @Test
    fun alignsAndCapsByteRanges() {
        assertEquals(
            listOf(
                PdfByteRange(0, PDF_RANGE_MAX_REQUEST_BYTES.toLong()),
                PdfByteRange(
                    PDF_RANGE_MAX_REQUEST_BYTES.toLong(),
                    (PDF_RANGE_MAX_REQUEST_BYTES + PDF_RANGE_CHUNK_BYTES).toLong(),
                ),
            ),
            planPdfByteRanges(
                7,
                (PDF_RANGE_MAX_REQUEST_BYTES + 7).toLong(),
                (PDF_RANGE_MAX_REQUEST_BYTES * 2).toLong(),
            ),
        )
    }

    @Test
    fun cacheIdentityIncludesAuthorizationAndResource() {
        val baseline = identity(authorizationVersion = 3)
        assertNotEquals(baseline.stableKey, identity(authorizationVersion = 4).stableKey)
        assertEquals(baseline.stableKey, identity(authorizationVersion = 3).stableKey)
    }

    private fun identity(authorizationVersion: Long) = PdfRangeCacheIdentity(
        ReaderSyncNamespace("server", "user", authorizationVersion),
        "resource",
    )
}
