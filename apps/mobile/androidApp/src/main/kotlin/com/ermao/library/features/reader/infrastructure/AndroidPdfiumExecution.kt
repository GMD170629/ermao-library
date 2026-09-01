package com.ermao.library.features.reader.infrastructure

import java.util.concurrent.Executors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.async
import kotlinx.coroutines.withContext

/**
 * Process-lifetime executor for PDFium. PDFium is not thread-safe, and every
 * native call must be ordered without ever occupying Android's main thread.
 */
internal object AndroidPdfiumExecution {
    private val executor = Executors.newSingleThreadExecutor { operation ->
        Thread(operation, "ermao-pdfium").apply { isDaemon = true }
    }
    private val dispatcher = executor.asCoroutineDispatcher()
    private val scope = CoroutineScope(SupervisorJob() + dispatcher)

    suspend fun <T> call(operation: () -> T): T = withContext(dispatcher) { operation() }

    fun submit(operation: suspend () -> Unit): Deferred<Unit> = scope.async { operation() }
}
