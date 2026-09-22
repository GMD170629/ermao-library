"""Bounded, deterministic file-move names and frozen source inventories."""

import unicodedata
from dataclasses import dataclass
from string import Formatter

from app.contracts.controlled_file_slots import is_controlled_file_slot
from app.contracts.file_operation import FileIdentity
from app.contracts.file_operation import FileOperationError as FileMoveError
from app.modules.library.domain.source_nodes import (
    SourceNodeRelativePath,
    parse_source_node_relative_path,
)

RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)}
)
TEMPLATE_FIELDS = frozenset({"author", "title", "resource_title", "index", "ext"})
MAX_FILES = 10_000
MAX_BYTES = 100 * 1024**3
MAX_TARGETS = 100


def collision_key(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def case_only_path(source: str, destination: str) -> bool:
    return (
        source != destination
        and source.rpartition("/")[0] == destination.rpartition("/")[0]
        and collision_key(source) == collision_key(destination)
    )


def validate_move_path(value: str) -> str:
    validate_portable_file_path(value)
    if any(is_controlled_file_slot(part) for part in value.split("/")):
        raise FileMoveError("RESERVED_OPERATION_PATH")
    return value


def validate_portable_file_path(value: str) -> str:
    if not isinstance(parse_source_node_relative_path(value), SourceNodeRelativePath):
        raise FileMoveError("INVALID_RELATIVE_PATH")
    if len(value.encode("utf-8")) > 4096:
        raise FileMoveError("PATH_TOO_LONG")
    if len(value.split("/")) > 128:
        raise FileMoveError("PATH_TOO_DEEP")
    for name in value.split("/"):
        if (
            any(ord(char) < 32 or char in '\\:*?"<>|' for char in name)
            or name.endswith((" ", "."))
            or len(name.encode("utf-8")) > 255
            or collision_key(name.split(".", 1)[0]) in RESERVED_NAMES
        ):
            raise FileMoveError("INVALID_FILE_NAME")
    return value


def render_move_template(template: str, values: dict[str, str]) -> str:
    """Only named scalar placeholders; substitutions cannot create directories."""
    result: list[str] = []
    try:
        parts = tuple(Formatter().parse(template))
    except ValueError as error:
        raise FileMoveError("INVALID_TEMPLATE") from error
    for literal, field, spec, conversion in parts:
        result.append(literal)
        if field is None:
            continue
        if field not in TEMPLATE_FIELDS or spec or conversion or field not in values:
            raise FileMoveError("INVALID_TEMPLATE")
        value = unicodedata.normalize("NFC", values[field])
        value = "".join(
            "_" if ord(char) < 32 or char in '/\\:*?"<>|' else char for char in value
        ).strip(" .")
        if not value:
            raise FileMoveError("MISSING_TEMPLATE_VALUE")
        result.append(value)
    return validate_move_path("".join(result))


@dataclass(frozen=True)
class MoveRequest:
    node_id: str
    destination_library_id: str
    destination_relative_path: str


@dataclass(frozen=True)
class MoveInventoryEntry:
    relative_path: str
    directory: bool
    identity: FileIdentity


@dataclass(frozen=True)
class MoveInventory:
    entries: tuple[MoveInventoryEntry, ...]
    file_count: int
    byte_count: int


def validate_move_set(
    sources: tuple[tuple[str, str], ...],
    destinations: tuple[tuple[str, str], ...],
    *,
    expanded: bool = False,
) -> None:
    limit = MAX_FILES if expanded else MAX_TARGETS
    if not 1 <= len(sources) <= limit or len(sources) != len(destinations):
        raise FileMoveError("INVALID_TARGET_COUNT")
    for library, path in (*sources, *destinations):
        if not library:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        validate_move_path(path)
    for collection in (sources, destinations):
        for index, (library, path) in enumerate(collection):
            key = collision_key(path)
            for other_library, other_path in collection[index + 1 :]:
                other = collision_key(other_path)
                if library == other_library and (
                    key == other
                    or key.startswith(other + "/")
                    or other.startswith(key + "/")
                ):
                    raise FileMoveError("OVERLAPPING_TARGETS")
    for library, path in sources:
        for other_library, destination in destinations:
            if library != other_library:
                continue
            key, other = collision_key(path), collision_key(destination)
            # Case-only renames require an explicit journalled intermediate slot.
            if (
                (key == other and not case_only_path(path, destination))
                or key.startswith(other + "/")
                or other.startswith(key + "/")
            ):
                raise FileMoveError("SOURCE_DESTINATION_OVERLAP")
