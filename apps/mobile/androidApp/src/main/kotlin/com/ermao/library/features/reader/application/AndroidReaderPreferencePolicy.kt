package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.ReaderPreferences
import com.ermao.library.shared.modules.reader.ReaderSpreadMode

/** Android phone readers always render one logical page at a time. */
internal fun enforceAndroidSinglePagePreferences(preferences: ReaderPreferences): ReaderPreferences =
    preferences.copy(
        epub = preferences.epub.copy(spreadMode = ReaderSpreadMode.Single),
        comic = preferences.comic.copy(spreadMode = ReaderComicSpreadMode.Single),
    )
