from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StorageLayout:
    root: Path

    @property
    def covers(self) -> Path:
        return self.root / "covers"

    @property
    def conversions(self) -> Path:
        return self.root / "conversions"

    @property
    def temp(self) -> Path:
        return self.root / "temp"

    @property
    def backups(self) -> Path:
        return self.root / "backups"

    @property
    def control(self) -> Path:
        return self.root / "control"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def secrets(self) -> Path:
        return self.root / "secrets"

    def ensure(self) -> None:
        for path in (
            self.covers,
            self.conversions,
            self.temp,
            self.backups,
            self.control,
            self.logs,
            self.secrets,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def resolve_inside(self, candidate: Path) -> Path:
        resolved = candidate.expanduser().resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError("path escapes appv2 storage root")
        return resolved
