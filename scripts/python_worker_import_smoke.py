# ruff: noqa: S106

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api-python"
sys.path.insert(0, str(API_ROOT))

from appv2.composition.container import build_container  # noqa: E402
from appv2.platform.config import Settings  # noqa: E402
from appv2.platform.database.migrations import migrate  # noqa: E402


def account_id(container: object) -> uuid.UUID:
    accounts = container.accounts  # type: ignore[attr-defined]
    if accounts.setup_required():
        return accounts.setup(
            email=f"worker-smoke-{uuid.uuid4().hex}@example.com",
            display_name="Worker Smoke",
            password="worker-smoke-password-at-least-20-characters",
            locale="en-US",
        ).account.id
    users, total = accounts.list_users(page=1, page_size=1)
    if total < 1:
        raise RuntimeError("account repository reported an inconsistent user count")
    return users[0].id


def main() -> None:
    database_url = os.getenv("APPV2_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "APPV2_TEST_DATABASE_URL or DATABASE_URL must point to "
            "an isolated PostgreSQL 18 database"
        )
    with TemporaryDirectory(prefix="shuku-appv2-worker-import-") as temporary:
        root = Path(temporary)
        monitor_root = root / "monitor"
        storage_root = root / "storage"
        monitor_root.mkdir()
        source = monitor_root / "worker-smoke.txt"
        source.write_text("appv2 worker import smoke\n", encoding="utf-8")
        settings = Settings(
            database_url=database_url,
            session_secret="worker-smoke-session-secret-at-least-32-characters",
            storage_root=storage_root,
            monitor_root=monitor_root,
            environment="test",
        )
        migrate(settings.database_dsn, API_ROOT)
        container = build_container(settings)
        try:
            actor_id = account_id(container)
            accepted = container.ingestion.enqueue(
                source_path=str(source),
                requested_by=actor_id,
                idempotency_key=f"worker-smoke-{uuid.uuid4().hex}",
            )
            if not container.ingestion_worker.run_once("worker-import-smoke"):
                raise RuntimeError("worker did not claim the queued import")
            jobs, _ = container.ingestion.list_jobs(page=1, page_size=100, status=None)
            job = next(item for item in jobs if item.id == accepted.job_id)
            if job.status != "completed" or job.result_id is None:
                raise RuntimeError(f"worker import did not complete: {job}")
            target = container.reading.bootstrap(
                user_id=actor_id,
                edition_id=job.result_id,
            )[0]
            if target.format != "txt":
                raise RuntimeError(f"unexpected imported format: {target.format}")
            print("appv2 worker import smoke ok")
        finally:
            container.close()


if __name__ == "__main__":
    main()
