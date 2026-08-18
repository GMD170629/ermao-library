from __future__ import annotations

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.authorization import (
    authorization_context,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.auth import User
from app.models.library import (
    LibraryFacet,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
)
from app.modules.library.application.filter_ast import FilterCondition, FilterExpression
from app.modules.library.application.queries import SmartShelfCriteria
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    resolve_library_roots,
)


class SqlAlchemyLibraryQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def matching_work_ids(
        self,
        criteria: SmartShelfCriteria,
        *,
        user_id: str | None,
    ) -> list[str]:
        user = self._db.get(User, user_id) if user_id else None
        context = authorization_context(self._db, user) if user else None
        predicates = [LibraryWork.hidden.is_(False)]
        if context is not None:
            predicates.append(work_visibility_predicate(context))
        if criteria.search:
            term = f"%{criteria.search.casefold()}%"
            predicates.append(
                or_(
                    func.lower(LibraryWork.title).like(term),
                    func.lower(func.coalesce(LibraryWork.author, "")).like(term),
                    func.lower(LibraryWork.tags).like(term),
                )
            )
        if criteria.statuses:
            status_filters = FilterExpression(
                combinator="ANY",
                conditions=tuple(
                    FilterCondition(
                        field="readingStatus",
                        operator="equals",
                        value=status,
                    )
                    for status in criteria.statuses
                ),
            )
            if context is None:
                from app.core.authorization import AuthorizationContext

                context = AuthorizationContext(
                    user_id=user_id or "",
                    is_admin=True,
                    can_manage_system=True,
                    can_view_manual_imports=True,
                    library_ids=(),
                    authz_version=1,
                )
            status_predicate = compile_filter_expression(
                status_filters,
                context=context,
                user_id=user_id,
            )
            if status_predicate is not None:
                predicates.append(status_predicate)
        if criteria.media_kinds:
            media_version = aliased(LibraryVersion)
            volume = aliased(LibraryVolume)
            volume_predicates = [volume.hidden.is_(False)]
            if context is not None:
                volume_predicates.append(volume_visibility_predicate(context, volume))
            predicates.append(
                exists(
                    select(media_version.id).where(
                        media_version.work_id == LibraryWork.id,
                        media_version.source_key.in_(criteria.media_kinds),
                        exists(
                            select(volume.id).where(
                                volume.version_id == media_version.id,
                                *volume_predicates,
                            )
                        ),
                    )
                )
            )
        for tag in criteria.tags:
            link = aliased(LibraryWorkFacet)
            facet = aliased(LibraryFacet)
            predicates.append(
                exists(
                    select(link.work_id)
                    .join(facet, facet.id == link.facet_id)
                    .where(
                        link.work_id == LibraryWork.id,
                        facet.kind == "TAG",
                        func.lower(facet.name) == tag.casefold(),
                    )
                )
            )
        if criteria.authors:
            predicates.append(
                or_(
                    *(
                        func.lower(func.coalesce(LibraryWork.author, "")).like(
                            f"%{author.casefold()}%"
                        )
                        for author in criteria.authors
                    )
                )
            )
        if criteria.filters.conditions:
            if context is None:
                from app.core.authorization import AuthorizationContext

                context = AuthorizationContext(
                    user_id=user_id or "",
                    is_admin=True,
                    can_manage_system=True,
                    can_view_manual_imports=True,
                    library_ids=(),
                    authz_version=1,
                )
            library_roots = resolve_library_roots(
                self._db,
                criteria.filters,
                context,
            )
            dynamic = compile_filter_expression(
                criteria.filters,
                context=context,
                user_id=user_id,
                shelf_owner_user_id=user_id,
                library_roots=library_roots,
            )
            if dynamic is not None:
                predicates.append(dynamic)
        matched_ids = list(
            self._db.scalars(
                select(LibraryWork.id)
                .where(and_(*predicates))
                .order_by(LibraryWork.updated_at.desc(), LibraryWork.id.desc())
            )
        )
        if not criteria.included_work_ids:
            return matched_ids
        included_predicates = [
            LibraryWork.id.in_(criteria.included_work_ids),
            LibraryWork.hidden.is_(False),
        ]
        if context is not None:
            included_predicates.append(work_visibility_predicate(context))
        visible_included = set(
            self._db.scalars(select(LibraryWork.id).where(and_(*included_predicates)))
        )
        return list(
            dict.fromkeys(
                [
                    *matched_ids,
                    *(
                        work_id
                        for work_id in criteria.included_work_ids
                        if work_id in visible_included
                    ),
                ]
            )
        )
