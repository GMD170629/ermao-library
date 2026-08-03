"""Enable newly admitted audiobook extensions in existing import preferences.

Revision ID: 0008_audiobook_audio_formats
Revises: 0007_media_versions_contract
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_audiobook_audio_formats"
down_revision: str | Sequence[str] | None = "0007_media_versions_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SETTING_KEY = "import.allowedExtensions"
NEW_AUDIO_EXTENSIONS = (
    ".aac",
    ".ac3",
    ".adx",
    ".aif",
    ".aifc",
    ".aiff",
    ".amr",
    ".ape",
    ".aptx",
    ".aptxhd",
    ".au",
    ".caf",
    ".dff",
    ".dsf",
    ".dts",
    ".eac3",
    ".flac",
    ".g722",
    ".g726",
    ".gsm",
    ".lbc",
    ".m4r",
    ".mka",
    ".mlp",
    ".mp2",
    ".mpc",
    ".oga",
    ".ogg",
    ".oma",
    ".opus",
    ".qcp",
    ".ra",
    ".rf64",
    ".shn",
    ".snd",
    ".sph",
    ".spx",
    ".tak",
    ".thd",
    ".tta",
    ".voc",
    ".w64",
    ".wav",
    ".wave",
    ".weba",
    ".wma",
    ".wv",
    ".xma",
)


def _settings_table() -> sa.Table:
    return sa.Table("SystemSetting", sa.MetaData(), autoload_with=op.get_bind())


def _stored_extensions(settings: sa.Table) -> list[str] | None:
    raw = op.get_bind().scalar(
        sa.select(settings.c.value).where(settings.c.key == SETTING_KEY)
    )
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, list):
        return None
    return [str(item) for item in value]


def _write_extensions(settings: sa.Table, extensions: list[str]) -> None:
    op.get_bind().execute(
        sa.update(settings)
        .where(settings.c.key == SETTING_KEY)
        .values(
            value=json.dumps(extensions, ensure_ascii=False, separators=(",", ":")),
            updatedAt=sa.func.unixepoch() * 1000,
        )
    )


def upgrade() -> None:
    settings = _settings_table()
    existing = _stored_extensions(settings)
    if existing is None:
        return
    normalized = {extension.lower() for extension in existing}
    additions = [
        extension for extension in NEW_AUDIO_EXTENSIONS if extension not in normalized
    ]
    if additions:
        _write_extensions(settings, [*existing, *additions])


def downgrade() -> None:
    settings = _settings_table()
    existing = _stored_extensions(settings)
    if existing is None:
        return
    additions = set(NEW_AUDIO_EXTENSIONS)
    retained = [
        extension for extension in existing if extension.lower() not in additions
    ]
    if retained != existing:
        _write_extensions(settings, retained)
