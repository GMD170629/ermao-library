"""Isolated HTTP source + Python dependency injection for explicit UI acceptance."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class AcceptanceSource:
    def __init__(self, root: Path):
        self.root = root
        self.release_download = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                name = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
                file = owner.root / name
                if not file.is_file():
                    self.send_error(404)
                    return
                if name.endswith(".tar.gz") and not owner.release_download.wait(120):
                    self.send_error(504)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(file.stat().st_size))
                self.end_headers()
                try:
                    with file.open("rb") as stream:
                        while chunk := stream.read(64 * 1024):
                            self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def injection(self, directory: Path):
        # PYTHONPATH/sitecustomize belongs only to this disposable test container.
        # Production has no URL configuration or bypass. The actual source still
        # validates official URLs and redirects, using its existing opener seam.
        (directory / "sitecustomize.py").write_text(f"""
from pathlib import Path
if Path('/acceptance-only').exists() and Path.cwd().name == 'api-python':
    import http.client, urllib.request, sys
    sys.path.insert(0, str(Path.cwd()))
    import app.bootstrap.updates as assembly
    from app.modules.updates.infrastructure.official_source import OfficialHTTP, OfficialRedirects
    class LocalHTTPS(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(lambda host, **kw: http.client.HTTPConnection('host.docker.internal', {self.server.server_port}, **kw), request)
    assembly.OfficialHTTP = lambda: OfficialHTTP(urllib.request.build_opener(urllib.request.ProxyHandler({{}}), OfficialRedirects(), LocalHTTPS()))
""")

    def close(self):
        self.release_download.set()
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
