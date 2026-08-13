package com.ermao.library.reader.mobipoc

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.ermao.library.shared.modules.reader.ExactBlockMatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class MobiReadiumConformanceTest {
    @Test
    fun pinnedMobiPublicationGoesAndRecapturesTheSameExactBlock() {
        ActivityScenario.launch(MobiReadiumConformanceActivity::class.java).use { scenario ->
            lateinit var activity: MobiReadiumConformanceActivity
            scenario.onActivity { activity = it }
            assertTrue("Readium conformance POC timed out", activity.completion.await(30, TimeUnit.SECONDS))
            assertNull(activity.failure?.stackTraceToString(), activity.failure)
            val report = requireNotNull(activity.report)

            assertEquals(MobiReadiumConformanceActivity.EXPECTED_FILE_SHA256, report.originalFileHash)
            assertEquals(MobiReadiumConformanceActivity.EXPECTED_PARSER, report.parser)
            assertEquals(MobiReadiumConformanceActivity.EXPECTED_NORMALIZATION, report.normalization)
            assertEquals(listOf(MobiReadiumConformanceActivity.EXPECTED_HREF), report.readingOrderHrefs)
            assertEquals(MobiReadiumConformanceActivity.EXPECTED_XHTML_SHA256, report.xhtmlSha256)
            assertEquals(ExactBlockMatch.Exact, report.exactBlockMatch)
            assertTrue(report.expectedLocator.contains("ZH_TEXT_MARKER"))
            assertTrue(report.recapturedLocator.contains("ZH_TEXT_MARKER"))
        }
    }
}
