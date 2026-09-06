from __future__ import annotations

import ctypes
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyBudgetName,
    reader_safety_budget,
)
from app.modules.publications.domain.model import PublicationResourceTooLargeError
from app.modules.publications.infrastructure import mobi_adapter


class _NativeOptions(ctypes.Structure):
    """Native header ABI, independent of the Python adapter's declaration."""

    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("max_read_bytes", ctypes.c_uint32),
        ("max_file_bytes", ctypes.c_uint64),
    ]


def test_open_supplies_native_defaults_and_finite_generated_budget() -> None:
    library = MagicMock()
    library.ermao_mobi_abi_version.return_value = 1
    observed: list[tuple[int, int, int]] = []

    def defaults(address: object) -> None:
        options = ctypes.cast(
            cast(ctypes.c_void_p, address), ctypes.POINTER(_NativeOptions)
        ).contents
        options.struct_size = ctypes.sizeof(_NativeOptions)
        options.max_read_bytes = mobi_adapter._MAX_READ_BYTES
        options.max_file_bytes = 0

    def native_open(path: bytes, address: object, output: object) -> int:
        assert path == b"book.mobi"
        assert address is not None, "native open requires explicit bounded options"
        options = ctypes.cast(
            cast(ctypes.c_void_p, address), ctypes.POINTER(_NativeOptions)
        ).contents
        observed.append(
            (options.struct_size, options.max_read_bytes, options.max_file_bytes)
        )
        ctypes.cast(cast(ctypes.c_void_p, output), ctypes.POINTER(ctypes.c_void_p))[
            0
        ] = ctypes.c_void_p(1)
        return 0

    library.ermao_mobi_default_options.side_effect = defaults
    library.ermao_mobi_open.side_effect = native_open
    with patch.object(mobi_adapter.ctypes, "CDLL", return_value=library):
        core = mobi_adapter._MobiCore("test-native")
    for _ in range(2):
        assert core.open(Path("book.mobi")).value == 1

    budget = reader_safety_budget(ReaderSafetyBudgetName.ORIGINAL_MAX_BYTES)
    assert 0 < budget < 2**64 - 1
    assert (
        observed
        == [(ctypes.sizeof(_NativeOptions), mobi_adapter._MAX_READ_BYTES, budget)] * 2
    )
    assert library.ermao_mobi_default_options.call_count == 2
    options_type = library.ermao_mobi_open.argtypes[1]._type_
    assert ctypes.sizeof(options_type) == 16
    assert options_type.struct_size.offset == 0
    assert options_type.max_read_bytes.offset == 4
    assert options_type.max_file_bytes.offset == 8
    assert options_type._fields_ == _NativeOptions._fields_
    assert library.ermao_mobi_default_options.argtypes == [ctypes.POINTER(options_type)]
    assert library.ermao_mobi_default_options.restype is None


def test_open_preserves_native_limit_failure() -> None:
    library = MagicMock()
    library.ermao_mobi_abi_version.return_value = 1
    library.ermao_mobi_open.return_value = 9
    library.ermao_mobi_status_name.return_value = b"limit_exceeded"
    with patch.object(mobi_adapter.ctypes, "CDLL", return_value=library):
        core = mobi_adapter._MobiCore("test-native")
    with pytest.raises(PublicationResourceTooLargeError):
        core.open(Path("book.mobi"))
    library.ermao_mobi_open.assert_called_once()
    library.ermao_mobi_close.assert_not_called()
