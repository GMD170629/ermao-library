from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.opds.application.dto import (
    OpdsProgressionDeviceDto,
    OpdsProgressionDocumentDto,
)


class OpdsWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OpdsProgressionDevice(OpdsWireModel):
    id: str = Field(min_length=1, max_length=2048)
    name: str = Field(min_length=1, max_length=256)

    @field_validator("id")
    @classmethod
    def require_uri(cls, value: str) -> str:
        if not urlsplit(value).scheme:
            raise ValueError("device id must be a URI")
        return value


class OpdsProgressionDocument(OpdsWireModel):
    title: str | None = Field(default=None, max_length=500)
    modified: datetime
    device: OpdsProgressionDevice
    progression: float = Field(ge=0, le=1)
    references: list[str] | None = Field(default=None, max_length=16)

    @field_validator("modified")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("modified must include a timezone")
        return value

    @field_validator("references")
    @classmethod
    def validate_references(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(not reference or len(reference) > 4096 for reference in value):
            raise ValueError("references must contain non-empty URI references")
        return value

    def to_dto(self) -> OpdsProgressionDocumentDto:
        return OpdsProgressionDocumentDto(
            title=self.title,
            modified=self.modified,
            device=OpdsProgressionDeviceDto(
                id=self.device.id,
                name=self.device.name,
            ),
            progression=self.progression,
            references=tuple(self.references) if self.references is not None else None,
        )

    @classmethod
    def from_dto(cls, document: OpdsProgressionDocumentDto) -> OpdsProgressionDocument:
        return cls(
            title=document.title,
            modified=document.modified,
            device=OpdsProgressionDevice(
                id=document.device.id,
                name=document.device.name,
            ),
            progression=document.progression,
            references=list(document.references)
            if document.references is not None
            else None,
        )


class OpdsAuthenticationLabels(OpdsWireModel):
    login: str
    password: str


class OpdsAuthenticationFlow(OpdsWireModel):
    type: Literal["http://opds-spec.org/auth/basic"] = "http://opds-spec.org/auth/basic"
    labels: OpdsAuthenticationLabels


class OpdsAuthenticationDocument(OpdsWireModel):
    id: str
    title: str
    description: str | None = None
    authentication: list[OpdsAuthenticationFlow]


class OpdsProblemDetails(OpdsWireModel):
    type: str
    title: str
