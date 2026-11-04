from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    Select,
    and_,
    case,
    exists,
    func,
    literal,
    or_,
    select,
    union,
    union_all,
)
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
from app.modules.library.infrastructure.books import book_ids_statement
from app.modules.library.infrastructure.filter_query import (
    compile_filter_expression,
    resolve_library_roots,
)
from app.modules.reader.public import ReaderV5LibraryPresentationQueryPort


@dataclass(frozen=True)
class _SmartShelfStatements:
    identities: Select[tuple[str]]
    ordered: Select[tuple[str]]


class SqlAlchemyLibraryQueries:
    def __init__(
        self,
        db: Session,
        *,
        reader_queries: ReaderV5LibraryPresentationQueryPort,
    ) -> None:
        self._db = db
        self._reader_queries = reader_queries

    def _matching_statement(
        self,
        criteria: SmartShelfCriteria,
        *,
        user_id: str | None,
    ) -> _SmartShelfStatements | None:
        user = self._db.get(User, user_id) if user_id else None
        if user_id and user is None:
            return None
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
                    select(LibraryBookMetadata.book_id)
                    .correlate(LibraryBook)
                    .where(
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
                status_filters,
                context=context,
                user_id=user_id,
                reader_queries=self._reader_queries,
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
                    select(LibraryBookMetadata.book_id)
                    .correlate(LibraryBook)
                    .where(
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
                reader_queries=self._reader_queries,
                library_roots=resolve_library_roots(
                    self._db, criteria.filters, context
                ),
            )
            if dynamic is not None:
                predicates.append(dynamic)
        matched = (
            select(LibraryBook.id)
            .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
            .where(and_(*predicates))
            .order_by(LibraryBook.updated_at.desc(), LibraryBook.id.desc())
        )
        # Count in identity order before metadata existence checks. Traversing
        # the date index makes the same narrow metadata key lookup random for
        # every match on a cold mechanical disk.
        count_ids = book_ids_statement(predicates).order_by(LibraryBook.id).cte(
            "smart_shelf_identities"
        ).prefix_with("MATERIALIZED")
        count_matches = select(count_ids.c.id).select_from(count_ids).join(
            LibraryBookMetadata, LibraryBookMetadata.book_id.between(count_ids.c.id, count_ids.c.id),
        )
        if not criteria.included_book_ids:
            return _SmartShelfStatements(count_matches, matched)
        # Explicit inclusions follow rule matches, in their supplied order.
        matches = matched.order_by(None).cte("smart_shelf_matches").prefix_with("MATERIALIZED")
        combined = union_all(
            select(LibraryBook.id.label("id"), literal(0).label("kind"),
                   LibraryBook.updated_at.label("updated_at"), literal(0).label("ordinal"))
            .join(matches, matches.c.id == LibraryBook.id),
            select(LibraryBook.id.label("id"), literal(1).label("kind"),
                   literal(None).label("updated_at"),
                   case({book_id: position for position, book_id in enumerate(criteria.included_book_ids)}, value=LibraryBook.id).label("ordinal"))
            .where(
                LibraryBook.id.in_(criteria.included_book_ids),
                LibraryBook.visibility_state == "VISIBLE",
                book_visibility_predicate(context),
                ~LibraryBook.id.in_(select(matches.c.id)),
            ),
        ).subquery()
        included = select(LibraryBook.id).where(
            LibraryBook.id.in_(criteria.included_book_ids),
            LibraryBook.visibility_state == "VISIBLE", book_visibility_predicate(context),
        )
        all_ids = union(count_matches, included).subquery()
        ordered = select(combined.c.id).order_by(
            combined.c.kind, combined.c.ordinal, combined.c.updated_at.desc(), combined.c.id.desc()
        )
        return _SmartShelfStatements(select(all_ids.c.id), ordered)

    def matching_book_ids(
        self, criteria: SmartShelfCriteria, *, user_id: str | None,
    ) -> list[str]:
        statement = self._matching_statement(criteria, user_id=user_id)
        return list(self._db.scalars(statement.ordered)) if statement is not None else []

    def matching_book_page(
        self, criteria: SmartShelfCriteria, *, user_id: str | None,
        page: int, page_size: int,
    ) -> tuple[list[str], int]:
        statement = self._matching_statement(criteria, user_id=user_id)
        if statement is None:
            return [], 0
        total = int(self._db.scalar(select(func.count()).select_from(statement.identities.order_by(None).subquery())) or 0)
        if not total:
            return [], 0
        ids = list(self._db.scalars(statement.ordered.limit(page_size).offset((page - 1) * page_size)))
        return ids, total
