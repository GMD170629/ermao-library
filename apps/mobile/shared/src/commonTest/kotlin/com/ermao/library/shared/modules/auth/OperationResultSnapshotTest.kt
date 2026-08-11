package com.ermao.library.shared.modules.auth

import com.ermao.library.shared.core.network.AppError
import com.ermao.library.shared.core.network.AppErrorKind
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class OperationResultSnapshotTest {
    @Test
    fun exposesStableFieldViolationsWithoutDiagnosticMessages() {
        val snapshot = RuntimeOperationResult.Failure(
            AppError(
                kind = AppErrorKind.Validation,
                code = "VALIDATION",
                diagnosticMessage = "backend localized message",
                fieldErrors = mapOf("email" to listOf("INVALID", "REQUIRED")),
                parameters = mapOf("minimum" to "10"),
            ),
        ).toSnapshot()

        assertFalse(snapshot.succeeded)
        assertEquals("Validation", snapshot.errorKind)
        assertEquals("VALIDATION", snapshot.errorCode)
        assertEquals(
            listOf(
                FieldViolationSnapshot("email", "INVALID"),
                FieldViolationSnapshot("email", "REQUIRED"),
            ),
            snapshot.fieldViolations,
        )
        assertEquals(mapOf("minimum" to "10"), snapshot.parameters)
    }
}
