package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderPdfFit
import com.ermao.library.shared.modules.reader.ReaderPdfPreferences
import kotlin.test.assertEquals
import org.junit.Test
import org.readium.r2.navigator.preferences.Axis
import org.readium.r2.navigator.preferences.Fit

class ReadiumPdfPreferencesMapperTest {
    @Test
    fun mapsOnlyPubliclySupportedPdfLayoutPreferences() {
        val page = ReaderPdfPreferences(fit = ReaderPdfFit.Page).toReadiumPdfium()
        val width = ReaderPdfPreferences(fit = ReaderPdfFit.Width).toReadiumPdfium()

        assertEquals(Fit.CONTAIN, page.fit)
        assertEquals(Fit.WIDTH, width.fit)
        assertEquals(Axis.HORIZONTAL, page.scrollAxis)
    }
}
