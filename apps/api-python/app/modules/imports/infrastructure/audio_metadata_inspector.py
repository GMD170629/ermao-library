"""Audio inspection adapter backed by Mutagen and ffprobe."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.audio_types import AudioFileMetadata
from app.services.audio_metadata import parse_audio_metadata


class MutagenFfprobeAudioMetadataInspector:
    def inspect(self, path: Path) -> AudioFileMetadata:
        return parse_audio_metadata(path)


__all__ = ["MutagenFfprobeAudioMetadataInspector"]
