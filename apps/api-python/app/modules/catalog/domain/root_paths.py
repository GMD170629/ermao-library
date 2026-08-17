"""Pure root observations and component-wise overlap rules.

Filesystem probing belongs to an infrastructure adapter.  The domain receives
only this typed observation and never imports ``pathlib``, ``os`` or ``Path``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.catalog.domain.errors import (
    InvalidRootObservation,
    RootOverlapConflict,
)


class RootRelation(StrEnum):
    EQUAL = "EQUAL"
    CANDIDATE_ANCESTOR = "CANDIDATE_ANCESTOR"
    CANDIDATE_DESCENDANT = "CANDIDATE_DESCENDANT"
    DISJOINT = "DISJOINT"


def _validate_components(components: tuple[str, ...]) -> None:
    if not isinstance(components, tuple) or not components:
        raise InvalidRootObservation("components")
    if any(
        not isinstance(component, str)
        or not component
        or component in {".", ".."}
        or "\x00" in component
        for component in components
    ):
        raise InvalidRootObservation("components")


@dataclass(frozen=True, slots=True)
class RootClaim:
    """Persistable comparison facts for one reserved library root."""

    root_path_key: str
    components: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.root_path_key.strip() or "\x00" in self.root_path_key:
            raise InvalidRootObservation("root_path_key")
        _validate_components(self.components)


@dataclass(frozen=True, slots=True)
class RegisteredRoot:
    """Durable root facts stored with a Library aggregate."""

    canonical_path: str
    root_path_key: str
    components: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.canonical_path.strip() or "\x00" in self.canonical_path:
            raise InvalidRootObservation("canonical_path")
        RootClaim(self.root_path_key, self.components)

    @property
    def claim(self) -> RootClaim:
        return RootClaim(self.root_path_key, self.components)


@dataclass(frozen=True, slots=True)
class RootObservation:
    """A canonical filesystem root produced by an injected preflight adapter."""

    canonical_path: str
    root_path_key: str
    components: tuple[str, ...]
    filesystem_identity: str
    writable: bool

    def __post_init__(self) -> None:
        if not self.canonical_path.strip() or "\x00" in self.canonical_path:
            raise InvalidRootObservation("canonical_path")
        if not self.filesystem_identity.strip() or "\x00" in self.filesystem_identity:
            raise InvalidRootObservation("filesystem_identity")
        if not isinstance(self.writable, bool):
            raise InvalidRootObservation("writable")
        RootClaim(self.root_path_key, self.components)

    @property
    def claim(self) -> RootClaim:
        return RootClaim(self.root_path_key, self.components)

    @property
    def registered_root(self) -> RegisteredRoot:
        return RegisteredRoot(
            canonical_path=self.canonical_path,
            root_path_key=self.root_path_key,
            components=self.components,
        )


def root_relation(candidate: RootClaim, existing: RootClaim) -> RootRelation:
    """Compare roots using complete path components, never string prefixes."""

    candidate_components = candidate.components
    existing_components = existing.components
    if candidate_components == existing_components:
        return RootRelation.EQUAL
    if (
        len(candidate_components) < len(existing_components)
        and existing_components[: len(candidate_components)] == candidate_components
    ):
        return RootRelation.CANDIDATE_ANCESTOR
    if (
        len(existing_components) < len(candidate_components)
        and candidate_components[: len(existing_components)] == existing_components
    ):
        return RootRelation.CANDIDATE_DESCENDANT
    return RootRelation.DISJOINT


def ensure_root_is_disjoint(
    candidate: RootClaim,
    existing_roots: tuple[RootClaim, ...],
) -> None:
    """Reject equal or nested roots while allowing unrelated roots."""

    for existing in existing_roots:
        if root_relation(candidate, existing) is not RootRelation.DISJOINT:
            raise RootOverlapConflict()
