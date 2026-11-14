import http.client
import io
import socket
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from demo import fake_server
from solution import HTTPFailure, InvalidJSON, TransportFailure, fetch_json


class FetchJSONTests(unittest.TestCase):
    def test_local_server(self):
        with fake_server() as (server, base):
            for path, expected in (("/null", None), ("/false", False), ("/empty", []), ("/object", {"ok": True})):
                with self.subTest(path=path):
                    actual = fetch_json(base + path)
                    self.assertEqual(actual, expected)
                    self.assertIs(type(actual), type(expected))
            for path in ("/bad", "/utf8"):
                with self.subTest(path=path), self.assertRaises(InvalidJSON) as caught:
                    fetch_json(base + path)
                self.assertIsNotNone(caught.exception.__cause__)
            for path, status in (("/error", 503), ("/redirect", 302), ("/missing", 404)):
                with self.subTest(path=path), self.assertRaises(HTTPFailure) as caught:
                    fetch_json(base + path)
                self.assertEqual(caught.exception.status, status)
                self.assertLessEqual(len(caught.exception.body), 200)
                self.assertIsInstance(caught.exception.__cause__, HTTPError)
            with self.assertRaises(TransportFailure) as caught:
                fetch_json(base + "/slow", timeout=0.02)
            self.assertIsNotNone(caught.exception.__cause__)
            self.assertEqual(len(server.requests), 10)
            self.assertEqual(server.requests.count("/object"), 1)

    def test_body_timeout_truncation_and_http_priority(self):
        with fake_server() as (server, base):
            for path in ("/slow-body", "/truncated"):
                with self.subTest(path=path), self.assertRaises(TransportFailure) as caught:
                    fetch_json(base + path, timeout=0.02)
                self.assertIsNotNone(caught.exception.__cause__)
            with self.assertRaises(HTTPFailure) as caught:
                fetch_json(base + "/slow-error", timeout=0.02)
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(caught.exception.body, "")
            self.assertIsInstance(caught.exception.__cause__, TimeoutError)
            self.assertEqual(len(server.requests), 3)

    def test_connection_refused(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
            with self.assertRaises(TransportFailure) as caught:
                fetch_json(f"http://127.0.0.1:{port}", timeout=0.1)
            self.assertIsInstance(caught.exception.__cause__, URLError)

    def test_success_decoding_and_close(self):
        cases = [
            (b"null", None), (b"false", False), (b"[]", []),
            (b"0", 0), (b'""', ""), (b"true", True),
            (b"1.5", 1.5), ('"snowman \u2603"'.encode(), "snowman \u2603"),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                response = io.BytesIO(payload)
                with patch("solution.build_opener") as builder:
                    builder.return_value.open.return_value = response
                    self.assertEqual(fetch_json("http://local/", timeout=0.25), expected)
                    builder.return_value.open.assert_called_once_with("http://local/", timeout=0.25)
                self.assertTrue(response.closed)

    def test_invalid_json_closes_and_chains(self):
        for payload in (b"", b"{", b'"\xff"', b"NaN", b"Infinity", b"-Infinity", b"{} {}", b"\xff\xfe{}"):
            with self.subTest(payload=payload):
                response = io.BytesIO(payload)
                with patch("solution.build_opener") as builder:
                    builder.return_value.open.return_value = response
                    with self.assertRaises(InvalidJSON) as caught:
                        fetch_json("http://local/")
                self.assertTrue(response.closed)
                self.assertIsInstance(caught.exception.__cause__, ValueError)

    def test_http_priority_bounded_body_and_close(self):
        for payload in (b"not json", b"\xff" * 1000, "\u2603".encode() * 1000):
            response = io.BytesIO(payload)
            error = HTTPError("http://local/", 500, "failure", {}, response)
            with patch("solution.build_opener") as builder:
                builder.return_value.open.side_effect = error
                with self.assertRaises(HTTPFailure) as caught:
                    fetch_json("http://local/")
                builder.return_value.open.assert_called_once()
            self.assertEqual(caught.exception.body, payload[:800].decode("utf-8", "replace")[:200])
            self.assertEqual(caught.exception.status, 500)
            self.assertIs(caught.exception.__cause__, error)
            self.assertTrue(response.closed)

    def test_transport_failures_no_retry(self):
        for error in (URLError("DNS failure"), TimeoutError(), ConnectionResetError(), http.client.BadStatusLine("bad")):
            with patch("solution.build_opener") as builder:
                builder.return_value.open.side_effect = error
                with self.assertRaises(TransportFailure) as caught:
                    fetch_json("http://local/")
                self.assertIs(caught.exception.__cause__, error)
                builder.return_value.open.assert_called_once()

    def test_read_failure_closes(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        error = http.client.IncompleteRead(b"{", 10)
        response.read.side_effect = error
        with patch("solution.build_opener") as builder:
            builder.return_value.open.return_value = response
            with self.assertRaises(TransportFailure) as caught:
                fetch_json("http://local/")
        self.assertIs(caught.exception.__cause__, error)
        response.__exit__.assert_called_once()

    def test_http_body_read_failure_preserves_status(self):
        response = Mock()
        response.closed = False
        read_error = http.client.IncompleteRead(b"partial", 10)
        response.read.side_effect = read_error
        error = HTTPError("http://local/", 503, "failure", {}, response)
        with patch("solution.build_opener") as builder:
            builder.return_value.open.side_effect = error
            with self.assertRaises(HTTPFailure) as caught:
                fetch_json("http://local/")
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.body, "partial")
        self.assertIs(caught.exception.__cause__, read_error)
        response.close.assert_called_once()

    def test_invalid_arguments(self):
        for timeout in (0, -1, float("nan"), float("inf"), None, "2"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                fetch_json("http://local/", timeout=timeout)
        for url in ("file:///tmp/test", "data:,null", "localhost", None):
            with self.subTest(url=url), self.assertRaises(ValueError):
                fetch_json(url)


if __name__ == "__main__":
    unittest.main()
