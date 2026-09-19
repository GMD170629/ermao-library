"""Executed by the business interpreter in the isolated acceptance container."""

import json
import sys
import time
import urllib.request

sys.path.insert(0, "/app/storage/runtime/apps/api-python")
from app.db.session import SessionLocal
from app.models import LibraryReadableResource
from sqlalchemy import select

base = "http://127.0.0.1:3000"
cookie = ""


def request(path, data=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json", "Origin": base, "Cookie": cookie},
    )
    return urllib.request.urlopen(req, timeout=5)


if globals().get("initialize", False):
    request(
        "/api/auth/setup",
        {
            "email": "acceptance@example.com",
            "password": "Acceptance-test-password-123",
            "name": "Acceptance",
        },
    )
with request(
    "/api/auth/login",
    {"email": "acceptance@example.com", "password": "Acceptance-test-password-123"},
) as response:
    cookie = next(
        value.split(";", 1)[0]
        for value in response.headers.get_all("Set-Cookie")
        if value.startswith("shuku_session=")
    )
assert request("/api/auth/me").status == 200
if globals().get("initialize", False):
    request(
        "/api/libraries",
        {
            "name": "Acceptance",
            "rootPath": "/books",
            "organizationMode": "FLAT",
            "minFileSizeBytes": 0,
        },
    )
assert request("/api/libraries").status == 200
deadline = time.monotonic() + 45
while True:
    with SessionLocal() as db:
        resource = db.scalar(
            select(LibraryReadableResource.id).where(
                LibraryReadableResource.format == "TXT",
                LibraryReadableResource.import_state == "READY",
            )
        )
    if resource is not None:
        break
    if time.monotonic() >= deadline:
        raise AssertionError("sample resource never imported")
    time.sleep(0.2)
with request(f"/api/reader/v5/resources/{resource}/publication") as response:
    assert b"acceptance original text" in response.read()
print("PASS login, library query, independent reading")
