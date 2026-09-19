# Test-only code appended to the metadata queue in an isolated acceptance volume.
# This file is never included in the application image or loaded by production.
import sqlite3 as _acceptance_sqlite
from pathlib import Path as _AcceptancePath

_acceptance_root = _AcceptancePath("/app/storage/update-tmp")
_acceptance_recover = globals()["recover_stale_metadata_lookup_tasks"]
_acceptance_claim = globals()["claim_next_metadata_lookup_task"]
_acceptance_clock = 0


def monotonic():
    global _acceptance_clock
    _acceptance_clock += 10
    return _acceptance_clock


def recover_stale_metadata_lookup_tasks(db):
    path = _acceptance_root / "recovery-attempts"
    count = int(path.read_text()) + 1 if path.exists() else 1
    path.write_text(str(count))
    if count < 3:
        raise _acceptance_sqlite.OperationalError("database is locked")
    return _acceptance_recover(db)


def claim_next_metadata_lookup_task(db, *, owner_id):
    assert int((_acceptance_root / "recovery-attempts").read_text()) >= 3
    result = _acceptance_claim(db, owner_id=owner_id)
    if result is not None:
        with (_acceptance_root / "claimed-tasks").open("a") as stream:
            stream.write(str(result["id"]) + "\n")
    return result


def maintain_metadata_writebacks(*args, **kwargs):
    (_acceptance_root / "maintenance-failed").touch()
    raise RuntimeError("acceptance maintenance fault")
