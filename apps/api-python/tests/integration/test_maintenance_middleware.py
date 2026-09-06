from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread, get_ident
from time import monotonic

import httpx
import pytest
from fastapi import FastAPI, Request, Response
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.orm import ORMExecuteState, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import Settings
from app.db.maintenance import (
    DATABASE_MAINTENANCE_RESTORE_VALUE,
    DATABASE_MAINTENANCE_SETTING_KEY,
)
from app.main import create_app
from app.models.settings import SystemSetting


@dataclass
class MaintenanceApp:
    app: FastAPI
    engine: Engine
    pool: QueuePool
    query_started: Event = field(default_factory=Event)
    reached: list[str] = field(default_factory=list)
    lifecycle: list[tuple[str, int, int]] = field(default_factory=list)

    def client(self, *, raise_app_exceptions: bool = True) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=self.app, raise_app_exceptions=raise_app_exceptions
            ),
            base_url="http://maintenance.test",
        )


@pytest.fixture
def maintenance_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[MaintenanceApp]:
    engine = create_engine(
        f"sqlite+pysqlite:///{(tmp_path / 'maintenance.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=2.0,
    )
    assert isinstance(engine.pool, QueuePool)
    SystemSetting.__table__.create(engine)
    settings = Settings(
        storage_root=str(tmp_path / "storage"),
        download_queue_enabled=False,
        kindle_send_queue_enabled=False,
    )
    app = create_app(settings, session_factory=sessionmaker(bind=engine))
    harness = MaintenanceApp(app=app, engine=engine, pool=engine.pool)

    # Observe the actual runtime sessions created by create_app's injected factory.
    # The ORM query and pool are real; no maintenance result is mocked.
    session_type = app.state.session_factory.class_
    original_init = session_type.__init__
    original_close = session_type.close

    def record_init(session: Session, **kwargs: object) -> None:
        original_init(session, **kwargs)
        harness.lifecycle.append(("create", id(session), get_ident()))

    def record_close(session: Session) -> None:
        try:
            original_close(session)
        finally:
            harness.lifecycle.append(("close", id(session), get_ident()))

    def record_query(execution: ORMExecuteState) -> None:
        harness.lifecycle.append(("query", id(execution.session), get_ident()))
        harness.query_started.set()

    monkeypatch.setattr(session_type, "__init__", record_init)
    monkeypatch.setattr(session_type, "close", record_close)
    event.listen(session_type, "do_orm_execute", record_query)

    @app.api_route(
        "/api/maintenance-probe",
        methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
    )
    async def probe(request: Request) -> Response:
        harness.reached.append(request.method)
        return Response(status_code=204)

    try:
        # ASGITransport does not run lifespan: no background workers or ports.
        yield harness
    finally:
        event.remove(session_type, "do_orm_execute", record_query)
        app.state.publication_navigation_runtime.close()
        engine.dispose()


def test_pool_exhaustion_keeps_event_loop_live_and_recovers(
    maintenance_app: MaintenanceApp,
) -> None:
    harness = maintenance_app
    held = Event()
    progress = Event()
    released = Event()
    observations: dict[str, object] = {}

    def occupy_pool() -> None:
        with Session(harness.engine) as blocker:
            blocker.scalar(select(SystemSetting.value))
            held.set()
            started = harness.query_started.wait(5.0)
            observations["query_started"] = started
            observations["progress_before_release"] = progress.wait(1.0)
        released.set()

    async def exercise() -> None:
        async with harness.client() as client:
            started_at = monotonic()

            async def heartbeat() -> None:
                await asyncio.sleep(0.05)
                observations["heartbeat_seconds"] = monotonic() - started_at
                observations["heartbeat_before_release"] = not released.is_set()

            async def read_probe() -> None:
                while not harness.query_started.is_set():
                    await asyncio.sleep(0.001)
                response = await client.get("/api/maintenance-probe")
                observations["probe_seconds"] = monotonic() - started_at
                observations["probe_before_release"] = not released.is_set()
                observations["probe_status"] = response.status_code
                observations["checked_out_at_probe"] = harness.pool.checkedout()
                await heartbeat_task
                progress.set()

            heartbeat_task = asyncio.create_task(heartbeat())
            probe_task = asyncio.create_task(read_probe())
            writes = [
                asyncio.create_task(client.post("/api/maintenance-probe"))
                for _ in range(2)
            ]
            responses = await asyncio.gather(*writes)
            await probe_task
            observations["write_statuses"] = [r.status_code for r in responses]
            observations["recovery_status"] = (
                await client.post("/api/maintenance-probe")
            ).status_code

    holder = Thread(target=occupy_pool, name="maintenance-pool-holder")
    holder.start()
    try:
        assert held.wait(5.0)
        assert harness.pool.checkedout() == 1
        asyncio.run(exercise())
    finally:
        progress.set()
        holder.join(timeout=7.0)
    observations["checked_out_after"] = harness.pool.checkedout()
    print("maintenance_pool_observation=" + json.dumps(observations, sort_keys=True))
    assert not holder.is_alive()
    assert released.is_set()
    assert observations["query_started"] is True
    assert observations["write_statuses"] == [204, 204]
    assert observations["recovery_status"] == 204
    assert observations["checked_out_after"] == 0
    assert observations["probe_status"] == 204
    assert observations["progress_before_release"] is True, observations
    assert observations["probe_before_release"] is True
    assert observations["heartbeat_before_release"] is True
    assert observations["checked_out_at_probe"] == 1


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_maintenance_blocks_writes_and_preserves_safe_methods(
    maintenance_app: MaintenanceApp, method: str, locale: str
) -> None:
    harness = maintenance_app
    with Session(harness.engine) as db, db.begin():
        db.add(
            SystemSetting(
                key=DATABASE_MAINTENANCE_SETTING_KEY,
                value=DATABASE_MAINTENANCE_RESTORE_VALUE,
            )
        )

    async def exercise() -> None:
        async with harness.client() as client:
            response = await client.request(
                method, "/api/maintenance-probe", headers={"Accept-Language": locale}
            )
            assert response.status_code == 503
            assert response.json() == {
                "ok": False,
                "error": {
                    "code": "DATABASE_MAINTENANCE",
                    "message": "DATABASE_MAINTENANCE",
                },
            }
            assert response.headers["Vary"] == "Cookie"
            assert harness.reached == []
            assert harness.pool.checkedout() == 0
            for safe_method in ("GET", "HEAD", "OPTIONS"):
                response = await client.request(safe_method, "/api/maintenance-probe")
                assert response.status_code == 204
                assert response.headers["Vary"] == "Cookie"
            assert harness.reached == ["GET", "HEAD", "OPTIONS"]

    asyncio.run(exercise())
    assert [phase for phase, _, _ in harness.lifecycle] == ["create", "query", "close"]
    assert len({session_id for _, session_id, _ in harness.lifecycle}) == 1
    thread_ids = {thread_id for _, _, thread_id in harness.lifecycle}
    assert len(thread_ids) == 1
    assert get_ident() not in thread_ids


def test_maintenance_query_error_closes_session_and_does_not_allow_write(
    maintenance_app: MaintenanceApp,
) -> None:
    harness = maintenance_app
    SystemSetting.__table__.drop(harness.engine)

    async def exercise() -> None:
        async with harness.client() as client:
            with pytest.raises(OperationalError):
                await client.post("/api/maintenance-probe")
        assert harness.pool.checkedout() == 0
        assert harness.reached == []
        assert [phase for phase, _, _ in harness.lifecycle] == [
            "create",
            "query",
            "close",
        ]
        async with harness.client(raise_app_exceptions=False) as client:
            response = await client.post("/api/maintenance-probe")
            assert response.status_code == 500
            assert response.text == "Internal Server Error"
        assert harness.pool.checkedout() == 0
        assert harness.reached == []
        SystemSetting.__table__.create(harness.engine)
        async with harness.client() as client:
            assert (await client.post("/api/maintenance-probe")).status_code == 204
        assert harness.pool.checkedout() == 0

    asyncio.run(exercise())


def test_pool_timeout_closes_session_and_recovers_after_release(
    maintenance_app: MaintenanceApp,
) -> None:
    harness = maintenance_app

    async def blocked_write() -> None:
        async with harness.client() as client:
            with pytest.raises(PoolTimeoutError):
                await client.post("/api/maintenance-probe")

    with Session(harness.engine) as blocker:
        blocker.scalar(select(SystemSetting.value))
        asyncio.run(blocked_write())
        assert harness.pool.checkedout() == 1
        assert harness.reached == []
        assert [phase for phase, _, _ in harness.lifecycle] == [
            "create",
            "query",
            "close",
        ]
    assert harness.pool.checkedout() == 0

    async def recovered_write() -> None:
        async with harness.client() as client:
            assert (await client.post("/api/maintenance-probe")).status_code == 204

    asyncio.run(recovered_write())
    assert harness.pool.checkedout() == 0
