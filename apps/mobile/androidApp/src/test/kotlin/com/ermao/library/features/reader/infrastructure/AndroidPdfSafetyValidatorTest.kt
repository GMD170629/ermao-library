package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSafetyFailure
import com.ermao.library.shared.modules.reader.readerSafetyPdfCanvasMaxDimension
import com.ermao.library.shared.modules.reader.readerSafetyPdfPageGeometryFailure
import com.ermao.library.shared.modules.reader.readerSafetyPdfPageMaxCount
import com.ermao.library.shared.modules.reader.readerSafetyPdfRenderBudgetFailure
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.fail

class AndroidPdfSafetyValidatorTest {
    @Test
    fun `page count and geometry use the generated page rule`() {
        assertSafetyFailure(readerSafetyPdfPageGeometryFailure()) {
            AndroidPdfSafetyValidator.requirePageCount((readerSafetyPdfPageMaxCount() + 1L).toInt())
        }
        assertSafetyFailure(readerSafetyPdfPageGeometryFailure()) {
            AndroidPdfSafetyValidator.requireFinitePageGeometry(Float.NaN, 1f)
        }
    }

    @Test
    fun `render dimensions use the generated render rule`() {
        assertSafetyFailure(readerSafetyPdfRenderBudgetFailure()) {
            AndroidPdfSafetyValidator.requireRenderBudget(
                (readerSafetyPdfCanvasMaxDimension() + 1L).toInt(),
                1,
            )
        }
    }

    private fun assertSafetyFailure(expected: ReaderSafetyFailure, block: () -> Unit) {
        val failure = try {
            block()
            fail("Expected ShukuPdfiumFailure")
        } catch (error: ShukuPdfiumFailure) {
            error.safeContext
        }
        assertEquals(expected.ruleId, failure["ruleId"])
        assertEquals(expected.errorCode, failure["errorCode"])
    }
}
