package com.ermao.library.features.reader.infrastructure

import androidx.fragment.app.Fragment
import com.ermao.library.features.reader.application.ReaderScreenController
import kotlinx.coroutines.CoroutineScope

internal interface AndroidReaderNavigatorSession : ReaderScreenController {
    suspend fun prepare(classLoader: ClassLoader): Fragment
    fun bind(scope: CoroutineScope)
    fun release()
}
