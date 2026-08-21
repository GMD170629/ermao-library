"""Public application and domain contracts for the library capability."""

from app.modules.library.application.bookshelf import (
    BookshelfItemQueryPort,
    BookshelfItemSummary,
    ListBookshelfItems,
)
from app.modules.library.application.catalog import (
    CATALOG_FACET_KINDS,
    CatalogFacet,
    CatalogFacetPage,
    CatalogFile,
    CatalogQueryPort,
    CatalogVolume,
    CatalogWork,
    CatalogWorkFacet,
    CatalogWorkFilter,
    CatalogWorkPage,
    GetCatalogWork,
    ListCatalogFacets,
    ListCatalogWorks,
)
from app.modules.library.application.facet_references import (
    LibraryFacetReference,
    LibraryFacetReferenceQueryPort,
    WorkFacetReferences,
)
from app.modules.library.application.facet_sync import (
    PreparedWorkFacet,
    WorkFacetProjection,
    prepare_work_facet,
)
from app.modules.library.application.filter_ast import (
    FilterCondition,
    FilterExpression,
    InvalidFilterExpression,
    parse_filter_expression,
)
from app.modules.library.application.filter_options import (
    GetLibraryFilterSchema,
    LibraryFilterFieldDefinition,
    LibraryFilterOption,
    LibraryFilterOptionPage,
    LibraryFilterOptionSource,
    LibraryFilterQueryPort,
    LibraryFilterSchema,
    LibraryFilterSchemaOptions,
    SearchLibraryFilterOptions,
)
from app.modules.library.application.groupings import (
    LIBRARY_GROUPING_KINDS,
    LibraryGrouping,
    LibraryGroupingPage,
    LibraryGroupingQueryPort,
    LibraryGroupingWork,
    ListLibraryGroupings,
)
from app.modules.library.application.queries import (
    GetSmartShelfWorkIds,
    SmartShelfCriteria,
    SmartShelfQueryPort,
)
from app.modules.library.application.source_tree_ports import (
    AdapterIdentity,
    BookResourceRepositoryPort,
    InterpretationRecord,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    ReadableResourceRecord,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
)
from app.modules.library.application.work_list import (
    WorkListQuery,
    WorkListResult,
    parse_media_kinds,
)
from app.modules.library.application.commands.manage_source_tree import (
    ChangeLibraryOrganizationMode,
    DeleteSourceNode,
    DisableReadableResource,
    EnableReadableResource,
    ManagementResult,
    RelocateLibraryRoot,
)
from app.modules.library.domain.book_placement import (
    BookAnchorDecision,
    decide_book_anchor_for_resource,
    volumes_root_folder_creates_empty_book_on_discovery,
)
from app.modules.library.domain.facets import FACET_KINDS
from app.modules.library.domain.organization_modes import (
    OrganizationModeViolationCode,
    TargetLibraryOrganizationMode,
    parse_target_organization_mode,
)
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    AssetRole,
    ResourceEnablementState,
    ResourceImportState,
    meets_minimum_ready_assets,
    resource_is_openable,
)
from app.modules.library.domain.source_nodes import (
    InvalidSourceNodeRelativePathError,
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
    SourceNodeViolation,
    SourceNodeViolationCode,
    evaluate_path_key_occupancy,
    parse_source_node_relative_path,
)
from app.modules.library.presentation.schemas import WorkView
from app.modules.library.presentation.views import (
    _get_work as get_work,
)
from app.modules.library.presentation.views import (
    _preferred_work_cover_path as preferred_work_cover_path,
)
from app.modules.library.presentation.views import (
    _work_view as work_view,
)
from app.modules.library.presentation.views import (
    bookshelf_item_view,
    bookshelf_item_views,
)

__all__ = [
    "CATALOG_FACET_KINDS",
    "FACET_KINDS",
    "LIBRARY_GROUPING_KINDS",
    "AdapterIdentity",
    "AssetImportState",
    "AssetRole",
    "BookAnchorDecision",
    "BookResourceRepositoryPort",
    "BookshelfItemQueryPort",
    "BookshelfItemSummary",
    "CatalogFacet",
    "CatalogFacetPage",
    "CatalogFile",
    "CatalogQueryPort",
    "CatalogVolume",
    "CatalogWork",
    "CatalogWorkFacet",
    "CatalogWorkFilter",
    "CatalogWorkPage",
    "ChangeLibraryOrganizationMode",
    "DeleteSourceNode",
    "DisableReadableResource",
    "EnableReadableResource",
    "FilterCondition",
    "FilterExpression",
    "GetCatalogWork",
    "GetLibraryFilterSchema",
    "GetSmartShelfWorkIds",
    "InterpretationRecord",
    "InvalidFilterExpression",
    "InvalidSourceNodeRelativePathError",
    "LibraryConfigPort",
    "LibraryFacetReference",
    "LibraryFacetReferenceQueryPort",
    "LibraryFilterFieldDefinition",
    "LibraryFilterOption",
    "LibraryFilterOptionPage",
    "LibraryFilterOptionSource",
    "LibraryFilterQueryPort",
    "LibraryFilterSchema",
    "LibraryFilterSchemaOptions",
    "LibraryGrouping",
    "LibraryGroupingPage",
    "LibraryGroupingQueryPort",
    "LibraryGroupingWork",
    "LibrarySourceTreeConfig",
    "ListBookshelfItems",
    "ListCatalogFacets",
    "ListCatalogWorks",
    "ListLibraryGroupings",
    "ManagementResult",
    "ObservedSourceEntry",
    "OrganizationModeViolationCode",
    "PreparedWorkFacet",
    "ReadableResourceRecord",
    "RelocateLibraryRoot",
    "ResourceEnablementState",
    "ResourceImportState",
    "SearchLibraryFilterOptions",
    "SmartShelfCriteria",
    "SmartShelfQueryPort",
    "SourceNodePhysicalKind",
    "SourceNodeRecord",
    "SourceNodeRelativePath",
    "SourceNodeRepositoryPort",
    "SourceNodeViolation",
    "SourceNodeViolationCode",
    "TargetLibraryOrganizationMode",
    "WorkFacetProjection",
    "WorkFacetReferences",
    "WorkListQuery",
    "WorkListResult",
    "WorkView",
    "bookshelf_item_view",
    "bookshelf_item_views",
    "decide_book_anchor_for_resource",
    "evaluate_path_key_occupancy",
    "get_work",
    "meets_minimum_ready_assets",
    "parse_filter_expression",
    "parse_media_kinds",
    "parse_source_node_relative_path",
    "parse_target_organization_mode",
    "preferred_work_cover_path",
    "prepare_work_facet",
    "resource_is_openable",
    "volumes_root_folder_creates_empty_book_on_discovery",
    "work_view",
]
