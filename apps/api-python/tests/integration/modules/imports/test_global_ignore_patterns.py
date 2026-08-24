from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.modules.imports.domain.ignore_rules import IMPORT_IGNORE_PATTERNS_KEY
from app.modules.imports.infrastructure.readable_resource.global_ignore_patterns import (
    load_global_ignore_patterns,
)


def test_global_ignore_patterns_are_loaded_and_normalized(
    db_session: Session,
) -> None:
    db_session.add(
        SystemSetting(
            key=IMPORT_IGNORE_PATTERNS_KEY,
            value=json.dumps("  *.tmp\r\n\r\n**/cache/**  "),
        )
    )
    db_session.flush()

    assert load_global_ignore_patterns(db_session) == "*.tmp\n**/cache/**"
