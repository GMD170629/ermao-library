"""Descriptor-relative file access anchored at a configured library root."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.modules.library.application.source_browser import SourceAccessError
from app.modules.library.domain.source_nodes import (
    SourceNodeRelativePath,
    parse_source_node_relative_path,
)


@contextmanager
def open_library_file(root: Path, relative_path: str) -> Iterator[int]:
    if "\\" in relative_path or not isinstance(
        parse_source_node_relative_path(relative_path), SourceNodeRelativePath
    ):
        raise SourceAccessError("INVALID_RELATIVE_PATH")
    descriptors: list[int] = []
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(directory)
        parts = relative_path.split("/")
        for name in parts[:-1]:
            directory = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            descriptors.append(directory)
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        descriptors.append(descriptor)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise SourceAccessError("REGULAR_FILE_REQUIRED")
        yield descriptor
    except FileNotFoundError:
        raise
    except OSError as error:
        raise SourceAccessError("SOURCE_UNAVAILABLE") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
