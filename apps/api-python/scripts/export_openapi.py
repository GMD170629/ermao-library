from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from appv2.composition.api import create_app
from appv2.platform.config import Settings


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_openapi.py OUTPUT.json")
    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="shuku-openapi-") as temporary:
        app = create_app(Settings(storage_root=Path(temporary)))
        try:
            schema = app.openapi()
        finally:
            app.state.container.close()
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
