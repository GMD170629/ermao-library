from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    qq: str = Field(default="", max_length=20, pattern=r"^\d*$")
    group_name: str = Field(default="", alias="groupName", max_length=100)
    email: str = Field(default="", max_length=254)


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_key: UUID = Field(alias="submissionKey")
    kind: Literal["suggestion", "issue"]
    markdown: str = Field(min_length=1, max_length=20_000)
    contact: Contact = Field(default_factory=Contact)
    diagnostics: dict[str, object] = Field(default_factory=dict)

    @field_validator("markdown")
    @classmethod
    def has_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description required")
        return value


class Receipt(BaseModel):
    id: str
    status: Literal["sent"] = "sent"
