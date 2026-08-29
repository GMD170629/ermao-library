package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderSpreadMode
import kotlin.test.assertEquals
import org.junit.Test

class AndroidReaderPreferencePolicyTest {
    @Test
    fun androidAlwaysProjectsReflowableAndComicPreferencesToSinglePage() {
        val requested = ReaderPreferences(
            epub = ReaderPreferences().epub.copy(spreadMode = ReaderSpreadMode.Double),
            comic = ReaderPreferences().comic.copy(spreadMode = ReaderComicSpreadMode.Double),
        )

        val supported = enforceAndroidSinglePagePreferences(requested)

        assertEquals(ReaderSpreadMode.Single, supported.epub.spreadMode)
        assertEquals(ReaderComicSpreadMode.Single, supported.comic.spreadMode)
    }
}
