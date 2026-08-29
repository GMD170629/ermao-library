package com.ermao.library.features.reader.infrastructure

import androidx.fragment.app.Fragment
import com.ermao.library.features.reader.application.ReaderScreenController
import com.ermao.library.shared.modules.reader.ReaderError
import com.ermao.library.shared.modules.reader.ReaderErrorCode
import java.util.logging.Level
import java.util.logging.Logger
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow

internal interface AndroidReaderNavigatorSession : ReaderScreenController {
    suspend fun prepare(classLoader: ClassLoader): Fragment
    fun bind(scope: CoroutineScope)
    fun release()
}

internal fun publishReaderRestoreWarning(
    state: MutableStateFlow<ReaderError?>,
    format: String,
    stage: String,
    cause: Exception? = null,
) {
    Logger.getLogger("MobileReader").log(
        Level.WARNING,
        "reader_restore_fallback platform=android format=$format stage=$stage",
        cause,
    )
    state.value = ReaderError(ReaderErrorCode.LocationRestoreFailed)
}
