"""Local fake-server demonstration: python demo.py."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time

from solution import HTTPFailure, InvalidJSON, TransportFailure, fetch_json


class FakeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        self.server.requests.append(self.path)
        routes = {
            "/null": (200, b"null"),
            "/false": (200, b"false"),
            "/empty": (200, b"[]"),
            "/object": (201, b'{"ok": true}'),
            "/bad": (200, b"not JSON"),
            "/utf8": (200, b'"\xff"'),
            "/error": (503, b"not JSON " * 100),
            "/redirect": (302, b"moved"),
            "/slow": (200, b"null"),
            "/slow-body": (200, b"null"),
            "/slow-error": (503, b"bad"),
            "/truncated": (200, b"null"),
        }
        if self.path == "/slow":
            time.sleep(0.15)
        status, body = routes.get(self.path, (404, b"missing"))
        self.send_response(status)
        if status == 302:
            self.send_header("Location", "/object")
        self.send_header("Content-Length", str(len(body) + (10 if self.path == "/truncated" else 0)))
        self.end_headers()
        if self.path in ("/slow-body", "/slow-error"):
            time.sleep(0.15)
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass


@contextmanager
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    server.requests = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main():
    with fake_server() as (server, base):
        for path in ("/null", "/false", "/empty", "/object", "/bad", "/utf8", "/error", "/redirect", "/slow"):
            try:
                print(f"{path}: {fetch_json(base + path, timeout=0.05)!r}")
            except (HTTPFailure, InvalidJSON, TransportFailure) as error:
                print(f"{path}: {type(error).__name__}")
        print(f"Requests received: {len(server.requests)} (one per call)")


if __name__ == "__main__":
    main()
