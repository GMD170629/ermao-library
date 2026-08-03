from __future__ import annotations

from typing import Protocol

from app.modules.opds.application.dto import (
    BasicCredentialsDto,
    OpdsActorDto,
    OpdsCatalogQueryDto,
    OpdsFeedDto,
    OpdsProgressionDocumentDto,
    OpdsProgressionUpdateResultDto,
)


class OpdsAuthenticator(Protocol):
    def authenticate(
        self, credentials: BasicCredentialsDto, client_address: str
    ) -> OpdsActorDto | None: ...


class OpdsCatalogPort(Protocol):
    def load_feed(self, query: OpdsCatalogQueryDto) -> OpdsFeedDto: ...


class OpdsProgressionPort(Protocol):
    def get_progression(
        self, actor_id: str, volume_id: str
    ) -> OpdsProgressionDocumentDto | None: ...

    def update_progression(
        self,
        actor_id: str,
        volume_id: str,
        document: OpdsProgressionDocumentDto,
    ) -> OpdsProgressionUpdateResultDto: ...
