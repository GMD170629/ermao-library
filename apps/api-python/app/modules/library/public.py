from app.modules.library.application.bulk_operations import (
    BulkBookAccessError,
    BulkBookAuthorizationError,
    BulkBookOperationResult,
    BulkMetadataCommand,
    BulkShelfMembershipCommand,
    ExecuteBulkMetadata,
    ExecuteBulkShelfMembership,
    InvalidBulkBookOperationError,
)
from app.modules.library.application.file_move_operations import (
    FileMoveOperationPort,
    move_plan_result,
    move_progress_result,
    require_plan_access,
)
from app.modules.library.application.file_move_plans import (
    MoveActor,
    PrepareFileMovePlan,
)
from app.modules.library.application.imported_book_metadata import (
    BookIdentificationRequests,
    IdentifyImportedBook,
)
from app.modules.library.application.metadata_effects import MetadataSideEffectPolicy
from app.modules.library.application.metadata_file_targets import (
    MetadataFileTarget,
    MetadataFileTargetPort,
)
from app.modules.library.application.metadata_ownership import (
    protected_fields as protected_metadata_fields,
)
from app.modules.library.application.metadata_patches import (
    ApplyMetadataPatches,
    GetMetadataSchema,
    MetadataPatchActor,
    MetadataPatchPort,
)
from app.modules.library.application.source_browser import (
    BrowseSourceNodes,
    SourceAccessError,
    SourceBrowserPort,
    SourceLocation,
)
from app.modules.library.domain.file_moves import (
    FileMoveError,
    MoveRequest,
    render_move_template,
)
from app.modules.library.domain.file_moves import (
    collision_key as file_path_collision_key,
)
from app.modules.library.domain.metadata_patch import (
    MetadataChange,
    MetadataPatchError,
    MetadataTarget,
    MetadataValue,
)

"""Stable public contracts for the Book/ReadableResource capability."""

from app.modules.library.application.book_covers import (
    BookCoverCandidate,
    BookCoverQueryPort,
    BookCoverSource,
    ResolveBookCoverCandidates,
)
from app.modules.library.application.book_list import (
    BookListProjection,
    BookListQuery,
    BookListResult,
)
from app.modules.library.application.bookshelf import (
    BookshelfItemQueryPort,
    BookshelfItemSummary,
    ListBookshelfItems,
)
from app.modules.library.application.catalog import (
    CATALOG_FACET_KINDS,
    CatalogAsset,
    CatalogBook,
    CatalogBookFacet,
    CatalogBookFilter,
    CatalogBookPage,
    CatalogFacet,
    CatalogFacetPage,
    CatalogLibrary,
    CatalogLibraryQueryPort,
    CatalogQueryPort,
    CatalogResource,
    GetCatalogBook,
    ListCatalogBooks,
    ListCatalogFacets,
)
from app.modules.library.application.commands.manage_source_tree import DeleteSourceNode
from app.modules.library.application.facet_references import (
    BookFacetReferences,
    LibraryFacetReference,
    LibraryFacetReferenceQueryPort,
)
from app.modules.library.application.facet_sync import (
    BookFacetProjection,
    PreparedBookFacet,
    prepare_book_facet,
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
    LibraryGroupingBook,
    LibraryGroupingPage,
    LibraryGroupingQueryPort,
    ListLibraryGroupings,
)
from app.modules.library.application.queries import (
    GetSmartShelfBookIds,
    SmartShelfCriteria,
    SmartShelfQueryPort,
)
from app.modules.library.application.source_tree_ports import (
    AdapterIdentity,
    BookResourceRepositoryPort,
    DirectoryAssetResult,
    DirectoryImportMember,
    InterpretationRecord,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    ReadableResourceRecord,
    ResourceAssetMetadataInput,
    ResourceCoverState,
    ResourceNavigationUnitInput,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
)
from app.modules.library.domain.asset_titles import (
    AssetTitleCandidate,
    resolve_asset_display_titles,
)
from app.modules.library.domain.book_placement import (
    BookAnchorDecision,
    decide_book_anchor_for_resource,
    resource_root_folder_creates_empty_book_on_discovery,
)
from app.modules.library.domain.facets import FACET_KINDS
from app.modules.library.domain.layout import LibraryOrganizationMode
from app.modules.library.domain.organization_modes import (
    OrganizationModeViolationCode,
    TargetLibraryOrganizationMode,
    parse_target_organization_mode,
)
from app.modules.library.domain.readable_resource_anchors import (
    ReadableResourceAnchorViolationCode,
    ReadableResourceTopologyError,
    audiobook_resource_owns_path,
    is_asset_path_within_resource_scope,
    is_resource_anchor_within_book_scope,
    is_same_or_descendant_path,
    is_strict_descendant_path,
    is_transparent_audiobook_directory_name,
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
    SourceNodeTopologyError,
    SourceNodeViolation,
    SourceNodeViolationCode,
    evaluate_path_key_occupancy,
    parse_source_node_relative_path,
)

__all__ = [
    "CATALOG_FACET_KINDS",
    "FACET_KINDS",
    "LIBRARY_GROUPING_KINDS",
    "AdapterIdentity",
    "ApplyMetadataPatches",
    "AssetImportState",
    "AssetRole",
    "AssetTitleCandidate",
    "BookAnchorDecision",
    "BookCoverCandidate",
    "BookCoverQueryPort",
    "BookCoverSource",
    "BookFacetProjection",
    "BookFacetReferences",
    "BookIdentificationRequests",
    "BookListProjection",
    "BookListQuery",
    "BookListResult",
    "BookResourceRepositoryPort",
    "BookshelfItemQueryPort",
    "BookshelfItemSummary",
    "BrowseSourceNodes",
    "BulkBookAccessError",
    "BulkBookAuthorizationError",
    "BulkBookOperationResult",
    "BulkMetadataCommand",
    "BulkShelfMembershipCommand",
    "CatalogAsset",
    "CatalogBook",
    "CatalogBookFacet",
    "CatalogBookFilter",
    "CatalogBookPage",
    "CatalogFacet",
    "CatalogFacetPage",
    "CatalogLibrary",
    "CatalogLibraryQueryPort",
    "CatalogQueryPort",
    "CatalogResource",
    "DeleteSourceNode",
    "DirectoryAssetResult",
    "DirectoryImportMember",
    "ExecuteBulkMetadata",
    "ExecuteBulkShelfMembership",
    "FileMoveError",
    "FileMoveOperationPort",
    "FilterCondition",
    "FilterExpression",
    "GetCatalogBook",
    "GetLibraryFilterSchema",
    "GetMetadataSchema",
    "GetSmartShelfBookIds",
    "IdentifyImportedBook",
    "InterpretationRecord",
    "InvalidBulkBookOperationError",
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
    "LibraryGroupingBook",
    "LibraryGroupingPage",
    "LibraryGroupingQueryPort",
    "LibraryOrganizationMode",
    "LibrarySourceTreeConfig",
    "ListBookshelfItems",
    "ListCatalogBooks",
    "ListCatalogFacets",
    "ListLibraryGroupings",
    "MetadataChange",
    "MetadataFileTarget",
    "MetadataFileTargetPort",
    "MetadataPatchActor",
    "MetadataPatchError",
    "MetadataPatchPort",
    "MetadataSideEffectPolicy",
    "MetadataTarget",
    "MetadataValue",
    "MoveActor",
    "MoveRequest",
    "ObservedSourceEntry",
    "OrganizationModeViolationCode",
    "PrepareFileMovePlan",
    "PreparedBookFacet",
    "ReadableResourceAnchorViolationCode",
    "ReadableResourceRecord",
    "ReadableResourceTopologyError",
    "ResolveBookCoverCandidates",
    "ResourceAssetMetadataInput",
    "ResourceCoverState",
    "ResourceEnablementState",
    "ResourceImportState",
    "ResourceNavigationUnitInput",
    "SearchLibraryFilterOptions",
    "SmartShelfCriteria",
    "SmartShelfQueryPort",
    "SourceAccessError",
    "SourceBrowserPort",
    "SourceLocation",
    "SourceNodePhysicalKind",
    "SourceNodeRecord",
    "SourceNodeRelativePath",
    "SourceNodeRepositoryPort",
    "SourceNodeTopologyError",
    "SourceNodeViolation",
    "SourceNodeViolationCode",
    "TargetLibraryOrganizationMode",
    "audiobook_resource_owns_path",
    "decide_book_anchor_for_resource",
    "evaluate_path_key_occupancy",
    "file_path_collision_key",
    "is_asset_path_within_resource_scope",
    "is_resource_anchor_within_book_scope",
    "is_same_or_descendant_path",
    "is_strict_descendant_path",
    "is_transparent_audiobook_directory_name",
    "meets_minimum_ready_assets",
    "move_plan_result",
    "move_progress_result",
    "parse_filter_expression",
    "parse_source_node_relative_path",
    "parse_target_organization_mode",
    "prepare_book_facet",
    "protected_metadata_fields",
    "render_move_template",
    "require_plan_access",
    "resolve_asset_display_titles",
    "resource_is_openable",
    "resource_root_folder_creates_empty_book_on_discovery",
]
