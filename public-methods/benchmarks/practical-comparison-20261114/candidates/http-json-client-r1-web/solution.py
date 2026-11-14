"""A single-attempt, standard-library HTTP JSON client."""

import http.client
import json
import math
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


class HTTPFailure(Exception):
    """A non-2xx response, with a bounded diagnostic body."""

    def __init__(self, status, body):
        self.status = int(status)
        self.body = body[:200]
        super().__init__(f"HTTP {self.status}: {self.body}")


class InvalidJSON(Exception):
    """A successful response did not contain valid UTF-8 JSON."""


class TransportFailure(Exception):
    """The request or response could not be transported."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def _reject_constant(value):
    raise ValueError(f"Invalid JSON constant: {value}")


def fetch_json(url, *, timeout=2.0):
    """GET HTTP(S) JSON once; timeout is a positive socket-operation timeout.

    Redirects and environment proxies are disabled. Invalid arguments raise
    ValueError; network failures and response failures use the public exceptions.
    """
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number of seconds")
    if not isinstance(url, str) or urlsplit(url).scheme.lower() not in ("http", "https"):
        raise ValueError("url must be an HTTP or HTTPS URL string")

    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        try:
            response = opener.open(url, timeout=timeout)
        except HTTPError as error:
            with error:
                try:
                    body = error.read(800).decode("utf-8", errors="replace")[:200]
                except (OSError, http.client.HTTPException) as read_error:
                    partial = getattr(read_error, "partial", b"")
                    body = partial[:800].decode("utf-8", errors="replace")[:200]
                    raise HTTPFailure(error.code, body) from read_error
                raise HTTPFailure(error.code, body) from error
        with response:
            payload = response.read()
    except (URLError, OSError, http.client.HTTPException) as error:
        raise TransportFailure("HTTP transport failed") from error

    try:
        text = payload.decode("utf-8")
        return json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise InvalidJSON("Response is not valid UTF-8 JSON") from error
