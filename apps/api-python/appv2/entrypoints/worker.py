from __future__ import annotations

import logging
import os
import socket
import time
import uuid

from appv2.composition.container import build_container
from appv2.composition.worker import WorkerRuntime
from appv2.platform.database.locks import advisory_lock
from appv2.platform.observability import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging()
    container = build_container()
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    runtime = WorkerRuntime(container=container, worker_id=worker_id)
    try:
        with advisory_lock(
            container.database.engine, container.settings.worker_lock_id
        ) as acquired:
            if not acquired:
                raise RuntimeError("another appv2 scheduler owns the advisory lock")
            logger.info("appv2 worker started as %s", worker_id)
            while True:
                handled = runtime.run_once()
                if not handled:
                    time.sleep(container.settings.worker_poll_seconds)
    finally:
        container.close()


if __name__ == "__main__":
    main()
