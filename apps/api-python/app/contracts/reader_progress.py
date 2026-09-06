"""Shared Reader v5 presentation wire contract for Reader and Library HTTP."""

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt


class ReaderV5WireModel(BaseModel):
    # Readium locators and the client-owned projection are JSON transport
    # values.  Non-finite IEEE-754 values are not JSON and must be rejected at
    # the HTTP boundary, before the opaque mapper or persistence layer sees
    # them.
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        allow_inf_nan=False,
    )


class ReaderV5Chapter(ReaderV5WireModel):
    navigation_key: str | None = Field(alias="navigationKey", max_length=256)
    href: str | None = Field(max_length=8192)
    title: str | None = Field(max_length=4096)
    index: StrictInt | None = Field(ge=0)


class ReaderV5Page(ReaderV5WireModel):
    number: StrictInt = Field(ge=1)
    total: StrictInt | None = Field(ge=1)


class ReaderV5Playback(ReaderV5WireModel):
    position_millis: StrictInt = Field(alias="positionMillis", ge=0)
    duration_millis: StrictInt | None = Field(alias="durationMillis", ge=0)


class ReaderV5Presentation(ReaderV5WireModel):
    display_percent: StrictFloat = Field(alias="displayPercent", ge=0, le=100)
    total_progression: StrictFloat = Field(alias="totalProgression", ge=0, le=1)
    current_href: str | None = Field(alias="currentHref", max_length=8192)
    chapter: ReaderV5Chapter | None
    page: ReaderV5Page | None
    playback: ReaderV5Playback | None
