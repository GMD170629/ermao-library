from __future__ import annotations

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.authorization import (
    authorization_context,
    book_visibility_predicate,
)
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
)
from app.models.auth import User
from app.modules.library.application.filter_ast import FilterCondition, FilterExpression
from app.modules.library.application.queries import SmartShelfCriteria
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    resolve_library_roots,
)


class SqlAlchemyLibraryQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def matching_book_ids(
        self,
        criteria: SmartShelfCriteria,
        *,
        user_id: str | None,
    ) -> list[str]:
        user = self._db.get(User, user_id) if user_id else None
        context = authorization_context(self._db, user) if user else None
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
        predicates = [
            LibraryBook.visibility_state == "VISIBLE",
            book_visibility_predicate(context),
        ]
        if criteria.search:
            term = f"%{criteria.search.casefold()}%"
            predicates.append(
                exists(
                    select(LibraryBookMetadata.book_id).where(
                        LibraryBookMetadata.book_id == LibraryBook.id,
                        or_(
                            func.lower(LibraryBookMetadata.title).like(term),
                            func.lower(
                                func.coalesce(LibraryBookMetadata.author, "")
                            ).like(term),
                            func.lower(
                                func.coalesce(LibraryBookMetadata.series_name, "")
                            ).like(term),
                        ),
                    )
                )
            )
        if criteria.statuses:
            status_filters = FilterExpression(
                combinator="ANY",
                conditions=tuple(
                    FilterCondition(
                        field="readingStatus", operator="equals", value=status
                    )
                    for status in criteria.statuses
                ),
            )
            dynamic = compile_filter_expression(
                status_filters, context=context, user_id=user_id
            )
            if dynamic is not None:
                predicates.append(dynamic)
        for tag in criteria.tags:
            link = aliased(LibraryBookFacet)
            facet = aliased(LibraryFacet)
            predicates.append(
                exists(
                    select(link.book_id)
                    .join(facet, facet.id == link.facet_id)
                    .where(
                        link.book_id == LibraryBook.id,
                        facet.kind == "TAG",
                        func.lower(facet.name) == tag.casefold(),
                    )
                )
            )
        if criteria.authors:
            predicates.append(
                exists(
                    select(LibraryBookMetadata.book_id).where(
                        LibraryBookMetadata.book_id == LibraryBook.id,
                        or_(
                            *(
                                func.lower(
                                    func.coalesce(LibraryBookMetadata.author, "")
                                ).like(f"%{author.casefold()}%")
                                for author in criteria.authors
                            )
                        ),
                    )
                )
            )
        if criteria.filters.conditions:
            dynamic = compile_filter_expression(
                criteria.filters,
                context=context,
                user_id=user_id,
                shelf_owner_user_id=user_id,
                library_roots=resolve_library_roots(
                    self._db, criteria.filters, context
                ),
            )
            if dynamic is not None:
                predicates.append(dynamic)
        matched_ids = list(
            self._db.scalars(
                select(LibraryBook.id)
                .where(and_(*predicates))
                .order_by(LibraryBook.updated_at.desc(), LibraryBook.id.desc())
            )
        )
        if not criteria.included_book_ids:
            return matched_ids
        included = set(
            self._db.scalars(
                select(LibraryBook.id).where(
                    LibraryBook.id.in_(criteria.included_book_ids),
                    LibraryBook.visibility_state == "VISIBLE",
                    book_visibility_predicate(context),
                )
            )
        )
        return list(
            dict.fromkeys(
                [
                    *matched_ids,
                    *(
                        book_id
                        for book_id in criteria.included_book_ids
                        if book_id in included
                    ),
                ]
            )
        )
