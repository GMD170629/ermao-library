"""Read actual JSONL records in diagnostic integration tests."""
from datetime import datetime
from types import SimpleNamespace

from app.modules.system.infrastructure.log_files import read_log_events


def log_records():
    return [SimpleNamespace(
        id=row["id"], level=row["level"], source=row["source"],
        action=row["action"], message=row["message"],
        metadata_json=row["metadata"], actor_type=row["actorType"],
        actor_id=row.get("actorId"), created_at=datetime.fromisoformat(row["createdAt"]),
    ) for row in read_log_events()]


def one_log(records):
    assert len(records) == 1, [row.message for row in records]
    return records[0]


def find_log(event_id):
    return next((row for row in log_records() if row.id == event_id), None)
