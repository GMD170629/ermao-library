from __future__ import annotations


class OpdsError(Exception):
    """Base class for named OPDS application failures."""


class OpdsAuthenticationRequired(OpdsError):
    pass


class OpdsAuthenticationThrottled(OpdsError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("OPDS authentication throttled")
        self.retry_after_seconds = retry_after_seconds


class OpdsPublicationNotFound(OpdsError):
    pass


class OpdsProgressionInvalidPayload(OpdsError):
    pass


class OpdsProgressionIncorrectUser(OpdsError):
    pass


class OpdsProgressionLocked(OpdsError):
    pass


class OpdsProgressionDateConflict(OpdsError):
    pass
