package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderComicSpreadMode
import com.ermao.library.shared.modules.reader.ReaderPreferences

/** The current Android comic navigator renders one logical page at a time. */
internal fun enforceAndroidSinglePagePreferences(preferences: ReaderPreferences): ReaderPreferences =
    preferences.copy(
        comic = preferences.comic.copy(spreadMode = ReaderComicSpreadMode.Single),
    )
