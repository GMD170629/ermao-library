package com.ermao.library.shared.modules.reader

import com.ermao.library.testing.reader.ReaderSafetyConformanceRunner
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.serialization.json.jsonArray

class ReaderSafetyConformanceReportTest {
    @Test
    fun kmpReportExecutesSharedSafetyFacadeAndMatchesContract() {
        val runner = ReaderSafetyConformanceRunner(
            File(requireNotNull(System.getProperty("readerSafetyFixtureRoot"))),
        )
        val report = runner.generate("KMP", "kmp-android-host/shared-facade")

        runner.verifyAgainstManifest(report)
        assertEquals(30, report.getValue("results").jsonArray.size)
        assertEquals(0, report.getValue("omissions").jsonArray.size)
        runner.write(
            report,
            File(requireNotNull(System.getProperty("readerSafetyReportPath"))),
        )
    }

    @Test
    fun androidReportCannotImpersonateANativeAdapterFromTheHostFacade() {
        val runner = ReaderSafetyConformanceRunner(
            File(requireNotNull(System.getProperty("readerSafetyFixtureRoot"))),
        )

        val failure = runCatching { runner.generate("ANDROID", "invalid-shared-only") }.exceptionOrNull()

        assertEquals("ANDROID_PRODUCTION_ADAPTER_UNAVAILABLE", failure?.message)
    }

    @Test
    fun instrumentationJsonLoaderUsesTheSameValidatedSuite() {
        val fixtureRoot = File(requireNotNull(System.getProperty("readerSafetyFixtureRoot")))
        val runner = ReaderSafetyConformanceRunner.fromJson(
            suiteJson = File(fixtureRoot, "conformance-suite.json").readText(),
            manifestJson = File(fixtureRoot, "manifest.json").readText(),
        )

        val report = runner.generate("KMP", "json-loader-contract-test")

        runner.verifyAgainstManifest(report)
        assertEquals(30, report.getValue("results").jsonArray.size)
        assertEquals(0, report.getValue("omissions").jsonArray.size)
    }
}
