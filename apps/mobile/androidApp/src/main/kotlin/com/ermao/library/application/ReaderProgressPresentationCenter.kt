package com.ermao.library.application

import com.ermao.library.shared.modules.reader.ReaderProgressPresentationUpdate
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow

/** App-scoped bridge from the Reader capability to currently visible content projections. */
class ReaderProgressPresentationCenter {
    private val mutableUpdates = MutableSharedFlow<ReaderProgressPresentationUpdate>(
        extraBufferCapacity = 32,
    )

    val updates: SharedFlow<ReaderProgressPresentationUpdate> = mutableUpdates.asSharedFlow()

    fun publish(update: ReaderProgressPresentationUpdate) {
        mutableUpdates.tryEmit(update)
    }
}
