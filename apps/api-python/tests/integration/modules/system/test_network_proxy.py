from __future__ import annotations

import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import StreamRequestHandler, ThreadingTCPServer
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from sqlalchemy.orm import sessionmaker

from app.bootstrap.outbound_http import outbound_opener, use_outbound_sessions
from app.core.auth import hash_password
from app.models.auth import User
from app.modules.system.domain.network_proxy import NetworkProxy, ProxyConnection


@contextmanager
def serving(server):
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        worker.join()
        server.server_close()


def test_http_proxy_redirect_auth_and_early_stream(monkeypatch):
    sent = []
    release = Event()

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            sent.append((self.path, self.headers.get("Proxy-Authorization")))
            if self.path.endswith("/start"):
                self.send_response(302)
                self.send_header("Location", "http://cdn.example.test/stream")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "65537")
            self.end_headers()
            self.wfile.write(b"a" * 65536)
            if release.wait(5):
                self.wfile.write(b"b")

    monkeypatch.setenv("NO_PROXY", ".example.test")
    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Proxy)) as port:
        snapshot = NetworkProxy(
            ProxyConnection("http", "127.0.0.1", port, "proxy-user", "proxy-password"),
            domains=("example.test",),
        )
        with outbound_opener(snapshot=snapshot).open(
            Request(
                "http://updates.example.test/start",
                headers={"Proxy-Authorization": "Basic previous-hop"},
            ),
            timeout=2,
        ) as response:
            try:
                assert response.read1(65536).startswith(b"a")
                assert not release.is_set()
            finally:
                release.set()
            assert response.read().endswith(b"b")
        header = "Basic " + base64.b64encode(b"proxy-user:proxy-password").decode()
        assert sent == [
            ("http://updates.example.test/start", header),
            ("http://cdn.example.test/stream", header),
        ]
        assert snapshot.rules_for("notexample.test") == ()


def test_socks5_auth_and_remote_hostname():
    destinations = []

    class Socks(StreamRequestHandler):
        def handle(self):
            read = self.rfile.read
            assert read(1) == b"\x05"
            assert b"\x02" in read(read(1)[0])
            self.wfile.write(b"\x05\x02")
            assert read(1) == b"\x01"
            assert read(read(1)[0]) == b"proxy-user"
            assert read(read(1)[0]) == b"proxy-password"
            self.wfile.write(b"\x01\x00")
            assert read(4) == b"\x05\x01\x00\x03"
            destinations.append((read(read(1)[0]), int.from_bytes(read(2), "big")))
            self.wfile.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            assert self.rfile.readline() == b"GET /metadata HTTP/1.1\r\n"
            while self.rfile.readline() != b"\r\n":
                pass
            self.wfile.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"
            )

    with serving(ThreadingTCPServer(("127.0.0.1", 0), Socks)) as port:
        snapshot = NetworkProxy(
            ProxyConnection(
                "socks5", "127.0.0.1", port, "proxy-user", "proxy-password"
            ),
            domains=("example.test",),
        )
        with outbound_opener(snapshot=snapshot).open(
            "http://metadata.example.test/metadata", timeout=2
        ) as response:
            assert response.read() == b"ok"
    assert destinations == [(b"metadata.example.test", 80)]


def test_new_requests_observe_saved_proxy_and_draft_does_not_publish(
    client, db_session, monkeypatch
):
    endpoint = "/api/system-settings/network-proxy"
    assert client.get(endpoint).status_code == 401
    for role in ("member", "admin"):
        db_session.add(
            User(
                email=f"{role}@example.com",
                name=role,
                role=role,
                password_hash=hash_password("proxy-test-password"),
            )
        )
    db_session.commit()
    credentials = {"email": "member@example.com", "password": "proxy-test-password"}
    assert client.post("/api/auth/login", json=credentials).is_success
    assert client.get(endpoint).status_code == 403
    assert client.put(endpoint, json={}).status_code == 403
    assert client.post(endpoint + "/test", json={}).status_code == 403
    credentials["email"] = "admin@example.com"
    assert client.post("/api/auth/login", json=credentials).is_success

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"routed")

    with serving(ThreadingHTTPServer(("127.0.0.1", 0), Proxy)) as port:
        payload = {
            "connection": {
                "protocol": "http",
                "host": "127.0.0.1",
                "port": port,
                "username": "user",
                "password": "proxy-secret",
            },
            "presets": ["updates", "github"],
            "domains": ["ExAmplE.TeSt.", "example.test"],
        }
        sessions = sessionmaker(bind=db_session.get_bind())
        with use_outbound_sessions(sessions):
            old_opener = outbound_opener()
            saved = client.put(endpoint, json=payload)
            assert saved.status_code == 200
            assert saved.json()["data"]["domains"] == ["example.test"]
            assert saved.json()["data"]["connection"]["passwordConfigured"] is True
            assert "proxy-secret" not in saved.text
            assert "proxy-secret" not in client.get("/api/system-settings").text
            assert (
                client.put(
                    "/api/system-settings",
                    json={"settings": {"network.proxy": "invalid write"}},
                ).status_code
                == 400
            )
            assert new_opener_read() == b"routed"
            with pytest.raises((URLError, HTTPError)):
                old_opener.open("http://metadata.example.test", timeout=1)
            draft = {
                "connection": None,
                "presets": [],
                "domains": ["draft.example.test"],
            }
            probe = client.post(endpoint + "/test", json=draft)
            assert probe.json()["data"][0]["result"] == "not_configured"
            assert client.get(endpoint).json() == saved.json()
            del payload["connection"]["password"]
            assert (
                client.put(endpoint, json=payload).json()["data"]["connection"][
                    "passwordConfigured"
                ]
                is True
            )
            payload["connection"]["password"] = ""
            assert (
                client.put(endpoint, json=payload).json()["data"]["connection"][
                    "passwordConfigured"
                ]
                is False
            )

    monkeypatch.setenv("NO_PROXY", "*")
    with use_outbound_sessions(sessions), pytest.raises(URLError):
        new_opener_read()


def new_opener_read() -> bytes:
    with outbound_opener().open("http://metadata.example.test", timeout=2) as response:
        return response.read()


def test_signed_in_reader_gets_official_release_summary_and_notes(
    client, db_session, monkeypatch
):
    from app.modules.updates.infrastructure.official_source import FEED_ROOT

    endpoint = "/api/updates/releases"
    assert client.get(endpoint).status_code == 401
    db_session.add(
        User(
            email="rel-reader@example.com",
            name="Reader",
            role="member",
            password_hash=hash_password("release-test-password"),
        )
    )
    db_session.commit()
    assert client.post(
        "/api/auth/login",
        json={"email": "rel-reader@example.com", "password": "release-test-password"},
    ).is_success
    requests = []

    class Source:
        def chunks(self, url, limit, seconds):
            requests.append(url)
            if url.endswith("index.json"):
                yield (
                    b'{"schemaVersion":1,"repository":"GMD170629/ermao-library","releases":[{"version":"1.6.4",'
                    b'"tag":"v1.6.4","publishedAt":"2026-11-19T00:00:00Z","notesPath":"v1.6.4.md",'
                    b'"releaseUrl":"https://github.com/GMD170629/ermao-library/releases/tag/v1.6.4","dependencyReleases":[]}]}'
                )
            else:
                yield b"Release notes"

    monkeypatch.setattr(client.app.state.update_runtime.releases, "transport", Source())
    summary = client.get(endpoint)
    assert summary.status_code == 200
    assert "dependencyReleases" not in summary.text
    assert summary.json()["data"]["releases"][0]["version"] == "1.6.4"
    assert (
        client.get(endpoint + "/1.6.4/notes").json()["data"]["markdown"]
        == "Release notes"
    )
    assert client.get(endpoint + "/arbitrary-path/notes").status_code == 422
    assert client.get("/api/updates/check").status_code == 403
    assert requests == [FEED_ROOT + "index.json", FEED_ROOT + "v1.6.4.md"]
