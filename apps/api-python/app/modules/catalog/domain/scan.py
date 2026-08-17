"""Pure contracts for generation scans and topology materialization."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
from typing import TypeAlias

from app.modules.catalog.domain.admission import AdmissionRejectionReason
from app.modules.catalog.domain.model import (
    AssetCandidate,
    OrganizationMode,
    PathComparison,
    SourceFormat,
    SourceKind,
    ViolationCode,
    VolumeCandidate,
    _validate_relative_path,
)
from app.modules.catalog.domain.ordering import comparison_path, natural_path_key

MAX_AUDIO_TRACKS = 10_000
MAX_STAGE_ROWS = 500
MAX_STRUCTURAL_ENTRIES_PER_UNIT = 20_001


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


class RevisionState(StrEnum):
    STAGING = "STAGING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ABANDONED = "ABANDONED"


class TopologyUnitKind(StrEnum):
    WORK_CONTAINER = "WORK_CONTAINER"
    AUDIOBOOK_WORK = "AUDIOBOOK_WORK"
    VERSION_CONTAINER = "VERSION_CONTAINER"
    FLAT_VOLUME = "FLAT_VOLUME"
    SINGLE_FILE_VOLUME = "SINGLE_FILE_VOLUME"
    MULTI_ASSET_VOLUME = "MULTI_ASSET_VOLUME"


class VersionKind(StrEnum):
    IMPLICIT = "IMPLICIT"
    DIRECTORY = "DIRECTORY"


class ReadingMorphology(StrEnum):
    REFLOWABLE = "REFLOWABLE"
    PDF = "PDF"
    COMIC = "COMIC"
    AUDIO = "AUDIO"


class AssetRole(StrEnum):
    PRIMARY = "PRIMARY"
    AUDIO_TRACK = "AUDIO_TRACK"


class ScanObservationCode(StrEnum):
    SOURCE_CHANGED_DURING_SCAN = "SOURCE_CHANGED_DURING_SCAN"
    PATH_NAME_UNSUPPORTED = "PATH_NAME_UNSUPPORTED"
    UNSUPPORTED_ENTRY_TYPE = "UNSUPPORTED_ENTRY_TYPE"
    TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED = "TOPOLOGY_UNIT_ENTRY_LIMIT_EXCEEDED"


ScanDiagnosticCode: TypeAlias = (
    ViolationCode | AdmissionRejectionReason | ScanObservationCode
)


class CatalogScanError(RuntimeError):
    code = "CATALOG_SCAN_ERROR"

    def __init__(self) -> None:
        super().__init__(self.code)


class ScanNotFound(CatalogScanError):
    code = "SCAN_NOT_FOUND"


class ScanConflict(CatalogScanError):
    code = "SCAN_CONFLICT"


class ScanLeaseLost(CatalogScanError):
    code = "SCAN_LEASE_LOST"


class ScanStale(CatalogScanError):
    code = "SCAN_STALE"


class ScanRootIdentityChanged(CatalogScanError):
    code = "SCAN_ROOT_IDENTITY_CHANGED"


class ScanAuthorizationDenied(CatalogScanError):
    code = "SCAN_AUTHORIZATION_DENIED"


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _structure_key(path: tuple[str, ...], comparison: PathComparison) -> str:
    """Encode a comparison path without an ambiguous separator."""

    _validate_relative_path(path, "structure path")
    components = comparison_path(path, comparison)
    return "".join(
        f"{len(component.encode('utf-8'))}:{component.encode('utf-8').hex()}"
        for component in components
    )


def _sortable_component(value: str, comparison: PathComparison) -> str:
    """Encode the frozen natural-order tuple into SQLite-BINARY-sortable text."""

    component_key = natural_path_key((value,), comparison)[0]
    tokens, normalized, preserved = component_key
    encoded_tokens: list[str] = []
    for token_kind, number, text in tokens:
        if token_kind == 0:
            digits = str(number)
            encoded_tokens.append(f"0{len(digits):04d}:{digits}!")
        else:
            encoded_tokens.append(f"1{text.encode('utf-8').hex()}!")
    return (
        "".join(encoded_tokens)
        + " "
        + normalized.encode("utf-8").hex()
        + "!"
        + preserved.hex()
        + "!"
    )


def reading_morphology(source_formats: tuple[SourceFormat, ...]) -> ReadingMorphology:
    if not isinstance(source_formats, tuple):
        raise TypeError("source_formats must be a tuple")
    if not source_formats:
        raise ValueError("source_formats must be non-empty")
    if any(not isinstance(value, SourceFormat) for value in source_formats):
        raise TypeError("source_formats must contain SourceFormat values")
    formats = frozenset(source_formats)
    if formats <= {SourceFormat.MP3, SourceFormat.M4A, SourceFormat.M4B}:
        return ReadingMorphology.AUDIO
    if len(formats) != 1:
        raise ValueError("a non-audio volume must have exactly one format")
    source_format = next(iter(formats))
    if source_format is SourceFormat.PDF:
        return ReadingMorphology.PDF
    if source_format in {
        SourceFormat.CBZ,
        SourceFormat.CBR,
        SourceFormat.RAR,
        SourceFormat.ZIP,
    }:
        return ReadingMorphology.COMIC
    return ReadingMorphology.REFLOWABLE


def collision_unit_path(
    mode: OrganizationMode, path: tuple[str, ...]
) -> tuple[str, ...]:
    """Return the smallest topology unit invalidated by one slot collision."""

    if not isinstance(mode, OrganizationMode):
        raise TypeError("mode must be an OrganizationMode")
    _validate_relative_path(path, "collision path")
    if mode in {OrganizationMode.FLAT, OrganizationMode.AUDIOBOOK}:
        return path[:1]
    if len(path) <= 2:
        return path
    return path[:3]


@dataclass(frozen=True, slots=True)
class ScanDiagnostic:
    code: ScanDiagnosticCode
    unit_path: tuple[str, ...]
    related_paths: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.code, (ViolationCode, AdmissionRejectionReason, ScanObservationCode)
        ):
            raise TypeError("code must be a typed scan diagnostic code")
        _validate_relative_path(self.unit_path, "unit_path")
        if not isinstance(self.related_paths, tuple):
            raise TypeError("related_paths must be a tuple")
        for path in self.related_paths:
            _validate_relative_path(path, "related path")


@dataclass(frozen=True, slots=True)
class WorkProjectionPlan:
    root_path: tuple[str, ...]
    structure_key: str
    source_name: str
    sort_key: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.root_path, "work root_path")
        for value, field_name in (
            (self.structure_key, "structure_key"),
            (self.sort_key, "sort_key"),
        ):
            _require_identifier(value, field_name)
        if not isinstance(self.source_name, str):
            raise TypeError("source_name must be a string")
        if self.source_name != self.root_path[-1]:
            raise ValueError("work source_name must preserve the root component")


@dataclass(frozen=True, slots=True)
class VersionProjectionPlan:
    work_path: tuple[str, ...]
    root_path: tuple[str, ...] | None
    kind: VersionKind
    structure_key: str
    source_name: str | None
    sort_key: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.work_path, "version work_path")
        if not isinstance(self.kind, VersionKind):
            raise TypeError("kind must be a VersionKind")
        _require_identifier(self.structure_key, "structure_key")
        if not isinstance(self.sort_key, str):
            raise TypeError("sort_key must be a string")
        if self.kind is VersionKind.IMPLICIT:
            if self.root_path is not None or self.source_name is not None:
                raise ValueError("implicit versions cannot own a directory")
            if self.sort_key:
                raise ValueError("implicit versions have no source sort key")
            return
        if self.root_path is None or self.source_name is None:
            raise ValueError("directory versions require root and source name")
        _validate_relative_path(self.root_path, "version root_path")
        if not isinstance(self.source_name, str):
            raise TypeError("source_name must be a string")
        if (
            len(self.root_path) != len(self.work_path) + 1
            or self.root_path[:-1] != self.work_path
        ):
            raise ValueError("version root must be a direct child of work")
        if self.source_name != self.root_path[-1]:
            raise ValueError("version source_name must preserve the root component")
        _require_identifier(self.sort_key, "sort_key")


@dataclass(frozen=True, slots=True)
class VolumeProjectionPlan:
    work_path: tuple[str, ...]
    version_path: tuple[str, ...] | None
    root_path: tuple[str, ...]
    source_kind: SourceKind
    reading_morphology: ReadingMorphology
    structure_key: str
    source_name: str
    sort_key: str

    def __post_init__(self) -> None:
        _validate_relative_path(self.work_path, "volume work_path")
        _validate_relative_path(self.root_path, "volume root_path")
        if not isinstance(self.source_kind, SourceKind):
            raise TypeError("source_kind must be a SourceKind")
        if not isinstance(self.reading_morphology, ReadingMorphology):
            raise TypeError("reading_morphology must be a ReadingMorphology")
        if self.version_path is not None:
            _validate_relative_path(self.version_path, "volume version_path")
            if (
                len(self.version_path) != len(self.work_path) + 1
                or self.version_path[:-1] != self.work_path
                or len(self.root_path) != len(self.version_path) + 1
                or self.root_path[:-1] != self.version_path
            ):
                raise ValueError("volume root must be a direct child of version")
        elif not (
            self.root_path == self.work_path
            or (
                len(self.root_path) == len(self.work_path) + 1
                and self.root_path[:-1] == self.work_path
            )
        ):
            raise ValueError("implicit-version volume must belong to work")
        for value, field_name in (
            (self.structure_key, "structure_key"),
            (self.sort_key, "sort_key"),
        ):
            _require_identifier(value, field_name)
        if not isinstance(self.source_name, str):
            raise TypeError("source_name must be a string")
        if self.source_name != self.root_path[-1]:
            raise ValueError("volume source_name must preserve the root component")


@dataclass(frozen=True, slots=True)
class AssetMembershipPlan:
    volume_path: tuple[str, ...]
    source_path: tuple[str, ...]
    source_format: SourceFormat
    role: AssetRole
    disc_number: int
    asset_order: int
    required_for_reading: bool = True

    def __post_init__(self) -> None:
        _validate_relative_path(self.volume_path, "volume_path")
        _validate_relative_path(self.source_path, "source_path")
        for value, field_name in (
            (self.disc_number, "disc_number"),
            (self.asset_order, "asset_order"),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
        if self.disc_number < 0 or self.asset_order < 0:
            raise ValueError("disc_number and asset_order must be non-negative")
        if not isinstance(self.source_format, SourceFormat):
            raise TypeError("source_format must be a SourceFormat")
        if not isinstance(self.role, AssetRole):
            raise TypeError("role must be an AssetRole")
        if not isinstance(self.required_for_reading, bool):
            raise TypeError("required_for_reading must be a bool")
        if (
            not (
                len(self.source_path) > len(self.volume_path)
                and self.source_path[: len(self.volume_path)] == self.volume_path
            )
            and self.source_path != self.volume_path
        ):
            raise ValueError("asset source must belong to its volume")


TopologyProjectionPlan: TypeAlias = (
    WorkProjectionPlan
    | VersionProjectionPlan
    | VolumeProjectionPlan
    | AssetMembershipPlan
)


@dataclass(frozen=True, slots=True)
class TopologyUnitPlan:
    unit_key: str
    unit_kind: TopologyUnitKind
    owner_path: tuple[str, ...]
    unit_root_path: tuple[str, ...]
    rows: tuple[TopologyProjectionPlan, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.unit_key, "unit_key")
        if not isinstance(self.unit_kind, TopologyUnitKind):
            raise TypeError("unit_kind must be a TopologyUnitKind")
        if not self.unit_key.startswith(f"{self.unit_kind.value}:"):
            raise ValueError("unit_key must be namespaced by unit_kind")
        _validate_relative_path(self.owner_path, "owner_path")
        _validate_relative_path(self.unit_root_path, "unit_root_path")
        if not isinstance(self.rows, tuple):
            raise TypeError("rows must be a tuple")
        if not self.rows:
            raise ValueError("a topology unit must contain projection rows")
        if any(
            not isinstance(
                row,
                (
                    WorkProjectionPlan,
                    VersionProjectionPlan,
                    VolumeProjectionPlan,
                    AssetMembershipPlan,
                ),
            )
            for row in self.rows
        ):
            raise TypeError("rows must contain typed topology projections")
        if self.owner_path != self.unit_root_path:
            raise ValueError("topology-v1 unit owner and root must match")
        self._validate_shape()

    def _validate_shape(self) -> None:
        row_types = tuple(type(row) for row in self.rows)
        if self.unit_kind is TopologyUnitKind.WORK_CONTAINER:
            if row_types != (WorkProjectionPlan,):
                raise ValueError("work containers contain only their Work projection")
            work = self.rows[0]
            if not isinstance(work, WorkProjectionPlan) or (
                work.root_path != self.owner_path
            ):
                raise ValueError("work container projection must match its owner")
            return
        if self.unit_kind is TopologyUnitKind.VERSION_CONTAINER:
            if row_types != (VersionProjectionPlan,):
                raise ValueError(
                    "version containers contain only their Version projection"
                )
            version = self.rows[0]
            if not isinstance(version, VersionProjectionPlan) or (
                version.root_path != self.owner_path
            ):
                raise ValueError("version container projection must match its owner")
            return
        if self.unit_kind is TopologyUnitKind.FLAT_VOLUME:
            self._validate_flat_shape()
            return
        if self.unit_kind is TopologyUnitKind.AUDIOBOOK_WORK:
            self._validate_audiobook_shape()
            return
        self._validate_volume_shape()

    def _validate_flat_shape(self) -> None:
        if len(self.rows) < 4 or not isinstance(self.rows[0], WorkProjectionPlan):
            raise ValueError("flat units start with Work, Version, and Volume rows")
        work = self.rows[0]
        version = self.rows[1]
        volume = self.rows[2]
        assets = self.rows[3:]
        if (
            not isinstance(version, VersionProjectionPlan)
            or not isinstance(volume, VolumeProjectionPlan)
            or any(not isinstance(asset, AssetMembershipPlan) for asset in assets)
            or work.root_path != self.owner_path
            or version.kind is not VersionKind.IMPLICIT
            or version.work_path != self.owner_path
            or volume.work_path != self.owner_path
            or volume.version_path is not None
            or volume.root_path != self.owner_path
            or volume.source_kind is not SourceKind.SINGLE_FILE
            or len(assets) != 1
            or any(
                isinstance(asset, AssetMembershipPlan)
                and (
                    asset.volume_path != self.owner_path
                    or asset.source_path != self.owner_path
                    or asset.role is not AssetRole.PRIMARY
                )
                for asset in assets
            )
        ):
            raise ValueError("flat unit projections must share their one owned source")

    def _validate_volume_shape(self) -> None:
        if len(self.rows) < 2 or not isinstance(self.rows[0], VolumeProjectionPlan):
            raise ValueError("VOLUMES child units start with a Volume projection")
        volume = self.rows[0]
        assets = self.rows[1:]
        expected_kind = (
            SourceKind.SINGLE_FILE
            if self.unit_kind is TopologyUnitKind.SINGLE_FILE_VOLUME
            else SourceKind.MULTI_ASSET_AUDIO
        )
        if (
            volume.root_path != self.owner_path
            or volume.source_kind is not expected_kind
            or (
                expected_kind is SourceKind.MULTI_ASSET_AUDIO
                and volume.reading_morphology is not ReadingMorphology.AUDIO
            )
            or any(not isinstance(asset, AssetMembershipPlan) for asset in assets)
            or any(
                isinstance(asset, AssetMembershipPlan)
                and (
                    asset.volume_path != self.owner_path
                    or (
                        expected_kind is SourceKind.SINGLE_FILE
                        and asset.role is not AssetRole.PRIMARY
                    )
                    or (
                        expected_kind is SourceKind.MULTI_ASSET_AUDIO
                        and asset.role is not AssetRole.AUDIO_TRACK
                    )
                )
                for asset in assets
            )
            or (expected_kind is SourceKind.SINGLE_FILE and len(assets) != 1)
        ):
            raise ValueError("volume unit projections must belong to their owner")

    def _validate_audiobook_shape(self) -> None:
        if (
            len(self.rows) < 4
            or not isinstance(self.rows[0], WorkProjectionPlan)
            or not isinstance(self.rows[1], VersionProjectionPlan)
            or self.rows[0].root_path != self.owner_path
            or self.rows[1].kind is not VersionKind.IMPLICIT
            or self.rows[1].work_path != self.owner_path
        ):
            raise ValueError(
                "audiobook units start with their Work and implicit Version"
            )
        if (
            sum(isinstance(row, AssetMembershipPlan) for row in self.rows)
            > MAX_AUDIO_TRACKS
        ):
            raise ValueError("an AUDIOBOOK work exceeds 10,000 tracks")
        current_volume: VolumeProjectionPlan | None = None
        current_assets: list[AssetMembershipPlan] = []
        for row in self.rows[2:]:
            if isinstance(row, VolumeProjectionPlan):
                if current_volume is not None:
                    self._validate_audiobook_assets(current_volume, current_assets)
                if (
                    row.work_path != self.owner_path
                    or row.version_path is not None
                    or row.reading_morphology is not ReadingMorphology.AUDIO
                ):
                    raise ValueError("audiobook Volume must belong to the owned Work")
                current_volume = row
                current_assets = []
            elif (
                not isinstance(row, AssetMembershipPlan)
                or current_volume is None
                or row.volume_path != current_volume.root_path
            ):
                raise ValueError("audiobook assets must follow their owned Volume")
            else:
                current_assets.append(row)
        if current_volume is None:
            raise ValueError("audiobook units require at least one Volume")
        self._validate_audiobook_assets(current_volume, current_assets)

    @staticmethod
    def _validate_audiobook_assets(
        volume: VolumeProjectionPlan,
        assets: list[AssetMembershipPlan],
    ) -> None:
        if not assets or len(assets) > MAX_AUDIO_TRACKS:
            raise ValueError("audiobook Volumes require between 1 and 10,000 assets")
        if volume.source_kind is SourceKind.SINGLE_FILE:
            valid = (
                len(assets) == 1
                and assets[0].role is AssetRole.PRIMARY
                and assets[0].source_path == volume.root_path
            )
        else:
            valid = all(asset.role is AssetRole.AUDIO_TRACK for asset in assets)
        if (
            not valid
            or reading_morphology(tuple(asset.source_format for asset in assets))
            is not ReadingMorphology.AUDIO
        ):
            raise ValueError("audiobook asset roles must match Volume ownership")


@dataclass(frozen=True, slots=True)
class TopologyActivationGroup:
    group_key: str
    units: tuple[TopologyUnitPlan, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.group_key, "group_key")
        if not isinstance(self.units, tuple):
            raise TypeError("units must be a tuple")
        if not self.units:
            raise ValueError("an activation group must contain topology units")
        if any(not isinstance(unit, TopologyUnitPlan) for unit in self.units):
            raise TypeError("units must contain TopologyUnitPlan values")
        if len({unit.unit_key for unit in self.units}) != len(self.units):
            raise ValueError("an activation group cannot repeat a topology unit")


@dataclass(frozen=True, slots=True)
class TopologyStageBatch:
    first_row: int
    rows: tuple[TopologyProjectionPlan, ...]
    complete: bool

    def __post_init__(self) -> None:
        if isinstance(self.first_row, bool) or not isinstance(self.first_row, int):
            raise TypeError("first_row must be an integer")
        if not isinstance(self.rows, tuple):
            raise TypeError("rows must be a tuple")
        if any(
            not isinstance(
                row,
                (
                    WorkProjectionPlan,
                    VersionProjectionPlan,
                    VolumeProjectionPlan,
                    AssetMembershipPlan,
                ),
            )
            for row in self.rows
        ):
            raise TypeError("rows must contain typed topology projections")
        if self.first_row < 0 or not self.rows or len(self.rows) > MAX_STAGE_ROWS:
            raise ValueError("invalid topology staging batch")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be a bool")


def iter_stage_batches(
    plan: TopologyUnitPlan, *, maximum_rows: int = MAX_STAGE_ROWS
) -> Iterator[TopologyStageBatch]:
    if maximum_rows <= 0 or maximum_rows > MAX_STAGE_ROWS:
        raise ValueError("maximum_rows must be between 1 and 500")
    iterator = iter(plan.rows)
    first_row = 0
    current = tuple(islice(iterator, maximum_rows))
    while current:
        following = tuple(islice(iterator, maximum_rows))
        yield TopologyStageBatch(
            first_row=first_row,
            rows=current,
            complete=not following,
        )
        first_row += len(current)
        current = following


def _work_row(path: tuple[str, ...], comparison: PathComparison) -> WorkProjectionPlan:
    return WorkProjectionPlan(
        root_path=path,
        structure_key=_structure_key(path, comparison),
        source_name=path[-1],
        sort_key=_sortable_component(path[-1], comparison),
    )


def _version_row(
    path: tuple[str, ...] | None,
    *,
    work_path: tuple[str, ...],
    comparison: PathComparison,
) -> VersionProjectionPlan:
    if path is None:
        return VersionProjectionPlan(
            work_path=work_path,
            root_path=None,
            kind=VersionKind.IMPLICIT,
            structure_key=_structure_key(work_path, comparison) + ":implicit",
            source_name=None,
            sort_key="",
        )
    return VersionProjectionPlan(
        work_path=work_path,
        root_path=path,
        kind=VersionKind.DIRECTORY,
        structure_key=_structure_key(path, comparison),
        source_name=path[-1],
        sort_key=_sortable_component(path[-1], comparison),
    )


def _volume_rows(
    candidate: VolumeCandidate, comparison: PathComparison
) -> tuple[TopologyProjectionPlan, ...]:
    morphology = reading_morphology(
        tuple(asset.source_format for asset in candidate.assets)
    )
    volume = VolumeProjectionPlan(
        work_path=candidate.work_path,
        version_path=candidate.version_path,
        root_path=candidate.volume_path,
        source_kind=candidate.source_kind,
        reading_morphology=morphology,
        structure_key=_structure_key(candidate.volume_path, comparison),
        source_name=candidate.volume_path[-1],
        sort_key=_sortable_component(candidate.volume_path[-1], comparison),
    )
    role = (
        AssetRole.PRIMARY
        if candidate.source_kind is SourceKind.SINGLE_FILE
        else AssetRole.AUDIO_TRACK
    )
    assets = tuple(
        _asset_row(candidate.volume_path, asset, role=role)
        for asset in candidate.assets
    )
    return (volume, *assets)


def _asset_row(
    volume_path: tuple[str, ...], asset: AssetCandidate, *, role: AssetRole
) -> AssetMembershipPlan:
    return AssetMembershipPlan(
        volume_path=volume_path,
        source_path=asset.path,
        source_format=asset.source_format,
        role=role,
        disc_number=asset.disc_number,
        asset_order=asset.order,
    )


def _unit(
    *,
    unit_kind: TopologyUnitKind,
    owner_path: tuple[str, ...],
    unit_root_path: tuple[str, ...],
    rows: tuple[TopologyProjectionPlan, ...],
    comparison: PathComparison,
) -> TopologyUnitPlan:
    return TopologyUnitPlan(
        unit_key=f"{unit_kind.value}:{_structure_key(owner_path, comparison)}",
        unit_kind=unit_kind,
        owner_path=owner_path,
        unit_root_path=unit_root_path,
        rows=rows,
    )


def build_topology_units(
    mode: OrganizationMode,
    candidates: tuple[VolumeCandidate, ...],
    *,
    path_comparison: PathComparison,
) -> tuple[TopologyUnitPlan, ...]:
    """Flatten activation groups for read-only inspection and diagnostics."""

    return tuple(
        unit
        for group in build_topology_activation_groups(
            mode, candidates, path_comparison=path_comparison
        )
        for unit in group.units
    )


def build_topology_activation_groups(
    mode: OrganizationMode,
    candidates: tuple[VolumeCandidate, ...],
    *,
    path_comparison: PathComparison,
) -> tuple[TopologyActivationGroup, ...]:
    """Map layout candidates to atomically activated publication groups."""

    if not isinstance(mode, OrganizationMode):
        raise TypeError("mode must be an OrganizationMode")
    if not isinstance(path_comparison, PathComparison):
        raise TypeError("path_comparison must be a PathComparison")
    if not isinstance(candidates, tuple):
        raise TypeError("candidates must be a tuple")
    if any(not isinstance(candidate, VolumeCandidate) for candidate in candidates):
        raise TypeError("candidates must contain VolumeCandidate values")
    ordered = tuple(
        sorted(
            candidates,
            key=lambda candidate: natural_path_key(
                candidate.volume_path, path_comparison
            ),
        )
    )
    if mode is OrganizationMode.FLAT:
        return tuple(
            TopologyActivationGroup(
                group_key=f"FLAT:{_structure_key(candidate.volume_path, path_comparison)}",
                units=(
                    _unit(
                        unit_kind=TopologyUnitKind.FLAT_VOLUME,
                        owner_path=candidate.volume_path,
                        unit_root_path=candidate.volume_path,
                        rows=(
                            _work_row(candidate.work_path, path_comparison),
                            _version_row(
                                None,
                                work_path=candidate.work_path,
                                comparison=path_comparison,
                            ),
                            *_volume_rows(candidate, path_comparison),
                        ),
                        comparison=path_comparison,
                    ),
                ),
            )
            for candidate in ordered
        )
    if mode is OrganizationMode.VOLUMES:
        return _build_volumes_units(ordered, path_comparison)
    return _build_audiobook_units(ordered, path_comparison)


def _build_volumes_units(
    candidates: tuple[VolumeCandidate, ...], comparison: PathComparison
) -> tuple[TopologyActivationGroup, ...]:
    groups: list[TopologyActivationGroup] = []
    for candidate in candidates:
        if candidate.version_path is None:
            raise ValueError("VOLUMES candidates require a version path")
        work = _work_row(candidate.work_path, comparison)
        version = _version_row(
            candidate.version_path,
            work_path=candidate.work_path,
            comparison=comparison,
        )
        work_unit = _unit(
            unit_kind=TopologyUnitKind.WORK_CONTAINER,
            owner_path=candidate.work_path,
            unit_root_path=candidate.work_path,
            rows=(work,),
            comparison=comparison,
        )
        version_unit = _unit(
            unit_kind=TopologyUnitKind.VERSION_CONTAINER,
            owner_path=candidate.version_path,
            unit_root_path=candidate.version_path,
            rows=(version,),
            comparison=comparison,
        )
        unit_kind = (
            TopologyUnitKind.SINGLE_FILE_VOLUME
            if candidate.source_kind is SourceKind.SINGLE_FILE
            else TopologyUnitKind.MULTI_ASSET_VOLUME
        )
        volume_unit = _unit(
            unit_kind=unit_kind,
            owner_path=candidate.volume_path,
            unit_root_path=candidate.volume_path,
            rows=_volume_rows(candidate, comparison),
            comparison=comparison,
        )
        groups.append(
            TopologyActivationGroup(
                group_key=(
                    f"VOLUMES:{_structure_key(candidate.volume_path, comparison)}"
                ),
                units=(work_unit, version_unit, volume_unit),
            )
        )
    return tuple(groups)


def _build_audiobook_units(
    candidates: tuple[VolumeCandidate, ...], comparison: PathComparison
) -> tuple[TopologyActivationGroup, ...]:
    grouped: dict[tuple[str, ...], list[VolumeCandidate]] = {}
    preserved_paths: dict[tuple[str, ...], tuple[str, ...]] = {}
    for candidate in candidates:
        key = comparison_path(candidate.work_path, comparison)
        grouped.setdefault(key, []).append(candidate)
        preserved_paths.setdefault(key, candidate.work_path)
    groups: list[TopologyActivationGroup] = []
    for key in sorted(grouped, key=lambda value: natural_path_key(value, comparison)):
        work_path = preserved_paths[key]
        volumes = tuple(grouped[key])
        if sum(len(volume.assets) for volume in volumes) > MAX_AUDIO_TRACKS:
            raise ValueError("an AUDIOBOOK work exceeds 10,000 tracks")
        rows: list[TopologyProjectionPlan] = [
            _work_row(work_path, comparison),
            _version_row(None, work_path=work_path, comparison=comparison),
        ]
        for volume in volumes:
            rows.extend(_volume_rows(volume, comparison))
        groups.append(
            TopologyActivationGroup(
                group_key=f"AUDIOBOOK:{_structure_key(work_path, comparison)}",
                units=(
                    _unit(
                        unit_kind=TopologyUnitKind.AUDIOBOOK_WORK,
                        owner_path=work_path,
                        unit_root_path=work_path,
                        rows=tuple(rows),
                        comparison=comparison,
                    ),
                ),
            )
        )
    return tuple(groups)


__all__ = [
    "MAX_AUDIO_TRACKS",
    "MAX_STAGE_ROWS",
    "MAX_STRUCTURAL_ENTRIES_PER_UNIT",
    "AssetMembershipPlan",
    "AssetRole",
    "CatalogScanError",
    "ReadingMorphology",
    "RevisionState",
    "ScanAuthorizationDenied",
    "ScanConflict",
    "ScanDiagnostic",
    "ScanDiagnosticCode",
    "ScanLeaseLost",
    "ScanNotFound",
    "ScanObservationCode",
    "ScanRootIdentityChanged",
    "ScanStage",
    "ScanStale",
    "ScanState",
    "TopologyActivationGroup",
    "TopologyProjectionPlan",
    "TopologyStageBatch",
    "TopologyUnitKind",
    "TopologyUnitPlan",
    "VersionKind",
    "VersionProjectionPlan",
    "VolumeProjectionPlan",
    "WorkProjectionPlan",
    "build_topology_activation_groups",
    "build_topology_units",
    "collision_unit_path",
    "iter_stage_batches",
    "reading_morphology",
]
