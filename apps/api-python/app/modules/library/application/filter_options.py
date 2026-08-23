"""Application contracts for library filter schema and bounded suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from app.core.authorization import AuthorizationContext

LibraryFilterOptionSource = Literal["authors", "tags", "series"]
LibraryFilterFieldType = Literal["text", "select", "number", "date", "boolean"]

TEXT_OPERATORS = (
    "contains",
    "not_contains",
    "equals",
    "not_equals",
    "starts_with",
    "ends_with",
    "is_empty",
    "is_not_empty",
)
SELECT_OPERATORS = ("equals", "not_equals", "is_empty", "is_not_empty")
NUMBER_OPERATORS = (
    "equals",
    "not_equals",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "between",
    "is_empty",
    "is_not_empty",
)
DATE_OPERATORS = (
    "equals",
    "not_equals",
    "after",
    "on_or_after",
    "before",
    "on_or_before",
    "between",
    "is_empty",
    "is_not_empty",
)
BOOLEAN_OPERATORS = ("is_true", "is_false")


@dataclass(frozen=True)
class LibraryFilterOption:
    value: str
    label: str
    count: int | None = None
    root_path: str | None = None


@dataclass(frozen=True)
class LibraryFilterFieldDefinition:
    key: str
    label: str
    group: str
    field_type: LibraryFilterFieldType
    operators: tuple[str, ...]
    option_source: str | None = None
    allow_custom: bool | None = None
    unit: str | None = None
    value_scale: int | None = None


@dataclass(frozen=True)
class LibraryFilterSchemaOptions:
    formats: tuple[LibraryFilterOption, ...]
    import_statuses: tuple[LibraryFilterOption, ...]
    origins: tuple[LibraryFilterOption, ...]
    libraries: tuple[LibraryFilterOption, ...]
    shelves: tuple[LibraryFilterOption, ...]


@dataclass(frozen=True)
class LibraryFilterSchema:
    fields: tuple[
        tuple[LibraryFilterFieldDefinition, tuple[LibraryFilterOption, ...]], ...
    ]
    max_conditions: int


@dataclass(frozen=True)
class LibraryFilterOptionPage:
    source: LibraryFilterOptionSource
    query: str
    options: tuple[LibraryFilterOption, ...]
    has_more: bool
    index_ready: bool


class LibraryFilterQueryPort(Protocol):
    def schema_options(
        self, context: AuthorizationContext
    ) -> LibraryFilterSchemaOptions: ...

    def search_options(
        self,
        context: AuthorizationContext,
        *,
        source: LibraryFilterOptionSource,
        query: str,
        limit: int,
    ) -> LibraryFilterOptionPage: ...


FILTER_FIELD_DEFINITIONS = (
    LibraryFilterFieldDefinition("title", "书名", "图书元数据", "text", TEXT_OPERATORS),
    LibraryFilterFieldDefinition(
        "author",
        "作者",
        "图书元数据",
        "select",
        SELECT_OPERATORS,
        "authors",
        True,
    ),
    LibraryFilterFieldDefinition(
        "tag", "标签", "图书元数据", "select", SELECT_OPERATORS, "tags", True
    ),
    LibraryFilterFieldDefinition(
        "series",
        "丛书",
        "图书元数据",
        "select",
        SELECT_OPERATORS,
        "series",
        True,
    ),
    LibraryFilterFieldDefinition(
        "description", "简介", "图书元数据", "text", TEXT_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "seriesIndex", "丛书序号", "图书元数据", "number", NUMBER_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "metadataQuality",
        "元数据完整度",
        "图书元数据",
        "number",
        NUMBER_OPERATORS,
        unit="%",
    ),
    LibraryFilterFieldDefinition(
        "resourceTitle", "资源名称", "资源元数据", "text", TEXT_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "narrator", "演播者", "资源元数据", "text", TEXT_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "mediaKind",
        "读物类型",
        "格式与文件",
        "select",
        SELECT_OPERATORS,
        "mediaKinds",
    ),
    LibraryFilterFieldDefinition(
        "format",
        "文件格式",
        "格式与文件",
        "select",
        SELECT_OPERATORS,
        "formats",
        True,
    ),
    LibraryFilterFieldDefinition(
        "fileSize",
        "文件总大小",
        "格式与文件",
        "number",
        NUMBER_OPERATORS,
        unit="MB",
        value_scale=1048576,
    ),
    LibraryFilterFieldDefinition(
        "pageCount", "页数", "格式与文件", "number", NUMBER_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "chapterCount", "章节数", "格式与文件", "number", NUMBER_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "duration",
        "时长",
        "格式与文件",
        "number",
        NUMBER_OPERATORS,
        unit="分钟",
        value_scale=60000,
    ),
    LibraryFilterFieldDefinition(
        "resourceCount", "资源数量", "格式与文件", "number", NUMBER_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "readingStatus",
        "阅读状态",
        "阅读与整理",
        "select",
        SELECT_OPERATORS,
        "readingStatuses",
    ),
    LibraryFilterFieldDefinition(
        "progress", "阅读进度", "阅读与整理", "number", NUMBER_OPERATORS, unit="%"
    ),
    LibraryFilterFieldDefinition(
        "lastReadAt", "最近阅读时间", "阅读与整理", "date", DATE_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "publicationStatus",
        "连载状态",
        "阅读与整理",
        "select",
        SELECT_OPERATORS,
        "publicationStatuses",
    ),
    LibraryFilterFieldDefinition(
        "trackingStatus",
        "追踪状态",
        "阅读与整理",
        "select",
        SELECT_OPERATORS,
        "trackingStatuses",
    ),
    LibraryFilterFieldDefinition(
        "organizeStatus",
        "整理状态",
        "阅读与整理",
        "select",
        SELECT_OPERATORS,
        "organizeStatuses",
    ),
    LibraryFilterFieldDefinition(
        "organized", "已完成整理", "阅读与整理", "boolean", BOOLEAN_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "hasCover", "有封面", "阅读与整理", "boolean", BOOLEAN_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "shelf", "所在普通书架", "来源与归档", "select", SELECT_OPERATORS, "shelves"
    ),
    LibraryFilterFieldDefinition(
        "library",
        "书库",
        "来源与归档",
        "select",
        SELECT_OPERATORS,
        "libraries",
    ),
    LibraryFilterFieldDefinition(
        "sourcePath", "原始文件路径", "来源与归档", "text", TEXT_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "origin",
        "加入来源",
        "来源与归档",
        "select",
        SELECT_OPERATORS,
        "origins",
        True,
    ),
    LibraryFilterFieldDefinition(
        "importStatus",
        "导入状态",
        "来源与归档",
        "select",
        SELECT_OPERATORS,
        "importStatuses",
        True,
    ),
    LibraryFilterFieldDefinition(
        "createdAt", "加入时间", "来源与归档", "date", DATE_OPERATORS
    ),
    LibraryFilterFieldDefinition(
        "updatedAt", "最后更新时间", "来源与归档", "date", DATE_OPERATORS
    ),
)

STATIC_OPTIONS: dict[str, tuple[LibraryFilterOption, ...]] = {
    "readingStatuses": (
        LibraryFilterOption("UNREAD", "未开始"),
        LibraryFilterOption("READING", "进行中"),
        LibraryFilterOption("FINISHED", "已完成"),
    ),
    "publicationStatuses": (
        LibraryFilterOption("UNKNOWN", "未知"),
        LibraryFilterOption("ONGOING", "连载中"),
        LibraryFilterOption("COMPLETED", "已完结"),
        LibraryFilterOption("HIATUS", "暂停"),
        LibraryFilterOption("CANCELLED", "已取消"),
    ),
    "trackingStatuses": (
        LibraryFilterOption("NOT_TRACKING", "未追踪"),
        LibraryFilterOption("TRACKING", "追踪中"),
        LibraryFilterOption("PAUSED", "已暂停"),
        LibraryFilterOption("IGNORED", "已忽略"),
    ),
    "organizeStatuses": (
        LibraryFilterOption("PENDING", "待整理"),
        LibraryFilterOption("REVIEWING", "待确认"),
        LibraryFilterOption("APPLIED", "已应用"),
        LibraryFilterOption("FAILED", "失败"),
    ),
    "mediaKinds": (
        LibraryFilterOption("EBOOK", "电子书"),
        LibraryFilterOption("COMIC", "漫画"),
        LibraryFilterOption("AUDIOBOOK", "有声书"),
    ),
}


@dataclass(frozen=True)
class GetLibraryFilterSchema:
    query: LibraryFilterQueryPort

    def execute(self, context: AuthorizationContext) -> LibraryFilterSchema:
        dynamic = self.query.schema_options(context)
        options_by_source = {
            **STATIC_OPTIONS,
            "authors": (),
            "tags": (),
            "series": (),
            "formats": dynamic.formats,
            "importStatuses": dynamic.import_statuses,
            "origins": dynamic.origins,
            "libraries": dynamic.libraries,
            "shelves": dynamic.shelves,
        }
        return LibraryFilterSchema(
            fields=tuple(
                (field, options_by_source.get(field.option_source or "", ()))
                for field in FILTER_FIELD_DEFINITIONS
            ),
            max_conditions=30,
        )


@dataclass(frozen=True)
class SearchLibraryFilterOptions:
    query: LibraryFilterQueryPort

    def execute(
        self,
        context: AuthorizationContext,
        *,
        source: LibraryFilterOptionSource,
        query: str,
        limit: int,
    ) -> LibraryFilterOptionPage:
        normalized_query = query.strip()
        if len(normalized_query) > 100:
            raise ValueError("library filter query must be at most 100 characters")
        if not 1 <= limit <= 50:
            raise ValueError("library filter option limit must be between 1 and 50")
        return self.query.search_options(
            context,
            source=source,
            query=normalized_query,
            limit=limit,
        )
