from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.core.config import Settings

DEFAULT_COVER_RELATIVE_PATH = Path("covers/default-book-cover-v1.png")
DEFAULT_COVER_ASSET_PATH = (
    Path(__file__).resolve().parent.parent / "assets/default-book-cover-v1.png"
)
DEFAULT_COVER_STATUS = "DEFAULT"


def default_cover_path(settings: Settings) -> Path:
    return settings.resolved_storage_root / DEFAULT_COVER_RELATIVE_PATH


def ensure_default_cover(settings: Settings) -> str:
    """Copy the bundled fallback cover into durable storage and return its path."""
    target = default_cover_path(settings)
    if (
        target.is_file()
        and target.stat().st_size == DEFAULT_COVER_ASSET_PATH.stat().st_size
    ):
        return str(DEFAULT_COVER_RELATIVE_PATH)

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=target.parent, prefix=".default-cover-", suffix=".png", delete=False
        ) as handle:
            temporary = Path(handle.name)
            with DEFAULT_COVER_ASSET_PATH.open("rb") as source:
                shutil.copyfileobj(source, handle)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(DEFAULT_COVER_RELATIVE_PATH)


def is_default_cover_path(value: object, settings: Settings | None = None) -> bool:
    if not value:
        return False
    candidate = Path(str(value))
    if candidate.as_posix() == DEFAULT_COVER_RELATIVE_PATH.as_posix():
        return True
    return settings is not None and candidate == default_cover_path(settings)


def cover_status(value: object, settings: Settings) -> str:
    return DEFAULT_COVER_STATUS if is_default_cover_path(value, settings) else "READY"
