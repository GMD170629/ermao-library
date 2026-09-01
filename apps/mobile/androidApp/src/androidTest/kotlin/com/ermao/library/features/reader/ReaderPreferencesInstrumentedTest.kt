package com.ermao.library.features.reader

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.infrastructure.AndroidReaderPreferencesStore
import com.ermao.library.features.reader.infrastructure.ReadiumPreferencesMapper
import com.ermao.library.shared.modules.reader.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.ReaderPdfFit
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderSpreadMode
import com.ermao.library.shared.modules.reader.ReaderTheme
import com.ermao.library.shared.modules.reader.ReaderReadingMode
import com.ermao.library.shared.modules.reader.ReaderReadingProgression
import com.ermao.library.shared.modules.reader.ReaderWritingMode
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.readium.r2.shared.ExperimentalReadiumApi
import org.readium.r2.navigator.preferences.ReadingProgression

@OptIn(ExperimentalReadiumApi::class)
@RunWith(AndroidJUnit4::class)
class ReaderPreferencesInstrumentedTest {
    @Test
    fun preferencesSurviveStoreRecreationAndRemainAccountScoped() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val suffix = UUID.randomUUID().toString()
        val stored = ReaderPreferences(
            appearance = ReaderPreferences().appearance.copy(theme = ReaderTheme.Green),
            epub = ReaderEpubPreferences(
                fontSize = 22,
                lineHeight = 2.2,
                spreadMode = ReaderSpreadMode.Double,
            ),
            comic = ReaderPreferences().comic.copy(spreadMode = ReaderComicSpreadMode.Double),
            pdf = ReaderPreferences().pdf.copy(fit = ReaderPdfFit.Width),
        )
        val supported = stored.copy(
            comic = stored.comic.copy(spreadMode = ReaderComicSpreadMode.Single),
        )

        AndroidReaderPreferencesStore(context, "server-$suffix", "user-a").save(stored)

        assertEquals(
            supported,
            AndroidReaderPreferencesStore(context, "server-$suffix", "user-a").load(),
        )
        assertEquals(
            ReaderPreferences(),
            AndroidReaderPreferencesStore(context, "server-$suffix", "user-b").load(),
        )
    }

    @Test
    fun readingProgressionAndWritingModeIndependentlyControlReadium() {
        val resources = InstrumentationRegistry.getInstrumentation().targetContext.resources
        val mapper = ReadiumPreferencesMapper(resources)
        val stored = ReaderPreferences(epub = ReaderEpubPreferences(
            readingProgression = ReaderReadingProgression.RightToLeft,
            writingMode = ReaderWritingMode.Horizontal,
            flow = ReaderReadingMode.Paged,
            spreadMode = ReaderSpreadMode.Double,
        ))
        val horizontal = mapper.toReadium(stored, supportsTextLayout = true)
        assertEquals(ReadingProgression.RTL, horizontal.readingProgression)
        assertEquals(false, horizontal.verticalText)
        assertEquals(false, horizontal.scroll)

        val verticalPreferences = stored.copy(epub = stored.epub.copy(
            readingProgression = ReaderReadingProgression.LeftToRight,
            writingMode = ReaderWritingMode.Vertical,
        ))
        val vertical = mapper.toReadium(verticalPreferences, supportsTextLayout = true)
        assertEquals(ReadingProgression.LTR, vertical.readingProgression)
        assertEquals(true, vertical.verticalText)
        assertEquals(true, vertical.scroll)

        val fixed = mapper.toReadium(verticalPreferences, supportsTextLayout = false)
        assertEquals(null, fixed.readingProgression)
        assertEquals(null, fixed.verticalText)
        assertEquals(false, fixed.scroll)
    }
}
