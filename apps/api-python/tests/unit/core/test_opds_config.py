import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_opds_page_size_cannot_exceed_maximum() -> None:
    with pytest.raises(ValidationError):
        Settings(
            session_secret="test-secret",
            opds_page_size=100,
            opds_max_page_size=50,
        )
