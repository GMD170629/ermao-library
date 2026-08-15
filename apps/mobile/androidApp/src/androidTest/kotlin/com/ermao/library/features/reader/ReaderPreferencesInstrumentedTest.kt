package com.ermao.library.features.reader

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ermao.library.features.reader.infrastructure.AndroidReaderPreferencesStore
import com.ermao.library.shared.modules.reader.ReaderEpubPreferences
import com.ermao.library.shared.modules.reader.ReaderPdfFit
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderTheme
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ReaderPreferencesInstrumentedTest {
    @Test
    fun preferencesSurviveStoreRecreationAndRemainAccountScoped() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val suffix = UUID.randomUUID().toString()
        val stored = ReaderPreferences(
            appearance = ReaderPreferences().appearance.copy(theme = ReaderTheme.Green),
            epub = ReaderEpubPreferences(fontSize = 22, lineHeight = 2.2),
            pdf = ReaderPreferences().pdf.copy(fit = ReaderPdfFit.Width),
        )

        AndroidReaderPreferencesStore(context, "server-$suffix", "user-a").save(stored)

        assertEquals(
            stored,
            AndroidReaderPreferencesStore(context, "server-$suffix", "user-a").load(),
        )
        assertEquals(
            ReaderPreferences(),
            AndroidReaderPreferencesStore(context, "server-$suffix", "user-b").load(),
        )
    }
}
