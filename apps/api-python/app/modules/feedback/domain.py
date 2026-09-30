from __future__ import annotations

import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeedbackContact(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    qq: str = Field(default="", max_length=20, pattern=r"^\d*$")
    group_name: str = Field(default="", alias="groupName", max_length=100)
    email: str = Field(default="", max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if value and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("invalid email")
        return value


class ClientEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    client: Literal["web", "pwa"]
    user_agent: str = Field(alias="userAgent", min_length=1, max_length=2048)
    platform: str = Field(max_length=200)
    languages: list[str] = Field(max_length=10)
    locale: Literal["zh-CN", "en-US"]
    time_zone: str = Field(alias="timeZone", max_length=80)
    viewport: str = Field(max_length=30)
    screen: str = Field(max_length=30)
    device_pixel_ratio: float = Field(alias="devicePixelRatio", gt=0, le=16)
    color_depth: int = Field(alias="colorDepth", ge=1, le=64)
    page: str = Field(max_length=100)

    @field_validator("languages")
    @classmethod
    def valid_languages(cls, value: list[str]) -> list[str]:
        if any(not language or len(language) > 80 for language in value):
            raise ValueError("invalid browser language")
        return value


class FileDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    size: int = Field(ge=0, le=10 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class FeedbackDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    kind: Literal["suggestion", "issue"]
    markdown: str = Field(max_length=20_000)
    contact: FeedbackContact = Field(default_factory=FeedbackContact)
    include_environment: bool = Field(default=False, alias="includeEnvironment")
    installation_method: Literal["app-store", "manual", "docker"] | None = Field(default=None, alias="installationMethod")
    client_environment: ClientEnvironment | None = Field(default=None, alias="clientEnvironment")
    event_id: str | None = Field(default=None, alias="eventId", max_length=191)
    files: list[FileDescriptor] = Field(default_factory=list, max_length=5)

class FeedbackSubmitRequest(FeedbackDraft):
    submission_key: UUID = Field(alias="submissionKey")
    preview_hash: str = Field(alias="previewHash", pattern=r"^[a-f0-9]{64}$")

    @field_validator("markdown")
    @classmethod
    def substantive_markdown(cls, value: str) -> str:
        without_headings = re.sub(r"^#{1,6}\s+.*$", "", value, flags=re.MULTILINE)
        without_images = re.sub(r"!\[[^]]*\]\(upload:[^)]+\)", "", without_headings)
        if not without_images.strip(" \t\r\n*`->"):
            raise ValueError("description required")
        return value


class FeedbackEnvironment(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    app_version: str = Field(alias="appVersion")


class FeedbackEnvironmentDiagnostics(ClientEnvironment):
    app_version: str = Field(alias="appVersion")
    installation_method: str = Field(alias="installationMethod")


class FeedbackLogEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: str
    level: str
    source: str
    action: str
    message: str
    created_at: str = Field(alias="createdAt")
    stage: str
    exception_type: str = Field(alias="exceptionType")
    diagnostic_message: str = Field(alias="diagnosticMessage")
    traceback: str


class FeedbackRelatedBook(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str


class FeedbackLogDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    selected_event_id: str = Field(alias="selectedEventId")
    events: list[FeedbackLogEvent]
    related_books: list[FeedbackRelatedBook] = Field(alias="relatedBooks")


class FeedbackDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: FeedbackEnvironmentDiagnostics | None = None
    log: FeedbackLogDiagnostics | None = None


class FeedbackPreview(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    diagnostics: FeedbackDiagnostics
    preview_hash: str = Field(alias="previewHash")


class FeedbackReceipt(BaseModel):
    id: str
    status: Literal["sent"] = "sent"


def preview_hash(draft: FeedbackDraft, diagnostics: dict[str, object]) -> str:
    value = {"draft": draft.model_dump(mode="json", by_alias=True), "diagnostics": diagnostics}
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
