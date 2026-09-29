from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from app.modules.feedback.infrastructure import Attachment, FeedbackDeliveryError, send_to_official_site


def test_feedback_transport_requires_release_receiver_configuration() -> None:
    with pytest.raises(FeedbackDeliveryError, match="not configured"):
        send_to_official_site({"submissionKey": "abc"}, ())


def test_feedback_transport_sends_payload_and_file_as_multipart(monkeypatch) -> None:
    received: list[tuple[str, bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers["Content-Length"])
            received.append((self.headers["Content-Type"], self.rfile.read(size)))
            response = json.dumps({"id": "FB-LOCAL", "status": "sent"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *_args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setattr("app.modules.feedback.infrastructure.RECEIVER_URL", f"http://127.0.0.1:{server.server_port}/api/feedback")
        receipt = send_to_official_site(
            {"submissionKey": "abc", "markdown": "reviewed text"},
            (Attachment("note.txt", "text/plain", b"attachment bytes"),),
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert receipt.id == "FB-LOCAL"
    assert received[0][0].startswith("multipart/form-data; boundary=")
    assert b'"markdown":"reviewed text"' in received[0][1]
    assert b'filename="note.txt"' in received[0][1]
    assert b"attachment bytes" in received[0][1]
