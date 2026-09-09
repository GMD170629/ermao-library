package com.ermao.library.shared.core.feedback

/** Semantic feedback shared by native presentation adapters; text is never a discriminator. */
enum class OperationFeedbackKind { Success, PartialSuccess, Failure, Action }

object OperationFeedbackPolicy {
    fun timeoutMillis(kind: OperationFeedbackKind, retainedTimeoutMillis: Long): Long =
        if (kind == OperationFeedbackKind.Success) 1_000L else retainedTimeoutMillis

    /** A success cannot erase a result that still needs attention. */
    fun canReplace(current: OperationFeedbackKind, incoming: OperationFeedbackKind): Boolean =
        current == OperationFeedbackKind.Success || incoming != OperationFeedbackKind.Success
}
