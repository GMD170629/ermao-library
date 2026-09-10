package com.ermao.library.shared.modules.administrativesettings.application

/** Values submitted atomically to the existing OPDS settings endpoint. */
data class OpdsEditValues(val enabled: Boolean, val publicBaseUrl: String)

/** Shared immediate-update workflow; native views own focus and render this immutable state. */
data class OpdsEditState(
    val confirmed: OpdsEditValues,
    val draft: OpdsEditValues = confirmed,
    val submission: OpdsEditValues? = null,
) {
    val isSubmitting: Boolean get() = submission != null

    fun editAddress(address: String): OpdsEditState =
        if (isSubmitting) this else copy(draft = draft.copy(publicBaseUrl = address))

    fun changeEnabled(enabled: Boolean): OpdsEditState =
        if (isSubmitting) this else copy(draft = draft.copy(enabled = enabled))

    fun beginSubmission(): OpdsEditState {
        val request = draft.copy(publicBaseUrl = draft.publicBaseUrl.trim())
        return if (isSubmitting || request == confirmed) this else copy(submission = request)
    }

    fun accept(enabled: Boolean, publicBaseUrl: String): OpdsEditState =
        OpdsEditState(OpdsEditValues(enabled, publicBaseUrl))

    fun reject(): OpdsEditState = copy(
        draft = draft.copy(enabled = confirmed.enabled),
        submission = null,
    )
}
