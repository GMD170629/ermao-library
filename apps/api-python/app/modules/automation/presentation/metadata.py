"""Strict MCP inputs for explicitly selected system metadata fields."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.automation.application.refresh import RefreshMetadataChange
from app.modules.library.public import MetadataChange, MetadataTarget
from app.modules.metadata.public import MetadataFileSource


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


class RefreshMetadataInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    target_type: MetadataTarget
    target_id: str = Field(min_length=1, max_length=191)
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    node_id: str = Field(min_length=1, max_length=191)
    source: MetadataFileSource
    fields: list[str] = Field(min_length=1, max_length=20)
    expected_file_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    mode: Literal["patch", "fill_missing"] = "fill_missing"
    override_fields: list[str] = Field(default_factory=list, max_length=20)
    sidecar_relative_path: str | None = Field(default=None, max_length=4096)

    def to_domain(self) -> RefreshMetadataChange:
        return RefreshMetadataChange(
            self.target_type,
            self.target_id,
            self.expected_revision,
            self.node_id,
            self.source,
            tuple(self.fields),
            self.expected_file_revision,
            self.mode,
            frozenset(self.override_fields),
            self.sidecar_relative_path,
        )
