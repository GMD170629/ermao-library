"""Compatibility CLI for the single portable dependency implementation."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api-python"))
import json

from shuku_dependencies import installed_records

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            installed_records(verify_contents=not args.no_verify), sort_keys=True
        )
    )
