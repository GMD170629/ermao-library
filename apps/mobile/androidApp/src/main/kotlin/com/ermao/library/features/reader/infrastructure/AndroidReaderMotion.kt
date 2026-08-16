package com.ermao.library.features.reader.infrastructure

import android.animation.ValueAnimator
import com.ermao.library.features.reader.application.shouldAnimateReaderNavigation
import com.ermao.library.shared.modules.reader.ReaderMorphology
import com.ermao.library.shared.modules.reader.ReaderPreferences

internal fun shouldAnimateAndroidReaderNavigation(
    preferences: ReaderPreferences,
    morphology: ReaderMorphology,
): Boolean = shouldAnimateReaderNavigation(
    preferences = preferences,
    morphology = morphology,
    systemAnimationsEnabled = ValueAnimator.areAnimatorsEnabled(),
)
