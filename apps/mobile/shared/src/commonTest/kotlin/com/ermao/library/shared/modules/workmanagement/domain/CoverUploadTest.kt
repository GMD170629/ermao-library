package com.ermao.library.shared.modules.workmanagement.domain

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class CoverUploadTest {
    @Test
    fun acceptsSupportedImageAtMaximumSize() {
        val upload = CoverUpload(
            fileName = "cover.webp",
            mimeType = "image/webp",
            bytes = ByteArray(CoverUpload.MAXIMUM_COVER_BYTES),
        )

        assertEquals(CoverUpload.MAXIMUM_COVER_BYTES, upload.bytes.size)
    }

    @Test
    fun rejectsUnsupportedEmptyAndOversizedImages() {
        assertFailsWith<IllegalArgumentException> {
            CoverUpload("cover.gif", "image/gif", byteArrayOf(1))
        }
        assertFailsWith<IllegalArgumentException> {
            CoverUpload("cover.jpg", "image/jpeg", byteArrayOf())
        }
        assertFailsWith<IllegalArgumentException> {
            CoverUpload(
                "cover.jpg",
                "image/jpeg",
                ByteArray(CoverUpload.MAXIMUM_COVER_BYTES + 1),
            )
        }
    }
}
