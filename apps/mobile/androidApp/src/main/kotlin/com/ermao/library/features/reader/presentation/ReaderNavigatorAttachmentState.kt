package com.ermao.library.features.reader.presentation

/** Coordinates the independently-timed Reader session preparation and navigator container. */
internal class ReaderNavigatorAttachmentState<Session : Any, Navigator : Any> {
    internal data class Prepared<Session : Any, Navigator : Any>(
        val session: Session,
        val navigator: Navigator,
    )

    private sealed interface Phase<out Session : Any, out Navigator : Any> {
        data object Idle : Phase<Nothing, Nothing>
        data class Prepared<Session : Any, Navigator : Any>(
            val value: ReaderNavigatorAttachmentState.Prepared<Session, Navigator>,
        ) : Phase<Session, Navigator>
        data class Attaching<Session : Any, Navigator : Any>(
            val value: ReaderNavigatorAttachmentState.Prepared<Session, Navigator>,
        ) : Phase<Session, Navigator>
        data class Bound<Session : Any>(val session: Session) : Phase<Session, Nothing>
    }

    private var containerReady = false
    private var phase: Phase<Session, Navigator> = Phase.Idle

    fun markContainerReady() {
        containerReady = true
    }

    fun markContainerUnavailable() {
        containerReady = false
    }

    /** Publishes only a navigator prepared by the session which is still current. */
    fun publish(
        currentSession: Session?,
        preparedSession: Session,
        navigator: Navigator,
    ): Boolean {
        if (currentSession !== preparedSession) return false
        check((phase as? Phase.Bound)?.session !== preparedSession) {
            "Reader navigator session is already bound"
        }
        phase = Phase.Prepared(Prepared(preparedSession, navigator))
        return true
    }

    /** Claims a ready pair before Fragment attachment so reentrant callbacks cannot bind twice. */
    fun claim(currentSession: Session?, fragmentStateSaved: Boolean): Prepared<Session, Navigator>? {
        if (!containerReady || fragmentStateSaved || currentSession == null) return null
        val prepared = (phase as? Phase.Prepared)?.value ?: return null
        if (prepared.session !== currentSession) return null
        phase = Phase.Attaching(prepared)
        return prepared
    }

    fun markBound(prepared: Prepared<Session, Navigator>) {
        val attaching = (phase as? Phase.Attaching)?.value
        check(attaching === prepared) { "Reader navigator attachment was not claimed" }
        phase = Phase.Bound(prepared.session)
    }

    fun discard(session: Session) {
        val owner = when (val current = phase) {
            Phase.Idle -> null
            is Phase.Prepared -> current.value.session
            is Phase.Attaching -> current.value.session
            is Phase.Bound -> current.session
        }
        if (owner === session) phase = Phase.Idle
    }

    /** Starts another Reader session without changing the physical container readiness. */
    fun resetSession() {
        phase = Phase.Idle
    }
}
