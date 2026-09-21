"""Discover explicitly associated sidecars without following arbitrary file paths."""

import os
from pathlib import Path, PurePosixPath

from app.infrastructure.sidecar_paths import same_stem_source_names, sidecar_opf_paths
from app.modules.library.application.file_move_plans import MoveDestination, MoveSource
from app.modules.library.domain.file_moves import (
    MAX_FILES,
    FileMoveError,
    collision_key,
    validate_move_path,
)
from app.modules.library.infrastructure.source_file_access import (
    open_library_directory,
    open_library_file,
)
from app.modules.metadata.public import (
    MAX_OPF_BYTES,
    OpfMetadataError,
    parse_opf_metadata,
)


def move_companion_paths(
    source: MoveSource, destination: MoveDestination, *, directory: bool
) -> tuple[tuple[str, str], ...]:
    source_path = Path(source.relative_path)
    target_path = Path(destination.relative_path)
    parent = source_path.parent.as_posix()
    parent = "" if parent == "." else parent
    with open_library_directory(source.root, parent) as descriptor:
        names = os.listdir(descriptor)
    if len(names) > MAX_FILES:
        raise FileMoveError("INVENTORY_LIMIT")
    by_key = {collision_key(name): name for name in names}
    if len(by_key) != len(names):
        raise FileMoveError("PORTABLE_NAME_COLLISION")
    candidates = sidecar_opf_paths(source_path, directory=directory)
    own_opf = source_path.with_suffix(".opf")
    paths: dict[str, str] = {}
    for candidate in candidates:
        if directory and candidate.is_relative_to(source_path):
            continue  # The directory inventory already contains these files.
        name = by_key.get(collision_key(candidate.name))
        if name is None:
            continue
        actual = candidate.with_name(name)
        if actual == source_path:
            continue
        if candidate != own_opf:
            # metadata.opf / directory-name.opf can describe multiple sibling
            # resources. Moving one resource cannot take another one's metadata.
            raise FileMoveError("SHARED_SIDECAR_REQUIRES_DIRECTORY_MOVE")
        peers = same_stem_source_names(tuple(names), source_path.name)
        if peers != (source_path.name,):
            raise FileMoveError("AMBIGUOUS_SIDECAR")
        target_opf = target_path.with_suffix(".opf")
        if (
            actual.as_posix() != target_opf.as_posix()
            or source.library_id != destination.library_id
        ):
            paths[actual.as_posix()] = target_opf.as_posix()
        with open_library_file(source.root, actual.as_posix()) as descriptor:
            if os.fstat(descriptor).st_size > MAX_OPF_BYTES:
                raise FileMoveError("SIDECAR_TOO_LARGE")
            data = bytearray()
            while chunk := os.read(
                descriptor, min(65536, MAX_OPF_BYTES + 1 - len(data))
            ):
                data.extend(chunk)
                if len(data) > MAX_OPF_BYTES:
                    raise FileMoveError("SIDECAR_TOO_LARGE")
        try:
            metadata = parse_opf_metadata(bytes(data))
        except OpfMetadataError as error:
            raise FileMoveError("SIDECAR_INVALID") from error
        if metadata.cover_href:
            href = PurePosixPath(metadata.cover_href)
            if (
                len(href.parts) != 1
                or "\\" in metadata.cover_href
                or ":" in metadata.cover_href
            ):
                raise FileMoveError("SIDECAR_COVER_REQUIRES_DIRECTORY_MOVE")
            validate_move_path(href.as_posix())
            cover_name = by_key.get(collision_key(href.name))
            if cover_name is None:
                raise FileMoveError("SIDECAR_COVER_MISSING")
            other_opfs = [
                name
                for name in names
                if Path(name).suffix.lower() == ".opf" and name != actual.name
            ]
            if other_opfs:
                raise FileMoveError("SHARED_COVER_REQUIRES_DIRECTORY_MOVE")
            cover = actual.parent / cover_name
            target_cover = target_opf.parent / cover_name
            if cover != target_cover or source.library_id != destination.library_id:
                paths[cover.as_posix()] = target_cover.as_posix()
    return tuple(sorted(paths.items()))
