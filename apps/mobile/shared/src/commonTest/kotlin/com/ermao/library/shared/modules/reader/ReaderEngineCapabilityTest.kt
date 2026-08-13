package com.ermao.library.shared.modules.reader

import kotlin.test.Test
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ReaderEngineCapabilityTest {
    @Test
    fun formatIsNotOpenableUntilTheFullVerticalSliceExists() {
        val registry = ReaderEngineCapabilityRegistry(
            listOf(
                ReaderEngineCapability(ReaderSourceFormat.Txt, parserAvailable = true, navigatorAvailable = true, exactLocationAvailable = true),
                ReaderEngineCapability(ReaderSourceFormat.Cbz, parserAvailable = true, navigatorAvailable = false, exactLocationAvailable = true),
                ReaderEngineCapability(ReaderSourceFormat.Pdf, parserAvailable = false, navigatorAvailable = false, exactLocationAvailable = true),
            ),
        )

        assertTrue(registry.requireOpenable(ReaderSourceFormat.Txt).localArtifactRequired)
        assertFalse(requireNotNull(registry.capability(ReaderSourceFormat.Cbz)).canOpen)
        assertFailsWith<IllegalArgumentException> { registry.requireOpenable(ReaderSourceFormat.Cbz) }
        assertFailsWith<IllegalArgumentException> { registry.requireOpenable(ReaderSourceFormat.Pdf) }
    }

    @Test
    fun duplicatePlatformRegistrationIsRejected() {
        assertFailsWith<IllegalArgumentException> {
            ReaderEngineCapabilityRegistry(
                listOf(
                    ReaderEngineCapability(ReaderSourceFormat.Txt, true, true, true, true),
                    ReaderEngineCapability(ReaderSourceFormat.Txt, true, true, true, true),
                ),
            )
        }
    }
}
