"""Strict MCP inputs for explicitly selected system metadata fields."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.library.public import MetadataChange, MetadataTarget


class MetadataChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_type: MetadataTarget
    target_id: str = Field(min_length=1, max_length=191)
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    mode: Literal["patch", "fill_missing"] = "patch"
    fields: dict[str, str | float | bool | list[str] | None] = Field(
        default_factory=dict, max_length=20
    )
    clear_fields: list[str] = Field(default_factory=list, max_length=20)
    override_fields: list[str] = Field(default_factory=list, max_length=20)

    def to_domain(self) -> MetadataChange:
        return MetadataChange(
            self.target_type,
            self.target_id,
            self.expected_revision,
            self.mode,
            {
                key: tuple(value) if isinstance(value, list) else value
                for key, value in self.fields.items()
            },
            frozenset(self.clear_fields),
            frozenset(self.override_fields),
        )
