package com.ermao.library.mobi.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.readerSafetyBinaryResourceMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyReflowableMarkupMaxBytes
import com.ermao.library.shared.modules.reader.readerSafetyReflowableMarkupMaxBytesFailure
import org.readium.r2.shared.util.mediatype.MediaType
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import org.junit.Test

class MobiResourceAdmissionTest {
    private val markup = requireNotNull(MediaType("text/html"))
    private val image = requireNotNull(MediaType("image/jpeg"))

    @Test
    fun oversizedOptionalBinaryIsBlockedWithoutRejectingThePublication() {
        val descriptors = listOf(
            descriptor(0, markup, 1L),
            descriptor(1, image, readerSafetyBinaryResourceMaxBytes()),
            descriptor(2, image, readerSafetyBinaryResourceMaxBytes() + 1L),
        )

        assertEquals(
            listOf(0, 1),
            applyMobiResourceBudgets(descriptors, setOf(0)).map(MobiResourceDescriptor::index),
        )
    }

    @Test
    fun oversizedRequiredMarkupRejectsWithTheGeneratedRule() {
        val failure = assertFailsWith<ReaderSafetyException> {
            applyMobiResourceBudgets(
                listOf(descriptor(0, markup, readerSafetyReflowableMarkupMaxBytes() + 1L)),
                setOf(0),
            )
        }

        assertEquals(readerSafetyReflowableMarkupMaxBytesFailure(), failure.failure)
    }

    private fun descriptor(index: Int, mediaType: MediaType, bytes: Long) =
        MobiResourceDescriptor(index, "resource-$index", mediaType, bytes)
}
