"""SQLAlchemy model package; importing it registers the complete fresh schema."""

from __future__ import annotations

from app.models.auth import (
    PasswordResetToken,
    ReaderBookmark,
    Session,
    User,
    UserLibraryAccess,
    UserPreference,
)
from app.models.import_pipeline import (
    DownloadTask,
    KindleSendTask,
    Source,
    SourceSearchRecord,
)
from app.models.library import (
    BookDetailPreference,
    ExternalMetadataCache,
    Library,
    LibraryBookFacet,
    LibraryFacet,
    LibraryOperation,
    LibraryReadableResourceFacet,
    ReadableResourceNavigationUnit,
    ReaderProgressMutation,
    ReaderResourceProgress,
)
from app.models.organize import (
    MetadataLookupTask,
    MetadataOpfQueueState,
    MetadataProviderExecution,
    MetadataProviderPipeline,
    MetadataSuggestion,
    MetadataWritebackOperation,
    MetadataWritebackPreparation,
    MetadataWritebackTarget,
    OrganizeJob,
    OrganizePolicy,
    OrganizeRun,
)
from app.models.settings import (
    QueueRuntimeState,
    ReaderBookPreference,
    ReaderPreference,
    ReaderProgressCursor,
    SystemEvent,
    SystemHealthRun,
    SystemSetting,
)
from app.models.shelf import Shelf, ShelfBook
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
    LibrarySourceNodeMetadata,
)
from app.modules.publications.infrastructure.models import PublicationNavigationCache
from app.modules.shelf.infrastructure.models import ShelfCollectionMembership

__all__ = [
    "BookDetailPreference",
    "DownloadTask",
    "ExternalMetadataCache",
    "KindleSendTask",
    "Library",
    "LibraryBook",
    "LibraryBookFacet",
    "LibraryBookMetadata",
    "LibraryFacet",
    "LibraryImportTask",
    "LibraryOperation",
    "LibraryReadableResource",
    "LibraryReadableResourceFacet",
    "LibraryReadableResourceMetadata",
    "LibraryResourceAsset",
    "LibraryResourceAssetMetadata",
    "LibrarySourceNode",
    "LibrarySourceNodeInterpretation",
    "LibrarySourceNodeMetadata",
    "MetadataLookupTask",
    "MetadataOpfQueueState",
    "MetadataProviderExecution",
    "MetadataProviderPipeline",
    "MetadataSuggestion",
    "MetadataWritebackOperation",
    "MetadataWritebackPreparation",
    "MetadataWritebackTarget",
    "OrganizeJob",
    "OrganizePolicy",
    "OrganizeRun",
    "PasswordResetToken",
    "PublicationNavigationCache",
    "QueueRuntimeState",
    "ReadableResourceNavigationUnit",
    "ReaderBookPreference",
    "ReaderBookmark",
    "ReaderPreference",
    "ReaderProgressCursor",
    "ReaderProgressMutation",
    "ReaderResourceProgress",
    "Session",
    "Shelf",
    "ShelfBook",
    "ShelfCollectionMembership",
    "Source",
    "SourceSearchRecord",
    "SystemEvent",
    "SystemHealthRun",
    "SystemSetting",
    "User",
    "UserLibraryAccess",
    "UserPreference",
]
