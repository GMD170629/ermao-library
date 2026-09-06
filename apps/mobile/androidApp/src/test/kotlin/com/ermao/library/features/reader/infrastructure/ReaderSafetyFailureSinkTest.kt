package com.ermao.library.features.reader.infrastructure

import com.ermao.library.shared.modules.reader.ReaderSafetyException
import com.ermao.library.shared.modules.reader.domain.ReaderSafetyResourceRole
import com.ermao.library.shared.modules.reader.readerSafetyEpubArchiveIntegrityFailure
import com.ermao.library.shared.modules.reader.readerSafetyOptionalResourceFailure
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import org.junit.Test

class ReaderSafetyFailureSinkTest {
    @Test
    fun optionalResourceFailureStaysScopedToTheResource() {
        val sink = ReaderSafetyFailureSink()

        sink.record(ReaderSafetyException(readerSafetyOptionalResourceFailure()))

        assertDoesNotThrow { sink.throwIfPresent() }
    }

    @Test
    fun requiredIntegrityFailureRemainsTerminalForThePublicationSession() {
        val sink = ReaderSafetyFailureSink()

        sink.record(ReaderSafetyException(readerSafetyEpubArchiveIntegrityFailure()))

        assertFailsWith<ReaderSafetyException> { sink.throwIfPresent() }
        assertFailsWith<ReaderSafetyException> { sink.throwIfPresent() }
    }

    @Test
    fun contextualOptionalIntegrityFailureDoesNotRejectThePublication() {
        val sink = ReaderSafetyFailureSink()

        sink.record(
            ReaderSafetyException(readerSafetyEpubArchiveIntegrityFailure()),
            ReaderSafetyResourceRole.OPTIONAL_RESOURCE,
        )

        assertDoesNotThrow { sink.throwIfPresent() }
    }

    @Test
    fun implementationFailureRemainsTypedAfterOpening() {
        val sink = ReaderSafetyFailureSink()
        val failure = com.ermao.library.shared.modules.reader.ReaderSafetyImplementationException(
            com.ermao.library.shared.modules.reader.ReaderSafetyFacade()
                .engineFailureFor(com.ermao.library.shared.modules.reader.ReaderSafetyRuleId.REFLOWABLE_PREPARE_XML),
        )

        sink.record(failure)

        assertTrue(runCatching { sink.throwIfPresent() }.exceptionOrNull() === failure)
    }

    private fun assertDoesNotThrow(action: () -> Unit) {
        action()
    }
}
