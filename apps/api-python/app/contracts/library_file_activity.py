"""Stable signal for a file mutation winning a queue-claim race."""


class LibraryFileActivityBusy(RuntimeError):
    """Defer the unstarted task; no filesystem action has occurred."""
