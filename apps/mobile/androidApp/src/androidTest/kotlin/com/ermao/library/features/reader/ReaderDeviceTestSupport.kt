package com.ermao.library.features.reader

import android.view.WindowManager
import androidx.test.core.app.ActivityScenario
import com.ermao.library.features.reader.presentation.ReaderActivity

/** Keeps synthetic Reader fixtures testable on unattended physical devices. */
internal fun ActivityScenario<ReaderActivity>.keepReaderTestFixtureVisible() {
    onActivity { activity ->
        activity.setShowWhenLocked(true)
        activity.setTurnScreenOn(true)
        activity.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }
}
