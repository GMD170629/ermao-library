"""Compatibility CLI for the single portable dependency implementation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api-python"))
import json

from shuku_dependencies import installed_records

if __name__ == "__main__":
    print(json.dumps(installed_records(), sort_keys=True))
