from enum import StrEnum


class WritePolicy(StrEnum):
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"


class LibraryControlState(StrEnum):
    DRAFT = "DRAFT"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REMOVING = "REMOVING"


class LibraryHealth(StrEnum):
    UNKNOWN = "UNKNOWN"
    HEALTHY = "HEALTHY"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


class GrantLevel(StrEnum):
    READ = "READ"
    CURATE = "CURATE"
    ADMIN = "ADMIN"


class IgnoreRuleKind(StrEnum):
    NAME = "NAME"
    PATH = "PATH"


class SourceEntryType(StrEnum):
    SYNTHETIC_ROOT = "SYNTHETIC_ROOT"
    DIRECTORY = "DIRECTORY"
    FILE = "FILE"
    SYMLINK = "SYMLINK"
    JUNCTION = "JUNCTION"
    SPECIAL = "SPECIAL"


class LayoutState(StrEnum):
    PRESENT = "PRESENT"
    INVALID = "INVALID"


class SlotState(StrEnum):
    ACTIVE = "ACTIVE"
    COLLIDING = "COLLIDING"
    RETIRED = "RETIRED"


class ScanState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ScanStage(StrEnum):
    DISCOVER = "DISCOVER"
    RECONCILE = "RECONCILE"
    FINALIZE = "FINALIZE"


class ScanFailureCode(StrEnum):
    ROOT_UNAVAILABLE = "ROOT_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    IO_ERROR = "IO_ERROR"
    DIRECTORY_CHANGED = "DIRECTORY_CHANGED"
    INVALID_RELATIVE_PATH = "INVALID_RELATIVE_PATH"
    ROOT_IDENTITY_CHANGED = "ROOT_IDENTITY_CHANGED"


class FullRescanReason(StrEnum):
    JOURNAL_CAPACITY = "JOURNAL_CAPACITY"
    DISCONNECTED = "DISCONNECTED"
    BACKEND_OVERFLOW = "BACKEND_OVERFLOW"
    UNTRUSTED = "UNTRUSTED"
    ROOT_CHANGED = "ROOT_CHANGED"
    COLLISION_RECHECK = "COLLISION_RECHECK"


class ReconcileIntentState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"


class ReconcileIntentPhase(StrEnum):
    EXECUTE = "EXECUTE"
    FOLD = "FOLD"


class ReconcileMovedEntryType(StrEnum):
    FILE = "FILE"
    DIRECTORY = "DIRECTORY"


class VersionKind(StrEnum):
    IMPLICIT = "IMPLICIT"
    DIRECTORY = "DIRECTORY"


class TopologyUnitKind(StrEnum):
    WORK_CONTAINER = "WORK_CONTAINER"
    AUDIOBOOK_WORK = "AUDIOBOOK_WORK"
    VERSION_CONTAINER = "VERSION_CONTAINER"
    FLAT_VOLUME = "FLAT_VOLUME"
    SINGLE_FILE_VOLUME = "SINGLE_FILE_VOLUME"
    MULTI_ASSET_VOLUME = "MULTI_ASSET_VOLUME"


class RevisionState(StrEnum):
    STAGING = "STAGING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ABANDONED = "ABANDONED"


class AssetRole(StrEnum):
    PRIMARY = "PRIMARY"
    AUDIO_TRACK = "AUDIO_TRACK"
    READER_SIDECAR = "READER_SIDECAR"


class AssetValidationState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    UNREADABLE = "UNREADABLE"


class ContentOriginKind(StrEnum):
    FULL_SCAN = "FULL_SCAN"
    RECONCILE = "RECONCILE"
    WATCHER = "WATCHER"


class SourceContentState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    INELIGIBLE = "INELIGIBLE"


class ManifestKind(StrEnum):
    REQUIRED = "REQUIRED"


class RequiredManifestState(StrEnum):
    STAGING = "STAGING"
    ACTIVE = "ACTIVE"


class RequiredDeliveryPolicy(StrEnum):
    ORIGINAL_SOURCE = "ORIGINAL_SOURCE"


class ContentProcessorKind(StrEnum):
    REQUIRED_MANIFEST = "REQUIRED_MANIFEST"
    REQUIRED_OPENING = "REQUIRED_OPENING"


class ProcessorState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"


class VolumeContentState(StrEnum):
    PENDING = "PENDING"
    READY = "READY"
    UNREADABLE = "UNREADABLE"


class AttachmentRole(StrEnum):
    COVER = "COVER"
    OPF = "OPF"
    CUE = "CUE"
    LRC = "LRC"


class OperationState(StrEnum):
    PREPARED = "PREPARED"
    FILESYSTEM_APPLIED = "FILESYSTEM_APPLIED"
    RECONCILE_QUEUED = "RECONCILE_QUEUED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ABANDONED_BY_LIBRARY_REMOVAL = "ABANDONED_BY_LIBRARY_REMOVAL"
    FAILED = "FAILED"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"


class AuditActorKind(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
