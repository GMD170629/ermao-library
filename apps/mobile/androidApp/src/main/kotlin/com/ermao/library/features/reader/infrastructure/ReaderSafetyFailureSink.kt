package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.ReaderSafetyImplementationException
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyResourceRole
import com.ermao.library.shared.modules.reader.readerSafetyEvaluateRuleDecision
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/** Keeps a typed safety failure attached to one Readium opening, including lazy resource reads. */
internal class ReaderSafetyFailureSink {
    private val firstFailure = AtomicReference<Throwable?>(null)
    private val disposed = AtomicBoolean(false)

    fun record(
        error: Throwable,
        resourceRole: ReaderSafetyResourceRole = ReaderSafetyResourceRole.CONTROL_DOCUMENT,
    ) {
        if (disposed.get()) return
        when (error) {
            is ReaderSafetyImplementationException -> firstFailure.compareAndSet(null, error)
            is ReaderSafetyException -> {
                val decision = runCatching {
                    readerSafetyEvaluateRuleDecision(
                        format = "EPUB",
                        resourceRole = resourceRole.name,
                        ruleId = error.failure.ruleId,
                        enforcementAvailable = true,
                        canIsolate = false,
                    )
                }.getOrElse {
                    firstFailure.compareAndSet(null, error)
                    return
                }
                // BLOCK_RESOURCE is returned by the protected resource and remains scoped to
                // that read. Only the contextual generated publication action may fail opening.
                if (decision.action != "BLOCK_RESOURCE") {
                    firstFailure.compareAndSet(null, error)
                }
            }
        }
    }

    fun throwIfPresent() {
        when (val error = firstFailure.get()) {
            is ReaderSafetyException -> throw error
            is ReaderSafetyImplementationException -> throw error
        }
    }

    fun clear() {
        disposed.set(true)
        firstFailure.set(null)
    }
}
