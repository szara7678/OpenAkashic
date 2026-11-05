"""Client routing and credential boundary tests: no external network."""
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

spec = importlib.util.spec_from_file_location("method_agent", Path(__file__).parents[1] / "scripts" / "method_agent.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


@pytest.fixture
def server():
    requests = []
    state = {"status": 200, "response": {"ok": True}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests.append((self.command, self.path, dict(self.headers), json.loads(body) if body else None))
            self.send_response(state["status"])
            if state["status"] == 302:
                self.send_header("Location", "/redirect-target")
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state["response"]).encode())

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:" + str(http.server_port), requests, state
    http.shutdown()
    thread.join()
    http.server_close()


def test_search_fetch_are_fixed_anonymous_gets(server, monkeypatch, capsys, tmp_path):
    base, requests, state = server
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_WRITE_KEY", "never-send-for-reads")
    state["response"] = {"results": [{"method": {"id": "method_1", "title": "절차"}}]}
    assert client.main(["--endpoint", base, "search", "--situation", "공개 실험", "--goal", "검증",
                        "--constraints", "비용 없음", "--limit", "3"]) == 0
    assert json.loads(capsys.readouterr().out) == state["response"]
    method, path, headers, body = requests[0]
    assert headers["User-Agent"] == "OpenAkashic-Method-Agent/0.1"
    assert method == "GET" and urlsplit(path).path == "/research/api/methods/search"
    assert parse_qs(urlsplit(path).query) == {"situation": ["공개 실험"], "goal": ["검증"],
                                             "constraints": ["비용 없음"], "limit": ["3"]}
    assert not any(name.lower() in ("x-openakashic-key", "idempotency-key") for name in headers)
    output = tmp_path / "response.json"
    assert client.main(["--endpoint", base, "--output", str(output), "fetch", "method_1"]) == 0
    assert requests[1][:2] == ("GET", "/research/api/methods/method_1")
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert json.loads(output.read_text()) == state["response"]


def test_submission_and_feedback_roundtrip(server, tmp_path, monkeypatch, capsys):
    base, requests, state = server
    monkeypatch.delenv("OPENAKASHIC_RESEARCH_WRITE_KEY", raising=False)
    key = "secret-test-key"
    keyfile = tmp_path / "key"
    keyfile.write_text(key)
    payload = {"public_source_only": True, "observed_result": "공개 결과"}
    inputfile = tmp_path / "input.json"
    inputfile.write_text(json.dumps(payload))
    for name, suffix in (("submit", ""), ("outcome", "/method_1/outcomes"), ("opinion", "/method_1/opinions")):
        state["response"] = {"id": name + "_1", "accepted": True}
        args = ["--endpoint", base, "--key-file", str(keyfile), name]
        if name != "submit":
            args += ["method_1"]
        args += ["--input", str(inputfile), "--idempotency-key", "experiment-" + name]
        assert client.main(args) == 0
        captured = capsys.readouterr()
        assert key not in captured.out + captured.err
        assert json.loads(captured.out) == state["response"]
        method, path, headers, body = requests[-1]
        assert (method, path) == ("POST", "/research/api/methods" + suffix)
        assert {k.lower(): v for k, v in headers.items()}["x-openakashic-key"] == key
        assert {k.lower(): v for k, v in headers.items()}["idempotency-key"] == "experiment-" + name
        assert body == payload


def test_public_write_missing_key_redirect_and_errors_are_safe(server, tmp_path, monkeypatch, capsys):
    base, requests, state = server
    for env in ("OPENAKASHIC_RESEARCH_WRITE_KEY", "OPENAKASHIC_WRITE_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    inputfile = tmp_path / "input.json"
    inputfile.write_text('{"public_source_only":false}')
    write = ["submit", "--input", str(inputfile), "--idempotency-key", "test"]
    assert client.main(write) == 1
    assert "read-only" in capsys.readouterr().err
    assert client.main(["--endpoint", base] + write) == 1
    assert "Write key required" in capsys.readouterr().err
    assert requests == []
    monkeypatch.setenv("OPENAKASHIC_WRITE_API_KEY", "sensitive-key")
    for status, summary in ((302, "redirect refused"), (422, "input validation failed")):
        state.update(status=status, response={"detail": "sensitive-key PRIVATE INPUT"})
        assert client.main(["--endpoint", base] + write) == 1
        captured = capsys.readouterr()
        assert summary in captured.err and str(status) in captured.err
        assert "sensitive-key" not in captured.out + captured.err
        assert "PRIVATE INPUT" not in captured.out + captured.err
    assert len(requests) == 2
    assert requests[0][3] == {"public_source_only": False}


@pytest.mark.parametrize("endpoint", [
    "http://user:password@127.0.0.1:18082", "http://127.0.0.1:18082/other",
    "http://127.0.0.1:18082?key=secret", "http://127.0.0.1:18082#secret",
    "ftp://127.0.0.1:18082", "http://127.0.0.1:invalid",
])
def test_invalid_endpoints_rejected_without_network(endpoint, capsys):
    assert client.main(["--endpoint", endpoint, "fetch", "method_1"]) == 1
    assert "secret" not in capsys.readouterr().err


def test_fetch_id_cannot_change_route(server, capsys):
    base, requests, _ = server
    assert client.main(["--endpoint", base, "fetch", "../search?secret"]) == 1
    assert requests == []
    assert "secret" not in capsys.readouterr().err
def test_context_forwards_budget_and_explicit_conditions_without_auth(server, monkeypatch, capsys):
    base, requests, state = server
    monkeypatch.setenv("OPENAKASHIC_RESEARCH_WRITE_KEY", "never-send-for-reads")
    state["response"] = {"schema": "method-context-v1", "items": []}
    assert client.main(["--endpoint", base, "context", "--situation", "공개 실험",
                        "--goal", "검증", "--forbids", "network", "--max-tokens", "512"]) == 0
    assert json.loads(capsys.readouterr().out) == state["response"]
    method, path, headers, body = requests[-1]
    query = parse_qs(urlsplit(path).query)
    assert method == "GET" and urlsplit(path).path.endswith("/context")
    assert query["mode"] == ["hybrid"] and query["max_tokens"] == ["512"]
    assert query["forbids"] == ["network"] and body is None
    assert "X-OpenAkashic-Key" not in headers


@pytest.mark.parametrize("command", ["search", "context", "bundle"])
def test_explicit_scope_forwarded_anonymously(server, command, capsys):
    base, requests, state = server
    assert client.main(["--endpoint", base, command, "--situation", "release issue",
                        "--goal", "restore service", "--domain", "개발·운영",
                        "--product", "postgresql"]) == 0
    capsys.readouterr()
    method, path, headers, body = requests[0]
    query = parse_qs(urlsplit(path).query)
    assert query["domain"] == ["개발·운영"]
    assert query["product"] == ["postgresql"]
    assert method == "GET" and body is None
    assert not any(name.lower() == "x-openakashic-key" for name in headers)
