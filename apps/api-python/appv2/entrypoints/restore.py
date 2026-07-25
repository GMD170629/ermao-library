from __future__ import annotations

from appv2.composition.container import build_container
from appv2.platform.observability import configure_logging


def main() -> None:
    configure_logging()
    container = build_container()
    try:
        container.restore_service.run_once()
    finally:
        container.close()


if __name__ == "__main__":
    main()
