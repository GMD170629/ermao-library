"""Page-zero extraction port; callers first resolve valid metadata artwork."""

from pathlib import Path
from typing import Protocol


class FirstPageCoverPort(Protocol):
    def extract(self, *, path: Path, source_format: str) -> bytes | None: ...
