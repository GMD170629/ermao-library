package com.ermao.library.features.reader.application

import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderPageTurnAnimation
import com.ermao.library.shared.modules.reader.ReaderPreferences

internal fun shouldAnimateReaderNavigation(
    preferences: ReaderPreferences,
    morphology: ReaderMorphology,
    systemAnimationsEnabled: Boolean,
): Boolean {
    if (!systemAnimationsEnabled) return false
    return when (morphology) {
        ReaderMorphology.Reflowable -> preferences.epub.pageTurnAnimation == ReaderPageTurnAnimation.Slide
        ReaderMorphology.Comic -> preferences.comic.pageTurnAnimation == ReaderPageTurnAnimation.Slide
        ReaderMorphology.Pdf -> true
    }
}
