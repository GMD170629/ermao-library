from datetime import UTC, datetime

import pytest

from app.modules.library.application.metadata_effects import MetadataSideEffectPolicy
from app.modules.library.application.request_mutations import (
    ApplyBookMetadata,
    BookRecordMutation,
    BulkBookMutation,
    MetadataApplyMutation,
    UpdateBookRecord,
    UpdateBulkBooks,
)


class NoMutation:
    """Any gateway/UoW action means the preflight boundary failed."""

    def __getattr__(self, name):
        raise AssertionError(f"unexpected mutation: {name}")


@pytest.mark.parametrize(
    ("use_case", "command"),
    [
        (UpdateBookRecord, BookRecordMutation("book", {}, None, ("intent",))),
        (UpdateBulkBooks, BulkBookMutation((), writeback_intents=("intent",))),
        (
            ApplyBookMetadata,
            MetadataApplyMutation(
                "book", {}, (), None, ("intent",), (), datetime.now(UTC)
            ),
        ),
    ],
)
def test_database_only_commands_reject_prepared_file_effects_before_mutating(
    use_case, command
):
    boundary = NoMutation()
    with pytest.raises(ValueError, match="FILE_WRITEBACK_NOT_ALLOWED"):
        use_case(
            boundary,
            boundary,
            side_effect_policy=MetadataSideEffectPolicy.DATABASE_ONLY,
        ).execute(command)
