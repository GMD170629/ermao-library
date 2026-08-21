"""HTTP mappers for typed library filter application results."""

from __future__ import annotations

from app.modules.library.application.filter_options import (
    LibraryFilterOption as ApplicationFilterOption,
)
from app.modules.library.application.filter_options import (
    LibraryFilterOptionPage as ApplicationFilterOptionPage,
)
from app.modules.library.application.filter_options import (
    LibraryFilterSchema as ApplicationFilterSchema,
)
from app.modules.library.presentation.schemas import (
    FilterFieldDefinition,
    FilterOption,
    FilterOptionsPayload,
    FilterSchemaPayload,
    FilterSuggestionOption,
)


def _filter_option(option: ApplicationFilterOption) -> FilterOption:
    return FilterOption(
        value=option.value,
        label=option.label,
        count=option.count,
        rootPath=option.root_path,
    )


def filter_schema_payload(schema: ApplicationFilterSchema) -> FilterSchemaPayload:
    return FilterSchemaPayload(
        fields=[
            FilterFieldDefinition(
                key=field.key,
                label=field.label,
                group=field.group,
                type=field.field_type,
                operators=list(field.operators),
                optionSource=field.option_source,
                allowCustom=bool(field.allow_custom),
                unit=field.unit,
                valueScale=field.value_scale,
                options=[_filter_option(option) for option in options],
            )
            for field, options in schema.fields
        ],
        maxConditions=schema.max_conditions,
    )


def filter_options_payload(
    page: ApplicationFilterOptionPage,
) -> FilterOptionsPayload:
    return FilterOptionsPayload(
        source=page.source,
        query=page.query,
        options=[
            FilterSuggestionOption(
                value=option.value,
                label=option.label,
                count=option.count or 0,
            )
            for option in page.options
        ],
        hasMore=page.has_more,
        indexReady=page.index_ready,
    )
