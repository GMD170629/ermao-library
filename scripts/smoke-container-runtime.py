#!/usr/bin/env python3
"""Explicit real-image D1 acceptance, isolated Docker volume; no default test collection."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path


def docker(*args: str) -> str:
    return subprocess.check_output(
        ["docker", *args],
        text=True,
        encoding="utf-8",
        timeout=180,
        stderr=subprocess.STDOUT if args[0] == "logs" else None,
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--upgrade-from", help="existing image to replace using the same test volume"
    )
    parser.add_argument("--fault-boundaries", action="store_true")
    parser.add_argument("--update-boundaries", action="store_true")
    parser.add_argument("--output-dir", default="artifacts/startup-acceptance")
    args = parser.parse_args()
    name = "shuku-d1-" + uuid.uuid4().hex[:10]
    volume = name + "-data"
    books = name + "-books"
    docker("volume", "create", volume)
    docker("volume", "create", books)
    running = False
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    log_index = 0
    business = "/app/storage/dependencies/python/bin/python"

    def execute(code: str, python: str = "/usr/local/bin/python3.11") -> str:
        return docker("exec", name, python, "-c", code)

    def start(
        *,
        without_dependency_seed: bool = False,
        require_worker: bool = True,
        writable_books: bool = False,
        image: str | None = None,
    ) -> None:
        nonlocal running
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "--user",
            "12345:12345",
            "-v",
            volume + ":/app/storage",
            "-v",
            books + (":/books" if writable_books else ":/books:ro"),
            "-v",
            str(Path(__file__).resolve().parents[1]) + ":/tooling:ro",
            *(
                [
                    "-e",
                    "SHUKU_DEPENDENCY_SEED=/absent",
                ]
                if without_dependency_seed
                else []
            ),
            image or args.image,
        )
        running = True
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "/usr/local/bin/python3.11",
                    "-c",
                    "import urllib.request; from pathlib import Path; "
                    + (
                        "assert Path('/app/storage/update-tmp/worker-ready').exists(); "
                        if require_worker
                        else ""
                    )
                    + "assert not Path('/app/storage/update-tmp/installation-incomplete').exists(); assert Path('/books/sentinel').read_text()=='original-book'; assert urllib.request.urlopen('http://127.0.0.1:3000/login').status == 200; assert urllib.request.urlopen('http://127.0.0.1:3000/api/health').status == 200",
                ],
                capture_output=True,
                check=False,
            )
            if probe.returncode == 0:
                return
            if docker("inspect", "-f", "{{.State.Running}}", name) != "true":
                raise RuntimeError(docker("logs", name))
            time.sleep(1)
        raise RuntimeError(docker("logs", name))

    def stop() -> None:
        nonlocal running, log_index
        docker("stop", "-t", "30", name)
        log_index += 1
        (output / f"{name}-{log_index}.log").write_text(
            docker("logs", name), encoding="utf-8"
        )
        assert docker("inspect", "-f", "{{.State.ExitCode}}", name) == "143"
        docker("rm", name)
        running = False

    def offline_command(code: str, python: str = "/usr/local/bin/python3.11") -> str:
        return docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "12345:12345",
            "-v",
            volume + ":/app/storage",
            "--entrypoint",
            python,
            args.image,
            "-c",
            "from pathlib import Path; assert Path('/app/storage/.acceptance-volume').is_file(); "
            + code,
        )

    def wait_for(code: str, timeout: int = 60) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = execute(code)
            if result == "ready":
                return result
            if docker("inspect", "-f", "{{.State.Running}}", name) != "true":
                raise RuntimeError(docker("logs", name))
            time.sleep(0.2)
        raise AssertionError(f"acceptance condition timed out: {code}")

    def inject(relative: str, addition: str, *, replace: bool = False) -> None:
        offline_command(
            f"p=Path('/app/storage/runtime/apps/api-python/{relative}'); p.with_suffix('.acceptance-original').write_bytes(p.read_bytes()); p.write_text({addition!r} if {replace!r} else p.read_text()+'\\n'+{addition!r})"
        )

    def restore(relative: str) -> None:
        offline_command(
            f"p=Path('/app/storage/runtime/apps/api-python/{relative}'); p.write_bytes(p.with_suffix('.acceptance-original').read_bytes()); p.with_suffix('.acceptance-original').unlink()"
        )

    def fault_boundaries() -> None:
        fixture_root = Path(__file__).parent / "fixtures"
        probe = (fixture_root / "startup-http-probe.py").read_text(encoding="utf-8")
        print(execute("initialize=True\n" + probe, business))
        stop()
        queue_file = "app/services/metadata_lookup_queue.py"
        inject(
            queue_file,
            (fixture_root / "metadata-startup-faults.py").read_text(encoding="utf-8"),
        )
        offline_command(
            "import sys; sys.path.insert(0,'/app/storage/runtime/apps/api-python'); "
            "from sqlalchemy import select; from app.db.session import SessionLocal; "
            "from app.models import MetadataLookupTask, LibraryReadableResource; "
            "db=SessionLocal(); r=db.scalar(select(LibraryReadableResource).where(LibraryReadableResource.format=='TXT')); "
            "db.add(MetadataLookupTask(id='acceptance-lookup',book_id=r.book_id,resource_id=r.id,status='PENDING',provider_order='[]',attempts=0)); db.commit(); db.close()",
            business,
        )
        start()
        wait_for(
            "from pathlib import Path; p=Path('/app/storage/update-tmp/claimed-tasks'); print('ready' if p.exists() and 'acceptance-lookup' in p.read_text() else 'waiting')"
        )
        assert execute(
            "from pathlib import Path; p=Path('/app/storage/update-tmp'); assert (p/'recovery-attempts').read_text()=='3'; assert (p/'claimed-tasks').read_text().splitlines().count('acceptance-lookup')==1; assert (p/'maintenance-failed').exists(); print('recovery gated, retried, and processed once')"
        )
        print(execute(probe, business))
        assert "metadata.maintenance_deferred" in docker("logs", name)
        stop()
        restore(queue_file)
        # Crash before publication with a persisted PREPARED target, then allow
        # the expired lease to recover. No production fault switch is added.
        writeback_file = "app/services/metadata_file_writeback.py"
        inject(
            writeback_file,
            (fixture_root / "writeback-crash.py").read_text(encoding="utf-8"),
        )
        offline_command(
            (fixture_root / "seed-writeback-crash.py").read_text(encoding="utf-8"),
            business,
        )
        start(writable_books=True, require_worker=False)
        wait_for(
            "from pathlib import Path; print('ready' if Path('/app/storage/update-tmp/writeback-crashed').exists() else 'waiting')"
        )
        # Advance only the test lease to simulate downtime without a minute sleep.
        execute(
            "import sys; sys.path.insert(0,'/app/storage/runtime/apps/api-python'); from datetime import datetime,UTC,timedelta; from app.db.session import SessionLocal; from app.models.organize import MetadataWritebackTarget; db=SessionLocal(); t=db.get(MetadataWritebackTarget,'acceptance-target'); assert t.status=='PREPARED'; assert __import__('pathlib').Path(t.prepared_path).is_file(); t.lease_expires_at=datetime.now(UTC)-timedelta(seconds=1); db.commit(); db.close()",
            business,
        )
        wait_for(
            "from pathlib import Path; print('ready' if Path('/app/storage/update-tmp/writeback-published').exists() else 'waiting')"
        )
        assert execute(
            "from pathlib import Path; p=Path('/app/storage/update-tmp/writeback-published'); assert p.read_text()=='once'; assert b'Crash recovery' in Path('/books/sample.opf').read_bytes(); assert Path('/books/sample.txt').read_text()=='acceptance original text'; print('crash recovery published once; source retained')"
        )
        print(execute(probe, business))
        stop()
        restore(writeback_file)
        inject(
            "app/worker/main.py",
            "raise RuntimeError('acceptance worker load failure')\n",
            replace=True,
        )
        start(require_worker=False)
        core_pids = execute(
            "from pathlib import Path; import json,os; print(json.dumps(sorted(int(p.parent.name) for p in Path('/proc').glob('[0-9]*/cmdline') if int(p.parent.name)!=os.getpid() and any(x in p.read_bytes().replace(bytes([0]),b' ') for x in [b'uvicorn app.main:app',b'next-server',b'unified-http-gateway.mjs']))))"
        )
        assert len(json.loads(core_pids)) >= 3, core_pids
        deadline = time.monotonic() + 65
        while "worker.paused reason=restart_limit" not in docker("logs", name):
            if time.monotonic() > deadline:
                raise AssertionError("worker restart limit not reached")
            time.sleep(0.5)
        execute(f"import os; [os.kill(pid,0) for pid in {core_pids}]")
        assert execute(
            "from pathlib import Path; assert not Path('/app/storage/update-tmp/worker-ready').exists(); print('worker offline, core processes retained')"
        )
        print(execute(probe, business))
        stop()
        restore("app/worker/main.py")
        start()
        print(
            "PASS startup fault boundaries A/B/C/D; process crash is not hardware power loss"
        )

    def update_boundaries() -> None:
        fixture_root = Path(__file__).parent / "fixtures"
        probe = (fixture_root / "startup-http-probe.py").read_text(encoding="utf-8")
        print(execute("initialize=True\n" + probe, business), flush=True)
        fixture = (fixture_root / "prepare-startup-update.py").read_text(
            encoding="utf-8"
        )
        for fault in ("recovery", "worker"):
            target = json.loads(execute(f"fault={fault!r}\n" + fixture, business))
            print("prepared real update:", target, flush=True)
            wait_for(
                "import json; from pathlib import Path; s=json.loads(Path('/app/storage/update-tmp/preparation.json').read_text()); print('ready' if s['phase'] in ('success','failed') else 'waiting')",
                timeout=240,
            )
            state = json.loads(
                execute(
                    "from pathlib import Path; print(Path('/app/storage/update-tmp/preparation.json').read_text())"
                )
            )
            assert state["phase"] == ("success" if fault == "recovery" else "failed"), (
                state
            )
            if fault == "worker":
                assert state["error"] == "WORKER_STARTUP_FAILED", state
            assert execute(
                f"import urllib.request,json; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version']=={target['version']!r}; print('target version verified')"
            )
            print(execute(probe, business), flush=True)
            print(
                "PASS online update",
                fault,
                state["phase"],
                state.get("error"),
                flush=True,
            )
        stop()

    def image_switches() -> None:
        old_version = execute(
            "import json; from pathlib import Path; print(json.loads(Path('/app/storage/runtime/application.json').read_text())['version'])"
        )
        execute(
            "from pathlib import Path; s=Path('/app/storage'); (s/'runtime/obsolete-image-file').write_text('old'); (s/'dependencies/obsolete-image-file').write_text('old'); (s/'covers/sentinel').write_text('keep'); (s/'configuration').write_text('keep')"
        )
        # Existing real API fixture verifies accounts, library content and reading state.
        probe = (Path(__file__).parent / "fixtures/startup-http-probe.py").read_text(
            encoding="utf-8"
        )
        print(execute("initialize=True\n" + probe, business))
        secret = execute(
            "from pathlib import Path; import hashlib; print(hashlib.sha256(Path('/app/storage/secrets/session-secret').read_bytes()).hexdigest())"
        )
        stop()
        start()
        target = json.loads(
            execute(
                "from pathlib import Path; print(Path('/opt/shuku-image/application.json').read_text())"
            )
        )
        assert target["version"] != old_version, (
            "--upgrade-from must have a different version"
        )
        assert execute(
            "import json,urllib.request; from pathlib import Path; s=Path('/app/storage'); target=json.loads(Path('/opt/shuku-image/application.json').read_text()); assert json.loads((s/'runtime/application.json').read_text())==target; assert json.loads((s/'update-tmp/image.json').read_text())==target; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version']==target['version']; assert not (s/'runtime/obsolete-image-file').exists(); assert not (s/'dependencies/obsolete-image-file').exists(); assert (s/'update-tmp/database-before-image.sqlite3').exists(); assert (s/'covers/sentinel').read_text()=='keep'; assert (s/'configuration').read_text()=='keep'; print('image and actual API aligned; obsolete code/dependencies removed')"
        )
        assert secret == execute(
            "from pathlib import Path; import hashlib; print(hashlib.sha256(Path('/app/storage/secrets/session-secret').read_bytes()).hexdigest())"
        )
        print(execute(probe, business))
        fixture = (
            Path(__file__).parent / "fixtures/prepare-startup-update.py"
        ).read_text(encoding="utf-8")
        online = json.loads(execute("fault='none'\n" + fixture, business))
        wait_for(
            "import json; from pathlib import Path; s=json.loads(Path('/app/storage/update-tmp/preparation.json').read_text()); assert s['phase']!='failed',s; print('ready' if s['phase']=='success' else 'waiting')",
            timeout=240,
        )
        snapshot_code = "from pathlib import Path; import hashlib,json; s=Path('/app/storage'); print(json.dumps({n:[(s/n).stat().st_ino,(s/n).stat().st_mtime_ns,hashlib.sha256((s/n).read_bytes()).hexdigest()] for n in ['runtime/application.json','dependencies/installed.json','dependencies/python/pyvenv.cfg','update-tmp/image.json']}))"
        snapshot = execute(snapshot_code)
        stop()
        start(without_dependency_seed=True)
        assert snapshot == execute(snapshot_code)
        assert execute(
            f"import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version']=={online['version']!r}; print('online version retained after same-image restart')"
        )
        print(execute(probe, business))
        stop()
        # An older image that includes this launcher must also take precedence.
        start(image=args.upgrade_from)
        assert execute(
            f"import json,urllib.request; from pathlib import Path; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/openapi.json'))['info']['version']=={old_version!r}; assert json.loads(Path('/app/storage/update-tmp/image.json').read_text())['version']=={old_version!r}; print('older image selected without database downgrade')"
        )
        print(execute(probe, business))
        stop()
        print(
            "PASS image switch, data retention, real online update/restart, and compatible older image"
        )

    try:
        docker(
            "run",
            "--rm",
            "-v",
            volume + ":/app/storage",
            "-v",
            books + ":/books",
            "--entrypoint",
            "sh",
            args.image,
            "-c",
            "chown 12345:12345 /app/storage /books && touch /app/storage/.acceptance-volume && printf original-book > /books/sentinel && printf 'acceptance original text' > /books/sample.txt",
        )
        start(image=args.upgrade_from)
        if args.upgrade_from:
            image_switches()
            return
        if args.update_boundaries:
            update_boundaries()
            return
        if args.fault_boundaries:
            fault_boundaries()
        assert execute(
            "import importlib.util; assert importlib.util.find_spec('fastapi') is None; print('fixed environment has no business dependencies')"
        )
        business = "/app/storage/dependencies/python/bin/python"
        print(
            execute(
                "import sys,site,fastapi; assert sys.prefix=='/app/storage/dependencies/python'; assert not site.ENABLE_USER_SITE; assert all('/usr/local/lib/python3.11/site-packages' != p for p in sys.path); print('business environment isolated')",
                business,
            )
        )
        processes = json.loads(
            execute(
                "import json; from pathlib import Path; print(json.dumps([p.read_bytes().replace(b'\\0',b' ').decode() for p in Path('/proc').glob('[0-9]*/cmdline') if p.is_file()]))"
            )
        )
        for role in ("-m uvicorn app.main:app", "-m app.worker.main"):
            assert any(
                command.startswith(business + " ") and role in command
                for command in processes
            )
        assert "prestart outcome=success" in docker("logs", name)
        assert execute(
            "from pathlib import Path; import json; s=Path('/app/storage'); (s/'covers/sentinel').write_text('keep'); (s/'configuration').write_text('keep'); print(json.loads((s/'dependencies/installed.json').read_text())['identity'])"
        )
        execute(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); c.execute('PRAGMA user_version=321'); c.close()"
        )
        snapshot = execute(
            "from pathlib import Path; import hashlib,json; s=Path('/app/storage'); print(json.dumps({str(p.relative_to(s)):[p.stat().st_ino,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()] for p in [s/'dependencies/installed.json',s/'dependencies/python/pyvenv.cfg',s/'secrets/session-secret',s/'covers/sentinel',s/'configuration']}))"
        )
        # A competing conversion must fail while the launcher lock is held.
        blocked = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "/usr/local/bin/python3.11",
                "/opt/shuku-launcher/container-entry.py",
                "--convert-legacy",
            ],
            capture_output=True,
            check=False,
        )
        assert blocked.returncode != 0 and b"already running" in blocked.stderr
        stop()
        start(without_dependency_seed=True)
        assert snapshot == execute(
            "from pathlib import Path; import hashlib,json; s=Path('/app/storage'); print(json.dumps({str(p.relative_to(s)):[p.stat().st_ino,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()] for p in [s/'dependencies/installed.json',s/'dependencies/python/pyvenv.cfg',s/'secrets/session-secret',s/'covers/sentinel',s/'configuration']}))"
        )
        assert execute(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); assert c.execute('PRAGMA user_version').fetchone()==(321,); c.close(); print('database retained')"
        )
        stop()
        # Convert only this isolated deployment to a known v1-shaped fixture.
        offline_command(
            "from pathlib import Path; import json,shutil; s=Path('/app/storage'); p=s/'runtime/application.json'; v=json.loads(p.read_text()); v.pop('protocol'); p.write_text(json.dumps(v)); shutil.rmtree(s/'dependencies'); (s/'update-tmp/image.json').unlink()"
        )
        start()
        assert execute(
            "from pathlib import Path; s=Path('/app/storage'); assert (s/'update-tmp/database-before-image.sqlite3').is_file(); assert (s/'covers/sentinel').read_text()=='keep'; print('automatic legacy adoption preserved data')"
        )
        preserved = json.loads(
            execute(
                "from pathlib import Path; import hashlib,json; s=Path('/app/storage'); print(json.dumps({str(p.relative_to(s)):[p.stat().st_ino,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()] for p in [s/'secrets/session-secret',s/'covers/sentinel',s/'configuration']}))"
            )
        )
        assert all(
            json.loads(snapshot)[key] == value for key, value in preserved.items()
        )
        assert execute(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); assert c.execute('PRAGMA user_version').fetchone()==(321,); c.close(); print('converted database retained')"
        )
        stop()
        # A newer/unknown database must not be made acceptable by conversion.
        offline_command(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); c.execute(\"UPDATE alembic_version SET version_num='future_schema'\"); c.commit(); c.close()"
        )
        rejected_start = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "12345:12345",
                "-v",
                volume + ":/app/storage",
                args.image,
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        assert rejected_start.returncode != 0
        (output / f"{name}-schema-refused.log").write_bytes(
            rejected_start.stdout + rejected_start.stderr
        )
        assert offline_command(
            "import sqlite3; c=sqlite3.connect('/app/storage/database/shuku.sqlite3'); assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('future_schema',); assert c.execute('PRAGMA user_version').fetchone()==(321,); c.close(); print('normal entry rejected unknown schema and retained database')"
        )
        offline_command(
            "from pathlib import Path; import json,shutil,sqlite3; s=Path('/app/storage'); p=s/'runtime/application.json'; v=json.loads(p.read_text()); v.pop('protocol'); p.write_text(json.dumps(v)); shutil.rmtree(s/'dependencies'); c=sqlite3.connect(s/'database/shuku.sqlite3'); c.execute(\"UPDATE alembic_version SET version_num='future_schema'\"); c.commit(); c.close()"
        )
        rejected = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                "12345:12345",
                "-v",
                volume + ":/app/storage",
                "--entrypoint",
                "/usr/local/bin/python3.11",
                args.image,
                "/opt/shuku-launcher/container-entry.py",
                "--convert-legacy",
            ],
            capture_output=True,
            check=False,
        )
        assert rejected.returncode != 0
        assert offline_command(
            "from pathlib import Path; import json,sqlite3; s=Path('/app/storage'); assert 'protocol' not in json.loads((s/'runtime/application.json').read_text()); c=sqlite3.connect(s/'database/shuku.sqlite3'); assert c.execute('SELECT version_num FROM alembic_version').fetchone()==('future_schema',); c.close(); print('unknown schema rejected without downgrade')"
        )
        print(
            "PASS: API, Worker, schema, Web; non-root; offline initialization/restart; automatic legacy adoption, locked conversion, unknown-schema refusal"
        )
    finally:
        if running:
            (output / f"{name}-final.log").write_text(
                docker("logs", name), encoding="utf-8"
            )
            subprocess.run(
                ["docker", "rm", "-f", name], check=False, capture_output=True
            )
        docker("volume", "rm", volume, books)


if __name__ == "__main__":
    main()
