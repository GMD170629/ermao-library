from __future__ import annotations

from typing import Protocol

from app.modules.opds.application.dto import (
    OpdsActorDto,
    OpdsAuthenticationRequestDto,
    OpdsCatalogQueryDto,
    OpdsFeedDto,
)


class OpdsAuthenticator(Protocol):
    def authenticate(
        self, request: OpdsAuthenticationRequestDto
    ) -> OpdsActorDto | None: ...


class OpdsCatalogPort(Protocol):
    def load_feed(self, query: OpdsCatalogQueryDto) -> OpdsFeedDto: ...
