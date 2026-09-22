"""Reserved operation slots shared by source discovery and move validation."""

import re

_SLOT = re.compile(r"(?:\.ermao-mcp-[0-9a-f]{32}-(?:source|target)|\.ermao-delete-[0-9a-f]{32}-[0-9]+)\Z")


def is_controlled_file_slot(name: str) -> bool:
    return _SLOT.fullmatch(name.casefold()) is not None
