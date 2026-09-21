"""Trusted caller policy for metadata mutations, never a model-supplied switch."""

from enum import StrEnum


class MetadataSideEffectPolicy(StrEnum):
    CONFIGURED_WRITEBACK = "configured_writeback"
    DATABASE_ONLY = "database_only"


def validate_writeback_intents(
    policy: MetadataSideEffectPolicy, intents: tuple[object, ...]
) -> None:
    if policy is MetadataSideEffectPolicy.DATABASE_ONLY and intents:
        raise ValueError("FILE_WRITEBACK_NOT_ALLOWED")
