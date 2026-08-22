"""Authenticated Readium Web publication distribution."""

from __future__ import annotations

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.publications import (
    ensure_publication_navigation,
    open_publication,
)
from app.contracts.http import MessageError
from app.contracts.http_errors import (
    BasicNotFoundError,
    BasicUnauthorizedError,
    ErrorResponses,
)
from app.core.authorization import authorization_context
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.publications.application.ports import PublicationAccessScope
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationResourceNotFoundError,
    PublicationUnsupportedError,
)
from app.modules.publications.domain.model import (
    PublicationLink as DomainPublicationLink,
)
from app.modules.publications.domain.model import (
    PublicationTocEntry as DomainPublicationTocEntry,
)
from app.modules.publications.infrastructure.locator_dom import WEB_SECURITY_PROFILE
from app.modules.publications.presentation.schemas import (
    PositionLocations,
    PublicationLink,
    PublicationManifest,
    PublicationMetadata,
    PublicationPosition,
    PublicationPositions,
    PublicationResourceResponse,
    PublicationRuntimeMetadata,
    PublicationTocEntry,
)

router = APIRouter(
    prefix="/reader/v4/resources/{resource_id}/publication",
    tags=["reader-v4-publication"],
    route_class=TypedContractRoute,
)
DatabaseSession = Annotated[Session, Depends(get_db)]
ApplicationSettings = Annotated[Settings, Depends(get_settings)]
PUBLICATION_ERROR_RESPONSES = ErrorResponses(
    BasicUnauthorizedError,
    BasicNotFoundError,
)
_EPUB_PROFILE = "https://readium.org/webpub-manifest/profiles/epub"
_MANIFEST_MEDIA_TYPE = "application/webpub+json"
_POSITIONS_MEDIA_TYPE = "application/vnd.readium.position-list+json"
_ACTIVE_CONTENT_CSP = WEB_SECURITY_PROFILE.content_security_policy


def _access_scope(db: Session, user: User) -> PublicationAccessScope:
    actor = authorization_context(db, user)
    return PublicationAccessScope(
        is_admin=actor.is_admin,
        can_view_manual_imports=actor.can_view_manual_imports,
        library_ids=tuple(actor.library_ids),
    )


def _authenticated_scope(
    db: Session,
    request: Request,
    settings: Settings,
) -> tuple[User, PublicationAccessScope]:
    user, auth_error = require_user(db, request, settings)
    if auth_error is not None or user is None:
        raise BasicUnauthorizedError(
            MessageError(message="未登录", code="UNAUTHORIZED")
        )
    return user, _access_scope(db, user)


def _not_found() -> BasicNotFoundError:
    return BasicNotFoundError(
        MessageError(message="出版物不存在或不可用", code="PUBLICATION_NOT_FOUND")
    )


def _runtime_session_factory(request: Request) -> sessionmaker[Session]:
    factory: object = request.app.state.session_factory
    if not isinstance(factory, sessionmaker):
        raise TypeError("application session factory is unavailable")
    return cast(sessionmaker[Session], factory)


def _open_manifest_publication(
    *,
    resource_id: str,
    request: Request,
    settings: Settings,
    scope: PublicationAccessScope,
) -> NormalizedPublication:
    return (
        ensure_publication_navigation(
            _runtime_session_factory(request),
            settings,
        )
        .open_and_ensure(
            resource_id=resource_id,
            access_scope=scope,
        )
        .publication
    )


def _manifest(publication: NormalizedPublication) -> PublicationManifest:
    def link(value: DomainPublicationLink) -> PublicationLink:
        return PublicationLink(
            href=value.href,
            type=value.media_type,
            title=value.title,
            rel=list(value.rel) or None,
        )

    def toc(value: DomainPublicationTocEntry) -> PublicationTocEntry:
        return PublicationTocEntry(
            href=value.href,
            title=value.title,
            children=[toc(child) for child in value.children] or None,
        )

    return PublicationManifest.model_validate(
        {
            "metadata": PublicationMetadata(
                identifier=publication.identifier,
                title=publication.title,
                author=publication.author,
                language=publication.language,
                conformsTo=[_EPUB_PROFILE],
                readingProgression=cast(
                    Literal["ltr", "rtl"], publication.reading_progression
                ),
            ),
            "links": [
                PublicationLink(
                    href="manifest.json", type=_MANIFEST_MEDIA_TYPE, rel=["self"]
                ),
                PublicationLink(
                    href="positions.json", type=_POSITIONS_MEDIA_TYPE, rel=["positions"]
                ),
            ],
            "readingOrder": [link(value) for value in publication.reading_order],
            "resources": [link(value) for value in publication.resources],
            "toc": [toc(value) for value in publication.toc],
            "runtime": PublicationRuntimeMetadata(
                sourceSizeBytes=publication.revision.source_size_bytes,
                sourceMtimeMs=publication.revision.source_mtime_ms,
                parser=publication.revision.parser,
                normalization=publication.revision.normalization,
            ),
        }
    )


@router.get(
    "/manifest.json",
    response_model=PublicationManifest,
    response_model_by_alias=True,
    response_model_exclude_none=True,
)
def publication_manifest(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[PublicationManifest, PUBLICATION_ERROR_RESPONSES]:
    _user, scope = _authenticated_scope(db, request, settings)
    try:
        publication = _open_manifest_publication(
            resource_id=resource_id,
            request=request,
            settings=settings,
            scope=scope,
        )
    except (
        PublicationNotFoundError,
        PublicationUnsupportedError,
        PublicationCorruptError,
    ) as error:
        raise _not_found() from error
    return _manifest(publication)


@router.get(
    "/positions.json",
    response_model=PublicationPositions,
    response_model_by_alias=True,
)
def publication_positions(
    resource_id: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[PublicationPositions, PUBLICATION_ERROR_RESPONSES]:
    _user, scope = _authenticated_scope(db, request, settings)
    try:
        publication = _open_manifest_publication(
            resource_id=resource_id,
            request=request,
            settings=settings,
            scope=scope,
        )
    except (
        PublicationNotFoundError,
        PublicationUnsupportedError,
        PublicationCorruptError,
    ) as error:
        raise _not_found() from error
    total = len(publication.reading_order)
    positions = [
        PublicationPosition(
            href=link.href,
            type=link.media_type,
            locations=PositionLocations(
                position=index + 1,
                progression=0,
                totalProgression=0 if total == 1 else index / (total - 1),
            ),
        )
        for index, link in enumerate(publication.reading_order)
    ]
    return PublicationPositions(total=total, positions=positions)


@router.get("/{resource_href:path}", response_class=PublicationResourceResponse)
@router.head("/{resource_href:path}", response_class=PublicationResourceResponse)
def publication_resource(
    resource_id: str,
    resource_href: str,
    request: Request,
    db: DatabaseSession,
    settings: ApplicationSettings,
) -> Annotated[Response, PUBLICATION_ERROR_RESPONSES]:
    _user, scope = _authenticated_scope(db, request, settings)
    try:
        resource = open_publication(db, settings).resource(
            resource_id=resource_id,
            href=resource_href,
            access_scope=scope,
        )
        content = resource.content
    except (
        PublicationNotFoundError,
        PublicationUnsupportedError,
        PublicationCorruptError,
        PublicationResourceNotFoundError,
    ) as error:
        raise _not_found() from error
    headers = {
        "Cache-Control": "private, no-cache",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
    }
    if resource.media_type in {"application/xhtml+xml", "text/html"}:
        headers["Content-Security-Policy"] = _ACTIVE_CONTENT_CSP
    response_content = b"" if request.method == "HEAD" else content
    headers["Content-Length"] = str(len(content))
    return Response(
        content=response_content,
        media_type=resource.media_type,
        headers=headers,
    )
