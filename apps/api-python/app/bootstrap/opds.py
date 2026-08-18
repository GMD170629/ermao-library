"""Composition root for the OPDS catalog and its cross-capability adapters."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.bootstrap.auth import build_password_authenticator
from app.bootstrap.media import media_page_index, media_resource_query, media_streaming
from app.bootstrap.reader import reader_volume_service
from app.core.authorization import (
    AuthorizationContext,
    authorization_context,
    can_access_volume,
    can_access_work,
    read_user_preferences,
)
from app.core.config import Settings
from app.core.i18n import configured_locale
from app.models.auth import User
from app.modules.auth.infrastructure.password_authentication import (
    BoundedPasswordVerificationGateway,
)
from app.modules.auth.public import (
    PasswordAuthenticated,
    PasswordAuthenticationThrottled,
    PasswordCredentials,
)
from app.modules.library.application.catalog import (
    CatalogFacet,
    CatalogFacetKind,
    CatalogVolume,
    CatalogWork,
    CatalogWorkFilter,
    GetCatalogWork,
    ListCatalogFacets,
    ListCatalogWorks,
)
from app.modules.library.application.queries import (
    GetSmartShelfWorkIds,
    SmartShelfCriteria,
)
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries
from app.modules.library.infrastructure.queries import SqlAlchemyLibraryQueries
from app.modules.opds.application.dto import (
    OPDS_ACQUISITION_REL,
    OPDS_PROGRESSION_MEDIA_TYPE,
    OPDS_PROGRESSION_REL,
    OpdsActorDto,
    OpdsAuthenticationRequestDto,
    OpdsAuthorDto,
    OpdsCatalogQueryDto,
    OpdsEntryDto,
    OpdsFeedDto,
    OpdsLinkDto,
    OpdsProgressionDeviceDto,
    OpdsProgressionDocumentDto,
    OpdsProgressionUpdateResultDto,
    PsePageRequestDto,
    PseStreamDto,
    normalize_pse_max_width,
    select_pse_stream_media_type,
)
from app.modules.opds.application.settings import (
    OPDS_ENABLED_SETTING_KEY,
    OPDS_PUBLIC_BASE_URL_SETTING_KEY,
    OpdsSettingsSnapshot,
    resolve_opds_settings,
)
from app.modules.opds.domain.errors import (
    OpdsAuthenticationThrottled,
    OpdsProgressionDateConflict,
    OpdsProgressionInvalidPayload,
    OpdsPublicationNotFound,
)
from app.modules.opds.presentation.http import OpdsHttpDependencies, create_opds_router
from app.modules.reader.application.dto import ReaderProgressDto
from app.modules.reader.infrastructure.volume_repository import (
    SqlAlchemyReaderVolumeRepository,
)
from app.modules.reader.public import (
    ReaderAccessScope,
    ReaderExternalProgressDto,
    ReaderProgressDateConflict,
    ReaderVolumeFormatUnsupported,
    ReaderVolumeNotFound,
    SaveExternalProgressCommand,
)
from app.modules.shelf.application.catalog import (
    ListCatalogShelfWorkIds,
    ListCatalogShelves,
)
from app.modules.shelf.infrastructure.catalog import SqlAlchemyCatalogShelfQueries
from app.modules.system.infrastructure.settings import get_setting

SessionFactory = Callable[[], Session]
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
NAVIGATION_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQUISITION_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
LOGGER = logging.getLogger(__name__)


def get_opds_settings(db: Session) -> OpdsSettingsSnapshot:
    return resolve_opds_settings(
        get_setting(db, OPDS_ENABLED_SETTING_KEY, None),
        stored_public_base_url=get_setting(db, OPDS_PUBLIC_BASE_URL_SETTING_KEY, None),
    )


def _opds_settings(session_factory: SessionFactory) -> OpdsSettingsSnapshot:
    db = session_factory()
    try:
        return get_opds_settings(db)
    finally:
        db.close()


def _catalog_text(locale: str, chinese: str, english: str) -> str:
    return english if locale == "en-US" else chinese


def _active_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None or user.status != "active":
        raise OpdsPublicationNotFound
    return user


def _reader_scope(context: AuthorizationContext) -> ReaderAccessScope:
    return ReaderAccessScope(
        is_admin=context.is_admin,
        can_view_manual_imports=context.can_view_manual_imports,
        library_ids=context.library_ids,
    )


class PasswordOpdsAuthenticator:
    def __init__(
        self,
        session_factory: SessionFactory,
        runtime: BoundedPasswordVerificationGateway,
    ) -> None:
        self._session_factory = session_factory
        self._runtime = runtime

    def authenticate(
        self, request: OpdsAuthenticationRequestDto
    ) -> OpdsActorDto | None:
        credentials = request.credentials
        db = self._session_factory()
        try:
            result = build_password_authenticator(db, self._runtime).execute(
                PasswordCredentials(
                    email=credentials.username,
                    password=credentials.password,
                    client_address=request.client_address,
                )
            )
        finally:
            db.close()
        if isinstance(result, PasswordAuthenticationThrottled):
            self._record_authentication_event(
                request,
                outcome="throttled",
                retry_after_seconds=result.retry_after_seconds,
            )
        elif isinstance(result, PasswordAuthenticated):
            self._record_authentication_event(
                request,
                outcome="succeeded",
                actor_id=result.principal.user_id,
            )
        else:
            self._record_authentication_event(request, outcome="failed")
        if isinstance(result, PasswordAuthenticationThrottled):
            raise OpdsAuthenticationThrottled(result.retry_after_seconds)
        if not isinstance(result, PasswordAuthenticated):
            return None
        return OpdsActorDto(user_id=result.principal.user_id)

    @staticmethod
    def _record_authentication_event(
        request: OpdsAuthenticationRequestDto,
        *,
        outcome: Literal["succeeded", "failed", "throttled"],
        actor_id: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        log = LOGGER.info if outcome == "succeeded" else LOGGER.warning
        log(
            "opds.authentication outcome=%s actor_id=%s client_address=%s "
            "method=%s path=%s username=%s retry_after_seconds=%s",
            outcome,
            actor_id or "anonymous",
            request.client_address[:255],
            request.method[:16].upper(),
            request.path[:2048],
            request.credentials.username.strip()[:320],
            retry_after_seconds,
        )


@dataclass(frozen=True, slots=True)
class OpdsCatalogUrls:
    public_base_url: str

    def url(self, path: str) -> str:
        return f"{self.public_base_url}{path}"

    def page_url(
        self,
        path: str,
        page: int,
        page_size: int,
        search: str | None = None,
    ) -> str:
        values: dict[str, str | int] = {"page": page, "pageSize": page_size}
        if search:
            values["q"] = search
        return self.url(f"{path}?{urlencode(values)}")


class SqlAlchemyOpdsCatalog:
    def __init__(self, session_factory: SessionFactory, settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def _feed(
        self,
        *,
        urls: OpdsCatalogUrls,
        path: str,
        title: str,
        kind: str,
        entries: tuple[OpdsEntryDto, ...],
        total: int,
        page: int,
        page_size: int,
        updated_at: datetime | None,
        search: str | None = None,
    ) -> OpdsFeedDto:
        last_page = max(1, (total + page_size - 1) // page_size)
        return OpdsFeedDto(
            id=urls.url(path),
            title=title,
            updated_at=updated_at or EPOCH,
            kind="acquisition" if kind == "acquisition" else "navigation",
            self_url=urls.page_url(path, page, page_size, search),
            start_url=urls.url("/opds/v1.2/catalog"),
            entries=entries,
            total_results=total,
            start_index=(page - 1) * page_size,
            items_per_page=page_size,
            search_url_template=urls.url("/opds/v1.2/opensearch.xml"),
            next_url=(
                urls.page_url(path, page + 1, page_size, search)
                if page < last_page
                else None
            ),
            previous_url=(
                urls.page_url(path, page - 1, page_size, search) if page > 1 else None
            ),
        )

    def _navigation_entry(
        self,
        *,
        urls: OpdsCatalogUrls,
        id_value: str,
        title: str,
        path: str,
        updated_at: datetime,
    ) -> OpdsEntryDto:
        return OpdsEntryDto(
            id=id_value,
            title=title,
            updated_at=updated_at,
            links=(
                OpdsLinkDto(
                    href=urls.url(path),
                    rel="subsection",
                    media_type=NAVIGATION_TYPE,
                ),
            ),
        )

    def _work_entry(self, urls: OpdsCatalogUrls, work: CatalogWork) -> OpdsEntryDto:
        links = [
            OpdsLinkDto(
                href=urls.url(f"/opds/v1.2/works/{quote(work.id)}"),
                rel="subsection",
                media_type=ACQUISITION_TYPE,
            )
        ]
        if work.has_cover:
            links.append(
                OpdsLinkDto(
                    href=urls.url(f"/opds/v1.2/works/{quote(work.id)}/cover"),
                    rel="http://opds-spec.org/image",
                    media_type="image/jpeg",
                )
            )
        return OpdsEntryDto(
            id=f"urn:shuku:work:{work.id}",
            title=work.title,
            updated_at=work.updated_at,
            authors=(OpdsAuthorDto(work.author),) if work.author else (),
            summary=work.description,
            links=tuple(links),
        )

    def _volume_entry(
        self,
        *,
        urls: OpdsCatalogUrls,
        work: CatalogWork,
        volume: CatalogVolume,
        progress_by_volume: Mapping[str, ReaderProgressDto],
        pse_media_type: str = "image/jpeg",
    ) -> OpdsEntryDto:
        links = [
            OpdsLinkDto(
                href=urls.url(f"/opds/v1.2/volumes/{quote(volume.id)}/file"),
                rel=OPDS_ACQUISITION_REL,
                media_type=volume.file.mime_type,
            ),
            OpdsLinkDto(
                href=urls.url(f"/opds/v1.2/volumes/{quote(volume.id)}/progression"),
                rel=OPDS_PROGRESSION_REL,
                media_type=OPDS_PROGRESSION_MEDIA_TYPE,
            ),
        ]
        if volume.has_cover:
            links.append(
                OpdsLinkDto(
                    href=urls.url(f"/opds/v1.2/volumes/{quote(volume.id)}/cover"),
                    rel="http://opds-spec.org/image",
                    media_type="image/jpeg",
                )
            )
        progress = progress_by_volume.get(volume.id)
        last_read = (
            _comic_page_from_progress(progress) if progress is not None else None
        )
        if last_read is not None and volume.page_count is not None:
            last_read = min(last_read, volume.page_count)
        pse = (
            PseStreamDto(
                href_template=urls.url(
                    f"/opds/v1.2/volumes/{quote(volume.id)}/pages/"
                    + (
                        "{pageNumber}"
                        if pse_media_type == "image/gif"
                        else "{pageNumber}?maxWidth={maxWidth}"
                    )
                ),
                media_type=pse_media_type,
                page_count=volume.page_count or 0,
                last_read=last_read,
                last_read_date=(
                    progress.progressed_at
                    if last_read is not None and progress is not None
                    else None
                ),
            )
            if volume.media_kind == "COMIC" and (volume.page_count or 0) > 0
            else None
        )
        return OpdsEntryDto(
            id=f"urn:shuku:volume:{volume.id}",
            title=volume.title,
            updated_at=volume.updated_at,
            authors=(OpdsAuthorDto(work.author),) if work.author else (),
            summary=volume.description or work.description,
            links=tuple(links),
            pse_stream=pse,
        )

    def load_feed(self, query: OpdsCatalogQueryDto) -> OpdsFeedDto:
        urls = OpdsCatalogUrls(query.public_base_url)
        db = self._session_factory()
        try:
            user = _active_user(db, query.actor_id)
            context = authorization_context(db, user)
            preferred_locale = read_user_preferences(db, user.id).get("locale")
            locale = (
                str(preferred_locale)
                if preferred_locale in {"zh-CN", "en-US"}
                else configured_locale(db)
            )
            library = SqlAlchemyCatalogQueries(db)
            works = ListCatalogWorks(library)
            facets = ListCatalogFacets(library)
            smart_shelves = GetSmartShelfWorkIds(SqlAlchemyLibraryQueries(db))
            shelves = SqlAlchemyCatalogShelfQueries(
                db,
                smart_work_ids=lambda rules, user_id: smart_shelves.execute(
                    SmartShelfCriteria.from_external(rules),
                    user_id=user_id,
                ),
            )
            if query.view == "catalog":
                sections = (
                    ("works", _catalog_text(locale, "全部作品", "All works")),
                    ("recent", _catalog_text(locale, "最近添加", "Recently added")),
                    ("authors", _catalog_text(locale, "作者", "Authors")),
                    ("series", _catalog_text(locale, "系列", "Series")),
                    ("tags", _catalog_text(locale, "标签", "Tags")),
                    ("shelves", _catalog_text(locale, "个人书架", "Personal shelves")),
                )
                entries = tuple(
                    self._navigation_entry(
                        urls=urls,
                        id_value=f"urn:shuku:opds:{key}",
                        title=title,
                        path=f"/opds/v1.2/{key}",
                        updated_at=EPOCH,
                    )
                    for key, title in sections
                )
                return self._feed(
                    urls=urls,
                    path="/opds/v1.2/catalog",
                    title="Shuku Starship",
                    kind="navigation",
                    entries=entries,
                    total=len(entries),
                    page=1,
                    page_size=len(entries),
                    updated_at=EPOCH,
                )
            if query.view == "work":
                work = GetCatalogWork(library).execute(
                    context=context, work_id=query.resource_id or ""
                )
                if work is None:
                    raise OpdsPublicationNotFound
                repository = SqlAlchemyReaderVolumeRepository(db)
                progresses = repository.list_progresses(
                    user.id, [volume.id for volume in work.volumes]
                )
                progress_by_volume = {
                    progress.volume_id: progress for progress in progresses
                }
                pse_media_types = {
                    volume.id: self._pse_media_type(volume.id)
                    for volume in work.volumes
                    if volume.media_kind == "COMIC"
                }
                entries = tuple(
                    self._volume_entry(
                        urls=urls,
                        work=work,
                        volume=volume,
                        progress_by_volume=progress_by_volume,
                        pse_media_type=pse_media_types.get(volume.id, "image/jpeg"),
                    )
                    for volume in work.volumes
                )
                return self._feed(
                    urls=urls,
                    path=f"/opds/v1.2/works/{quote(work.id)}",
                    title=work.title,
                    kind="acquisition",
                    entries=entries,
                    total=len(entries),
                    page=1,
                    page_size=max(1, len(entries)),
                    updated_at=work.updated_at,
                )
            if query.view in {"authors", "series", "tags"}:
                kind = {"authors": "AUTHOR", "series": "SERIES", "tags": "TAG"}[
                    query.view
                ]
                facet_result = facets.execute(
                    context=context,
                    kind=kind,
                    page=query.page,
                    page_size=query.page_size,
                )
                entries = tuple(
                    self._facet_entry(urls, query.view, facet)
                    for facet in facet_result.facets
                )
                return self._feed(
                    urls=urls,
                    path=f"/opds/v1.2/{query.view}",
                    title={
                        "authors": _catalog_text(locale, "作者", "Authors"),
                        "series": _catalog_text(locale, "系列", "Series"),
                        "tags": _catalog_text(locale, "标签", "Tags"),
                    }[query.view],
                    kind="navigation",
                    entries=entries,
                    total=facet_result.total,
                    page=facet_result.page,
                    page_size=facet_result.page_size,
                    updated_at=facet_result.updated_at,
                )
            if query.view == "shelves":
                shelf_result = ListCatalogShelves(shelves).execute(
                    context=context, page=query.page, page_size=query.page_size
                )
                entries = tuple(
                    self._navigation_entry(
                        urls=urls,
                        id_value=f"urn:shuku:shelf:{shelf.id}",
                        title=shelf.name,
                        path=f"/opds/v1.2/shelves/{quote(shelf.id)}",
                        updated_at=shelf.updated_at,
                    )
                    for shelf in shelf_result.shelves
                )
                return self._feed(
                    urls=urls,
                    path="/opds/v1.2/shelves",
                    title=_catalog_text(locale, "个人书架", "Personal shelves"),
                    kind="navigation",
                    entries=entries,
                    total=shelf_result.total,
                    page=shelf_result.page,
                    page_size=shelf_result.page_size,
                    updated_at=shelf_result.updated_at,
                )
            work_filter, path, title, total_override = self._work_filter(
                query, context, shelves, locale
            )
            work_result = works.execute(
                context=context,
                filters=work_filter,
                page=1 if query.view == "shelf" else query.page,
                page_size=query.page_size,
            )
            entries = tuple(self._work_entry(urls, work) for work in work_result.works)
            return self._feed(
                urls=urls,
                path=path,
                title=title,
                kind="navigation",
                entries=entries,
                total=(
                    total_override if total_override is not None else work_result.total
                ),
                page=query.page,
                page_size=work_result.page_size,
                updated_at=work_result.updated_at,
                search=query.search,
            )
        finally:
            db.close()

    def _pse_media_type(self, volume_id: str) -> str:
        projection_db = self._session_factory()
        try:
            projection = media_page_index.load_read_only(projection_db, volume_id)
        finally:
            projection_db.close()
        resolved = media_page_index.resolve_read_only(projection)
        return select_pse_stream_media_type(
            tuple(str(unit.media_type or "") for unit in resolved.pages)
        )

    def _facet_entry(
        self, urls: OpdsCatalogUrls, view: str, facet: CatalogFacet
    ) -> OpdsEntryDto:
        return self._navigation_entry(
            urls=urls,
            id_value=f"urn:shuku:facet:{facet.id}",
            title=facet.name,
            path=f"/opds/v1.2/{view}/{quote(facet.id)}",
            updated_at=facet.updated_at,
        )

    def _work_filter(
        self,
        query: OpdsCatalogQueryDto,
        context: AuthorizationContext,
        shelves: SqlAlchemyCatalogShelfQueries,
        locale: str,
    ) -> tuple[CatalogWorkFilter, str, str, int | None]:
        if query.view == "recent":
            return (
                CatalogWorkFilter(sort="recent"),
                "/opds/v1.2/recent",
                _catalog_text(locale, "最近添加", "Recently added"),
                None,
            )
        if query.view == "search":
            return (
                CatalogWorkFilter(search=query.search or ""),
                "/opds/v1.2/search",
                _catalog_text(
                    locale,
                    f"搜索：{query.search or ''}",
                    f"Search: {query.search or ''}",
                ),
                None,
            )
        facet_kind_by_view: dict[str, CatalogFacetKind] = {
            "authors_works": "AUTHOR",
            "series_works": "SERIES",
            "tags_works": "TAG",
        }
        if query.view in facet_kind_by_view:
            if not query.resource_id:
                raise OpdsPublicationNotFound
            return (
                CatalogWorkFilter(
                    facet_kind=facet_kind_by_view[query.view],
                    facet_id=query.resource_id,
                ),
                f"/opds/v1.2/{query.view.removesuffix('_works')}/{quote(query.resource_id)}",
                _catalog_text(locale, "作品", "Works"),
                None,
            )
        if query.view == "shelf":
            shelf_page = ListCatalogShelfWorkIds(shelves).execute(
                context=context,
                shelf_id=query.resource_id or "",
                page=query.page,
                page_size=query.page_size,
            )
            if shelf_page is None:
                raise OpdsPublicationNotFound
            return (
                CatalogWorkFilter(work_ids=shelf_page.work_ids),
                f"/opds/v1.2/shelves/{quote(shelf_page.shelf.id)}",
                shelf_page.shelf.name,
                shelf_page.total,
            )
        return (
            CatalogWorkFilter(),
            "/opds/v1.2/works",
            _catalog_text(locale, "全部作品", "All works"),
            None,
        )


class ReaderOpdsProgression:
    def __init__(self, session_factory: SessionFactory, settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def get_progression(
        self, actor_id: str, volume_id: str
    ) -> OpdsProgressionDocumentDto | None:
        db = self._session_factory()
        try:
            user = _active_user(db, actor_id)
            context = authorization_context(db, user)
            progress = reader_volume_service(db, self._settings).get_external_progress(
                user_id=user.id,
                volume_id=volume_id,
                access_scope=_reader_scope(context),
            )
            return _opds_progression(progress) if progress is not None else None
        except (ReaderVolumeNotFound, ReaderVolumeFormatUnsupported) as error:
            raise OpdsPublicationNotFound from error
        finally:
            db.close()

    def update_progression(
        self,
        actor_id: str,
        volume_id: str,
        document: OpdsProgressionDocumentDto,
    ) -> OpdsProgressionUpdateResultDto:
        db = self._session_factory()
        try:
            user = _active_user(db, actor_id)
            context = authorization_context(db, user)
            service = reader_volume_service(db, self._settings)
            existing = service.get_external_progress(
                user_id=user.id,
                volume_id=volume_id,
                access_scope=_reader_scope(context),
            )
            saved = service.save_external_progress(
                SaveExternalProgressCommand(
                    user_id=user.id,
                    volume_id=volume_id,
                    access_scope=_reader_scope(context),
                    progression=document.progression,
                    modified_at=document.modified,
                    device_id=document.device.id,
                    device_name=document.device.name,
                    references=document.references or (),
                )
            )
            return OpdsProgressionUpdateResultDto(
                created=existing is None,
                document=_opds_progression(saved),
            )
        except ReaderProgressDateConflict as error:
            raise OpdsProgressionDateConflict from error
        except (ReaderVolumeNotFound, ReaderVolumeFormatUnsupported) as error:
            raise OpdsPublicationNotFound from error
        except ValueError as error:
            raise OpdsProgressionInvalidPayload from error
        finally:
            db.close()


class OpdsMediaResources:
    def __init__(self, session_factory: SessionFactory, settings: Settings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def work_cover(self, actor_id: str, work_id: str, request: Request) -> Response:
        return self._cover(actor_id, request, work_id=work_id)

    def volume_cover(self, actor_id: str, volume_id: str, request: Request) -> Response:
        return self._cover(actor_id, request, volume_id=volume_id)

    def _cover(
        self,
        actor_id: str,
        request: Request,
        *,
        work_id: str | None = None,
        volume_id: str | None = None,
    ) -> Response:
        db = self._session_factory()
        try:
            user = _active_user(db, actor_id)
            if work_id is not None and not can_access_work(db, user, work_id):
                return Response(status_code=404)
            if volume_id is not None and not can_access_volume(db, user, volume_id):
                return Response(status_code=404)
            path_value = media_resource_query(db).cover_path(
                work_id=work_id, volume_id=volume_id
            )
            path = media_streaming.stored_path(
                path_value, self._settings, database_backed=True
            )
            if path is None or not path.is_file():
                return Response(status_code=404)
            return media_streaming.send_pse_page_file(
                path,
                request,
                user.id,
                self._settings,
                max_width=1600,
                file_id=work_id or volume_id or "cover",
            )
        finally:
            db.close()

    def volume_file(self, actor_id: str, volume_id: str, request: Request) -> Response:
        db = self._session_factory()
        try:
            user = _active_user(db, actor_id)
            if not can_access_volume(db, user, volume_id):
                return Response(status_code=404)
            resource = media_resource_query(db).first_volume_file(volume_id)
            return media_streaming.send_file(
                media_streaming.stored_path(
                    resource.path if resource else None,
                    self._settings,
                    database_backed=True,
                ),
                request,
                user.id,
                media_type=resource.mime_type if resource else None,
                name=Path(resource.path).name if resource else "file",
                route="opds-volume-file",
                file_id=resource.id if resource else volume_id,
            )
        finally:
            db.close()

    def volume_page(
        self, actor_id: str, page: PsePageRequestDto, request: Request
    ) -> Response:
        db = self._session_factory()
        try:
            user = _active_user(db, actor_id)
            if not can_access_volume(db, user, page.volume_id):
                return Response(status_code=404)
            user_id = user.id
            projection = media_page_index.load_read_only(db, page.volume_id)
        finally:
            db.close()
        resolved = media_page_index.resolve_read_only(projection)
        unit = resolved.page(page.internal_page_index)
        if unit is None:
            return Response(status_code=404)
        source = resolved.source_for(unit.file_id)
        width = normalize_pse_max_width(page.max_width)
        output_media_type = select_pse_stream_media_type(
            tuple(str(candidate.media_type or "") for candidate in resolved.pages)
        )
        if output_media_type == "image/gif":
            width = None
        if source is not None and source.kind == "COMIC":
            metadata = _json_object(unit.metadata_json)
            entry_name = metadata.get("zipEntryName") or unit.href
            return media_streaming.send_pse_page_zip_entry(
                media_streaming.stored_path(
                    source.path, self._settings, database_backed=True
                ),
                str(entry_name) if entry_name else None,
                request,
                user_id,
                self._settings,
                max_width=width,
                file_id=unit.id,
                output_media_type=output_media_type,
            )
        return media_streaming.send_pse_page_file(
            media_streaming.stored_path(
                unit.href, self._settings, database_backed=True
            ),
            request,
            user_id,
            self._settings,
            max_width=width,
            file_id=unit.id,
            output_media_type=output_media_type,
        )


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed: object = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _comic_page_from_progress(progress: ReaderProgressDto) -> int | None:
    location = _json_object(progress.location_json)
    page = location.get("pageIndex")
    return page if isinstance(page, int) and page >= 1 else None


def _opds_progression(
    progress: ReaderExternalProgressDto,
) -> OpdsProgressionDocumentDto:
    return OpdsProgressionDocumentDto(
        modified=progress.modified_at,
        device=OpdsProgressionDeviceDto(
            id=progress.device_id,
            name=progress.device_name,
        ),
        progression=progress.progression,
        references=progress.references,
    )


def build_opds_router(
    session_factory: SessionFactory,
    settings: Settings,
    authentication_runtime: BoundedPasswordVerificationGateway,
):
    resources = OpdsMediaResources(session_factory, settings)
    return create_opds_router(
        OpdsHttpDependencies(
            settings=lambda: _opds_settings(session_factory),
            authenticator=PasswordOpdsAuthenticator(
                session_factory, authentication_runtime
            ),
            catalog=SqlAlchemyOpdsCatalog(session_factory, settings),
            progression=ReaderOpdsProgression(session_factory, settings),
            default_page_size=settings.opds_page_size,
            max_page_size=settings.opds_max_page_size,
            work_cover=resources.work_cover,
            volume_cover=resources.volume_cover,
            volume_file=resources.volume_file,
            volume_page=resources.volume_page,
        )
    )


__all__ = ["build_opds_router", "get_opds_settings"]
