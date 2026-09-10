package com.ermao.library.shared.modules.administrativesettings.application

import com.ermao.library.shared.modules.administrativesettings.createOpdsEditState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class OpdsEditStateTest {
    @Test
    fun bothToggleDirectionsSubmitWithoutASeparateSaveAction() {
        for (enabled in listOf(false, true)) {
            val initial = createOpdsEditState(enabled, "https://books.example/base")
            val pending = initial.changeEnabled(!enabled).beginSubmission()
            assertEquals(!enabled, pending.draft.enabled)
            assertEquals(OpdsEditValues(!enabled, "https://books.example/base"), pending.submission)
        }
    }

    @Test
    fun focusLossAndToggleUseOneCombinedRequest() {
        val edited = createOpdsEditState(false, "https://old.example")
            .editAddress(" https://new.example/library ")
        val submitted = edited.changeEnabled(true).beginSubmission()
        assertEquals(OpdsEditValues(true, "https://new.example/library"), submitted.submission)
        assertEquals(submitted, submitted.beginSubmission())
        assertEquals(submitted, submitted.changeEnabled(false))
        assertEquals(submitted, submitted.editAddress("https://ignored.example"))
    }

    @Test
    fun unchangedAddressAndRepeatedCompletionDoNotSubmit() {
        val initial = createOpdsEditState(true, "https://books.example")
        assertNull(initial.beginSubmission().submission)
        assertNull(initial.editAddress(" https://books.example ").beginSubmission().submission)
        val finished = initial.editAddress("https://new.example/").beginSubmission()
            .accept(true, "https://new.example")
        assertNull(finished.beginSubmission().submission)
        assertEquals("https://new.example", finished.draft.publicBaseUrl)
    }

    @Test
    fun rejectedToggleRollsBackWhilePreservingAddressForRetry() {
        val initial = createOpdsEditState(true, "https://books.example")
        val failed = initial.editAddress("invalid URL").changeEnabled(false).beginSubmission().reject()
        assertTrue(failed.draft.enabled)
        assertEquals("invalid URL", failed.draft.publicBaseUrl)
        assertEquals(initial.confirmed, failed.confirmed)
        assertFalse(failed.isSubmitting)
        assertEquals(OpdsEditValues(true, "https://fixed.example"), failed.editAddress("https://fixed.example").beginSubmission().submission)
    }

    @Test
    fun serverResponseBecomesTheOnlyConfirmedConfiguration() {
        val submitted = createOpdsEditState(true, "https://books.example")
            .changeEnabled(false).beginSubmission()
        val finished = submitted.accept(false, "https://books.example")
        assertFalse(finished.draft.enabled)
        assertFalse(finished.isSubmitting)
        assertNull(finished.beginSubmission().submission)
    }
}
