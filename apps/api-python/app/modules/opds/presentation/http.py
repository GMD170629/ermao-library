from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Body, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.modules.opds.application.dto import OpdsCatalogQueryDto, PsePageRequestDto
from app.modules.opds.application.ports import (
    OpdsAuthenticator,
    OpdsCatalogPort,
    OpdsProgressionPort,
)
from app.modules.opds.application.settings import OpdsSettingsSnapshot
from app.modules.opds.domain.errors import (
    OpdsAuthenticationRequired,
    OpdsAuthenticationThrottled,
    OpdsProgressionDateConflict,
    OpdsProgressionIncorrectUser,
    OpdsProgressionInvalidPayload,
    OpdsProgressionLocked,
    OpdsPublicationNotFound,
)
from app.modules.opds.presentation.atom import CATALOG_MEDIA_TYPE, serialize_opds_feed
from app.modules.opds.presentation.auth import parse_basic_authorization
from app.modules.opds.presentation.opensearch import serialize_opensearch_description
from app.modules.opds.presentation.schemas import (
    OpdsAuthenticationDocument,
    OpdsAuthenticationFlow,
    OpdsAuthenticationLabels,
    OpdsProblemDetails,
    OpdsProgressionDocument,
)

PROGRESSION_MEDIA_TYPE = "application/opds-progression+json"


class OpdsProtocolResponse(Response):
    """OpenAPI-neutral default for routes that negotiate OPDS media types."""

    media_type = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class OpdsHttpDependencies:
    settings: Callable[[], OpdsSettingsSnapshot]
    authenticator: OpdsAuthenticator
    catalog: OpdsCatalogPort
    progression: OpdsProgressionPort
    default_page_size: int = 50
    max_page_size: int = 100
    work_cover: Callable[[str, str, Request], Response] | None = None
    volume_cover: Callable[[str, str, Request], Response] | None = None
    volume_file: Callable[[str, str, Request], Response] | None = None
    volume_page: Callable[[str, PsePageRequestDto, Request], Response] | None = None


def authentication_required_response(
    document: OpdsAuthenticationDocument,
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content=document.model_dump(mode="json", exclude_none=True),
        media_type="application/opds-authentication+json",
        headers={
            "WWW-Authenticate": 'Basic realm="Shuku OPDS", charset="UTF-8"',
            "Link": '</opds/authentication.json>; rel="http://opds-spec.org/auth/document"; type="application/opds-authentication+json"',
            "Cache-Control": "no-store",
            "Vary": "Authorization",
        },
    )


def authentication_throttled_response(retry_after_seconds: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "type": "https://shuku.invalid/errors/opds-auth-throttled",
            "title": "Too many authentication attempts.",
        },
        media_type="application/problem+json",
        headers={
            "Retry-After": str(max(1, retry_after_seconds)),
            "Cache-Control": "no-store",
            "Vary": "Authorization",
        },
    )


def problem_response(status_code: int, problem_type: str, title: str) -> JSONResponse:
    problem = OpdsProblemDetails(type=problem_type, title=title)
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
        headers={"Cache-Control": "no-store", "Vary": "Authorization"},
    )


def _problem_for(error: Exception) -> JSONResponse:
    if isinstance(error, OpdsPublicationNotFound):
        return problem_response(404, "about:blank", "Publication not found.")
    if isinstance(error, OpdsProgressionInvalidPayload):
        return problem_response(
            400,
            "https://registry.opds.io/error#progression-invalid-payload",
            "Progression could not be updated due to an invalid payload.",
        )
    if isinstance(error, OpdsProgressionIncorrectUser):
        return problem_response(
            403,
            "https://registry.opds.io/error#progression-incorrect-user",
            "Progression could not be updated for the current user.",
        )
    if isinstance(error, OpdsProgressionLocked):
        return problem_response(
            403,
            "https://registry.opds.io/error#progression-locked",
            "Progression can no longer be updated for this publication.",
        )
    if isinstance(error, OpdsProgressionDateConflict):
        return problem_response(
            409,
            "https://registry.opds.io/error#progression-date",
            "A more recent progression point is already available.",
        )
    raise error


def create_opds_router(dependencies: OpdsHttpDependencies) -> APIRouter:
    router = APIRouter(
        tags=["opds"],
        include_in_schema=False,
        default_response_class=OpdsProtocolResponse,
    )
    default_page_size = dependencies.default_page_size

    def actor_id(authorization: str | None, request: Request) -> str | JSONResponse:
        snapshot = dependencies.settings()
        if not snapshot.enabled or snapshot.public_base_url is None:
            return problem_response(404, "about:blank", "OPDS is disabled.")
        try:
            credentials = parse_basic_authorization(authorization)
        except OpdsAuthenticationRequired:
            return authentication_required_response(
                _authentication_document(snapshot.public_base_url)
            )
        try:
            actor = dependencies.authenticator.authenticate(
                credentials,
                request.client.host if request.client is not None else "unknown",
            )
        except OpdsAuthenticationThrottled as error:
            return authentication_throttled_response(error.retry_after_seconds)
        return (
            actor.user_id
            if actor
            else authentication_required_response(
                _authentication_document(snapshot.public_base_url)
            )
        )

    @router.get("/opds/authentication.json")
    def authentication_document() -> JSONResponse:
        snapshot = dependencies.settings()
        if not snapshot.enabled or snapshot.public_base_url is None:
            return problem_response(404, "about:blank", "OPDS is disabled.")
        document = _authentication_document(snapshot.public_base_url)
        return JSONResponse(
            content=document.model_dump(mode="json", exclude_none=True),
            media_type="application/opds-authentication+json",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/opds/v1.2/opensearch.xml")
    def opensearch_description(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        actor = actor_id(authorization, request)
        if isinstance(actor, JSONResponse):
            return actor
        snapshot = dependencies.settings()
        if snapshot.public_base_url is None:
            return problem_response(404, "about:blank", "OPDS is disabled.")
        return Response(
            content=serialize_opensearch_description(
                f"{snapshot.public_base_url}/opds/v1.2/search"
                f"?q={{searchTerms}}&page=1&pageSize={dependencies.default_page_size}"
            ),
            media_type="application/opensearchdescription+xml",
            headers={
                "Cache-Control": "private, max-age=3600",
                "Vary": "Authorization",
            },
        )

    def feed_response(
        *,
        view: str,
        resource_id: str | None,
        search: str | None,
        page: int,
        page_size: int,
        authorization: str | None,
        request: Request,
    ) -> Response:
        actor = actor_id(authorization, request)
        if isinstance(actor, JSONResponse):
            return actor
        snapshot = dependencies.settings()
        if snapshot.public_base_url is None:
            return problem_response(404, "about:blank", "OPDS is disabled.")
        try:
            feed = dependencies.catalog.load_feed(
                OpdsCatalogQueryDto(
                    actor_id=actor,
                    public_base_url=snapshot.public_base_url,
                    search=search,
                    page=page,
                    page_size=min(page_size, dependencies.max_page_size),
                    view=view,
                    resource_id=resource_id,
                )
            )
        except OpdsPublicationNotFound as error:
            return _problem_for(error)
        return Response(
            content=serialize_opds_feed(feed),
            media_type=CATALOG_MEDIA_TYPE.format(kind=feed.kind),
            headers={"Cache-Control": "private, max-age=60", "Vary": "Authorization"},
        )

    @router.get("/opds/v1.2/catalog")
    def catalog(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[
            int, Query(alias="pageSize", ge=1, le=100)
        ] = default_page_size,
    ) -> Response:
        return feed_response(
            view="catalog",
            resource_id=None,
            search=None,
            page=page,
            page_size=page_size,
            authorization=authorization,
            request=request,
        )

    def section_feed(
        view: str,
        request: Request,
        authorization: str | None,
        page: int,
        page_size: int,
        resource_id: str | None = None,
    ) -> Response:
        return feed_response(
            view=view,
            resource_id=resource_id,
            search=None,
            page=page,
            page_size=page_size,
            authorization=authorization,
            request=request,
        )

    @router.get("/opds/v1.2/works")
    def works(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[
            int, Query(alias="pageSize", ge=1, le=100)
        ] = default_page_size,
    ) -> Response:
        return section_feed("works", request, authorization, page, page_size)

    @router.get("/opds/v1.2/recent")
    def recent(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[
            int, Query(alias="pageSize", ge=1, le=100)
        ] = default_page_size,
    ) -> Response:
        return section_feed("recent", request, authorization, page, page_size)

    @router.get("/opds/v1.2/works/{work_id}")
    def work(
        work_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        return section_feed("work", request, authorization, 1, 100, work_id)

    def facet_routes(kind: str) -> None:
        @router.get(f"/opds/v1.2/{kind}", name=f"opds_{kind}")
        def facets(
            request: Request,
            authorization: Annotated[str | None, Header()] = None,
            page: Annotated[int, Query(ge=1)] = 1,
            page_size: Annotated[
                int, Query(alias="pageSize", ge=1, le=100)
            ] = default_page_size,
        ) -> Response:
            return section_feed(kind, request, authorization, page, page_size)

        @router.get(f"/opds/v1.2/{kind}/{{facet_id}}", name=f"opds_{kind}_works")
        def facet_works(
            facet_id: str,
            request: Request,
            authorization: Annotated[str | None, Header()] = None,
            page: Annotated[int, Query(ge=1)] = 1,
            page_size: Annotated[
                int, Query(alias="pageSize", ge=1, le=100)
            ] = default_page_size,
        ) -> Response:
            return section_feed(
                f"{kind}_works",
                request,
                authorization,
                page,
                page_size,
                facet_id,
            )

    for facet_kind in ("authors", "series", "tags"):
        facet_routes(facet_kind)

    @router.get("/opds/v1.2/shelves")
    def shelves(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[
            int, Query(alias="pageSize", ge=1, le=100)
        ] = default_page_size,
    ) -> Response:
        return section_feed("shelves", request, authorization, page, page_size)

    @router.get("/opds/v1.2/shelves/{shelf_id}")
    def shelf(
        shelf_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[
            int, Query(alias="pageSize", ge=1, le=100)
        ] = default_page_size,
    ) -> Response:
        return section_feed("shelf", request, authorization, page, page_size, shelf_id)

    @router.get("/opds/v1.2/search")
    def search(
        q: Annotated[str, Query(min_length=1, max_length=200)],
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[
            int, Query(alias="pageSize", ge=1, le=100)
        ] = default_page_size,
    ) -> Response:
        return feed_response(
            view="search",
            resource_id=None,
            search=q,
            page=page,
            page_size=page_size,
            authorization=authorization,
            request=request,
        )

    @router.get("/opds/v1.2/volumes/{volume_id}/progression")
    def get_progression(
        volume_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        actor = actor_id(authorization, request)
        if isinstance(actor, JSONResponse):
            return actor
        try:
            document = dependencies.progression.get_progression(actor, volume_id)
        except (OpdsPublicationNotFound, OpdsProgressionIncorrectUser) as error:
            return _problem_for(error)
        if document is None:
            return Response(
                status_code=200,
                media_type=PROGRESSION_MEDIA_TYPE,
                headers={"Cache-Control": "no-store", "Vary": "Authorization"},
            )
        wire_document = OpdsProgressionDocument.from_dto(document)
        return JSONResponse(
            content=wire_document.model_dump(mode="json", exclude_none=True),
            media_type=PROGRESSION_MEDIA_TYPE,
            headers={"Cache-Control": "no-store", "Vary": "Authorization"},
        )

    @router.put("/opds/v1.2/volumes/{volume_id}/progression")
    def put_progression(
        volume_id: str,
        request: Request,
        document_payload: Annotated[object, Body()],
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        actor = actor_id(authorization, request)
        if isinstance(actor, JSONResponse):
            return actor
        try:
            document = OpdsProgressionDocument.model_validate(document_payload)
        except ValidationError:
            return _problem_for(OpdsProgressionInvalidPayload())
        try:
            result = dependencies.progression.update_progression(
                actor, volume_id, document.to_dto()
            )
        except (
            OpdsPublicationNotFound,
            OpdsProgressionInvalidPayload,
            OpdsProgressionIncorrectUser,
            OpdsProgressionLocked,
            OpdsProgressionDateConflict,
        ) as error:
            return _problem_for(error)
        response_document = OpdsProgressionDocument.from_dto(result.document)
        return JSONResponse(
            status_code=201 if result.created else 200,
            content=response_document.model_dump(mode="json", exclude_none=True),
            media_type=PROGRESSION_MEDIA_TYPE,
            headers={"Cache-Control": "no-store", "Vary": "Authorization"},
        )

    def resource_response(
        actor: str | JSONResponse,
        callback: Callable[[str, str, Request], Response] | None,
        resource_id: str,
        request: Request,
    ) -> Response:
        if isinstance(actor, JSONResponse):
            return actor
        if callback is None:
            return problem_response(404, "about:blank", "Resource not found.")
        response = callback(actor, resource_id, request)
        response.headers["Vary"] = "Authorization"
        return response

    @router.api_route("/opds/v1.2/works/{work_id}/cover", methods=["GET", "HEAD"])
    def work_cover(
        work_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        return resource_response(
            actor_id(authorization, request), dependencies.work_cover, work_id, request
        )

    @router.api_route("/opds/v1.2/volumes/{volume_id}/cover", methods=["GET", "HEAD"])
    def volume_cover(
        volume_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        return resource_response(
            actor_id(authorization, request),
            dependencies.volume_cover,
            volume_id,
            request,
        )

    @router.api_route("/opds/v1.2/volumes/{volume_id}/file", methods=["GET", "HEAD"])
    def volume_file(
        volume_id: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        return resource_response(
            actor_id(authorization, request),
            dependencies.volume_file,
            volume_id,
            request,
        )

    @router.api_route(
        "/opds/v1.2/volumes/{volume_id}/pages/{page_number}",
        methods=["GET", "HEAD"],
    )
    def volume_page(
        volume_id: str,
        page_number: int,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        max_width: Annotated[int | None, Query(alias="maxWidth", ge=1)] = None,
    ) -> Response:
        actor = actor_id(authorization, request)
        if isinstance(actor, JSONResponse):
            return actor
        if dependencies.volume_page is None:
            return problem_response(404, "about:blank", "Page not found.")
        try:
            page_request = PsePageRequestDto(
                actor_id=actor,
                volume_id=volume_id,
                page_number=page_number,
                max_width=max_width,
            )
        except ValueError:
            return problem_response(404, "about:blank", "Page not found.")
        response = dependencies.volume_page(actor, page_request, request)
        response.headers["Vary"] = "Authorization"
        return response

    return router


def _authentication_document(public_base_url: str) -> OpdsAuthenticationDocument:
    return OpdsAuthenticationDocument(
        id=f"{public_base_url}/opds/authentication.json",
        title="Shuku Starship OPDS",
        description=(
            "Use your Shuku account email and password. / 使用 Shuku 账号邮箱和密码。"
        ),
        authentication=[
            OpdsAuthenticationFlow(
                labels=OpdsAuthenticationLabels(login="Email", password="Password")
            )
        ],
    )
