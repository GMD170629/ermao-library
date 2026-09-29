from __future__ import annotations

import json
import logging
import re
import shutil
import tempfile
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from sqlalchemy import create_engine, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .contracts import Receipt, Submission
from .delivery import send_feedback
from .models import Base, FeedbackRecord

LOGGER = logging.getLogger(__name__)
FILE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf",
    ".txt": "text/plain", ".log": "text/plain", ".zip": "application/zip",
}
MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 15 * 1024 * 1024
MAX_REQUEST = 17 * 1024 * 1024


def _clean_name(value: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or len(name) > 120 or not re.fullmatch(r"[\w.() +-]+", name, re.UNICODE):
        raise HTTPException(400, "Invalid filename")
    return name


def _validate_signature(ext: str, beginning: bytes) -> bool:
    signatures = {
        ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff",
        ".gif": b"GIF8", ".pdf": b"%PDF-", ".zip": b"PK\x03\x04",
    }
    if ext == ".webp":
        return beginning.startswith(b"RIFF") and beginning[8:12] == b"WEBP"
    return ext not in signatures or beginning.startswith(signatures[ext])


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    data_root = config.data_root.resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    upload_root = data_root / "temporary-files"
    if upload_root.is_symlink():
        raise RuntimeError("Temporary file root must not be a symlink")
    upload_root.mkdir(exist_ok=True)
    for orphan in upload_root.iterdir():
        if orphan.is_dir() and not orphan.is_symlink():
            shutil.rmtree(orphan)
    engine = create_engine(f"sqlite:///{(data_root / 'feedback.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.execute(update(FeedbackRecord).where(FeedbackRecord.status == "pending").values(status="failed"))
        db.commit()
    app = FastAPI(title="Ermao official feedback receiver")
    attempts: dict[str, deque[float]] = defaultdict(deque)
    rate_lock = Lock()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/feedback", response_model=Receipt)
    async def receive(request: Request, payload: str = Form(), files: list[UploadFile] | None = File(default=None)) -> Receipt:
        if int(request.headers.get("content-length", "0") or "0") > MAX_REQUEST:
            raise HTTPException(413, "Request too large")
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with rate_lock:
            timestamps = attempts[client_ip]
            while timestamps and now - timestamps[0] > 3600:
                timestamps.popleft()
            if len(timestamps) >= 10:
                raise HTTPException(429, "Too many feedback submissions")
            timestamps.append(now)
        try:
            submission = Submission.model_validate_json(payload)
        except ValidationError as error:
            raise HTTPException(422, "Invalid feedback payload") from error
        if len(payload.encode()) > 60_000 or len(json.dumps(submission.diagnostics, ensure_ascii=False)) > 30_000:
            raise HTTPException(413, "Feedback text too large")
        uploaded = files or []
        if len(uploaded) > 5:
            raise HTTPException(413, "Too many attachments")
        key = str(submission.submission_key)
        with Session(engine) as db:
            existing = db.scalar(select(FeedbackRecord).where(FeedbackRecord.submission_key == key))
            if existing:
                if (
                    existing.kind != submission.kind
                    or existing.markdown != submission.markdown
                    or existing.qq != submission.contact.qq
                    or existing.group_name != submission.contact.group_name
                    or existing.email != submission.contact.email
                    or existing.diagnostics_json != json.dumps(submission.diagnostics, ensure_ascii=False)
                ):
                    raise HTTPException(409, "Idempotency key reused for different feedback")
                if existing.status == "sent":
                    return Receipt(id=existing.id)
                if existing.status == "pending":
                    raise HTTPException(409, "Feedback submission in progress")
                record_id = existing.id
                existing.status = "pending"
                existing.attempts += 1
                db.commit()
            else:
                record_id = f"FB-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8].upper()}"
                record = FeedbackRecord(
                    id=record_id, submission_key=key, kind=submission.kind,
                    markdown=submission.markdown, qq=submission.contact.qq,
                    group_name=submission.contact.group_name, email=submission.contact.email,
                    diagnostics_json=json.dumps(submission.diagnostics, ensure_ascii=False),
                    status="pending", attempts=1,
                )
                db.add(record)
                try:
                    db.commit()
                except IntegrityError as error:
                    db.rollback()
                    raise HTTPException(409, "Feedback submission in progress") from error
        staged_dir = Path(tempfile.mkdtemp(prefix="submission-", dir=upload_root))
        staged: list[tuple[str, str, Path]] = []
        try:
            total = 0
            for uploaded_file in uploaded:
                name = _clean_name(uploaded_file.filename or "")
                ext = Path(name).suffix.lower()
                media_type = FILE_TYPES.get(ext)
                if media_type is None:
                    raise HTTPException(400, "Unsupported attachment type")
                path = staged_dir / uuid4().hex
                beginning = b""
                size = 0
                with path.open("xb") as output:
                    while chunk := await uploaded_file.read(64 * 1024):
                        if not beginning:
                            beginning = chunk[:16]
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_FILE or total > MAX_TOTAL:
                            raise HTTPException(413, "Attachment size limit exceeded")
                        output.write(chunk)
                if not _validate_signature(ext, beginning):
                    raise HTTPException(400, "Attachment content does not match filename")
                if ext in {".txt", ".log"}:
                    try:
                        content = path.read_bytes()
                        if b"\x00" in content:
                            raise UnicodeError("binary text")
                        content.decode("utf-8")
                    except UnicodeError as error:
                        raise HTTPException(400, "Invalid text attachment") from error
                staged.append((name, media_type, path))
            await run_in_threadpool(send_feedback, config, record_id, submission, staged)
            with Session(engine) as db:
                record = db.get(FeedbackRecord, record_id)
                if record is None:
                    raise RuntimeError("Feedback record disappeared")
                record.status = "sent"
                record.sent_at = datetime.now(UTC)
                db.commit()
            return Receipt(id=record_id)
        except HTTPException:
            with Session(engine) as db:
                record = db.get(FeedbackRecord, record_id)
                if record is not None:
                    record.status = "failed"
                    db.commit()
            raise
        except Exception as error:
            LOGGER.exception("feedback.delivery_failed", extra={"feedback_id": record_id, "stage": "send_or_persist"})
            with Session(engine) as db:
                record = db.get(FeedbackRecord, record_id)
                if record is not None:
                    record.status = "failed"
                    db.commit()
            raise HTTPException(503, "Feedback delivery failed") from error
        finally:
            for uploaded_file in uploaded:
                await uploaded_file.close()
            try:
                shutil.rmtree(staged_dir)
            except OSError:
                LOGGER.exception("feedback.temporary_cleanup_failed", extra={"feedback_id": record_id, "stage": "remove_temporary_files"})

    return app
