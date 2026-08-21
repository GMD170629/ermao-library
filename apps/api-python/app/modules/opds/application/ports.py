from __future__ import annotations

from typing import Protocol

from app.modules.opds.application.dto import (
    OpdsActorDto,
    OpdsAuthenticationRequestDto,
    OpdsCatalogQueryDto,
    OpdsFeedDto,
    OpdsProgressionDocumentDto,
    OpdsProgressionUpdateResultDto,
)


class OpdsAuthenticator(Protocol):
    def authenticate(self, request: OpdsAuthenticationRequestDto) -> OpdsActorDto | None: ...


class OpdsCatalogPort(Protocol):
    def load_feed(self, query: OpdsCatalogQueryDto) -> OpdsFeedDto: ...


class OpdsProgressionPort(Protocol):
    def get_progression(
        self, actor_id: str, resource_id: str
    ) -> OpdsProgressionDocumentDto | None: ...

    def update_progression(
        self,
        actor_id: str,
        resource_id: str,
        document: OpdsProgressionDocumentDto,
    ) -> OpdsProgressionUpdateResultDto: ...
