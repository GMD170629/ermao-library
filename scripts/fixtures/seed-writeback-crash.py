import json
import sys

sys.path.insert(0, "/app/storage/runtime/apps/api-python")
from app.db.session import SessionLocal
from app.models import LibraryReadableResource
from app.models.organize import MetadataWritebackOperation, MetadataWritebackTarget
from sqlalchemy import select

with SessionLocal() as db:
    resource = db.scalar(
        select(LibraryReadableResource).where(LibraryReadableResource.format == "TXT")
    )
    db.add(
        MetadataWritebackOperation(
            id="acceptance-operation",
            book_id=resource.book_id,
            resource_id=resource.id,
            source_node_id=resource.source_node_id,
            source="MANUAL",
            status="PENDING",
            total_targets=1,
        )
    )
    db.flush()
    db.add(
        MetadataWritebackTarget(
            id="acceptance-target",
            operation_id="acceptance-operation",
            target_key="acceptance-target",
            source_path="/books/sample.txt",
            format="TXT",
            payload_json=json.dumps({"title": "Crash recovery"}),
            status="PENDING",
            attempts=0,
            written_fields_json="[]",
        )
    )
    db.commit()
