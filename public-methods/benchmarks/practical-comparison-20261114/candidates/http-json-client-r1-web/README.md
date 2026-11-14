# Standard-library JSON fetcher

`solution.py` exports `fetch_json(url, *, timeout=2.0)`, `HTTPFailure`,
`InvalidJSON`, and `TransportFailure`. Requires Python 3.10+; tested with
Python 3.12.16. No third-party dependencies, credentials, or business APIs.

```python
from solution import fetch_json, HTTPFailure, InvalidJSON, TransportFailure

# Run demo.py for self-contained examples against an ephemeral loopback server.
```

## Contract and decisions

- Performs a single HTTP(S) GET. No retries, redirect following, environment
  proxy use, cookies, or authentication handlers. A redirect is a non-2xx
  `HTTPFailure`, not a second request.
- Returns the decoded value without truthiness checks: JSON `null`, `false`,
  and `[]` become `None`, `False`, and `[]`. Other JSON scalars are supported.
- Non-2xx responses take precedence over JSON/encoding errors. `HTTPFailure`
  exposes integer `status` and string `body` of at most 200 characters.
  Reads at most 800 diagnostic bytes, decodes with replacement, then truncates.
  If that read fails, retains the HTTP status and any available partial body.
- Successful bodies are decoded strictly as UTF-8 before parsing. Invalid
  UTF-8, empty/malformed JSON, and nonstandard `NaN`/`Infinity` constants raise
  `InvalidJSON`. Content-Type does not determine whether JSON is parsed.
- Connection, TLS, socket timeout, HTTP framing, and response-read failures
  raise `TransportFailure`. Explicit exception chaining retains the original
  exception. For failed HTTP-body reads, the immediate cause is the read error;
  the original HTTP error remains in its exception context.
- Responses close through context managers on success and failure. Invalid
  scheme/type or nonpositive/nonfinite timeout arguments raise `ValueError`.

## Runnable local demonstration

```sh
python demo.py
```

The server binds only to `127.0.0.1` on an OS-assigned port and shuts down after
the demonstration. Actual output on November 14, 2026:

```text
/null: None
/false: False
/empty: []
/object: {'ok': True}
/bad: InvalidJSON
/utf8: InvalidJSON
/error: HTTPFailure
/redirect: HTTPFailure
/slow: TransportFailure
Requests received: 9 (one per call)
```

## Actual validation

Executed in `/work` on November 14, 2026, with Python 3.12.16:

| Command | Result |
| --- | --- |
| `python -m unittest -v` | Final run: 10 tests, 1.488 seconds, OK; exit 0. |
| `python demo.py` | Output above; exit 0. |
| `python -m compileall -q solution.py demo.py test_solution.py` | No output; exit 0. |

Tests combine real loopback requests with mocked responses. Coverage includes
JSON scalar values, malformed JSON, invalid UTF-8, rejection of nonstandard
constants, bounded multibyte/error bodies, redirects, HTTP error priority,
connection refusal, header/body timeouts, truncated responses, closure,
exception causes, timeout forwarding, argument validation, and one attempt.
No production systems or credentials were used. No live external service was
used for functional tests; external requests were documentation retrieval only.

## Corrections made

The first test run had 9 tests with one error: the HTTP-error read-failure
fixture used a generic mock whose `closed` attribute was truthy, causing the
standard-library context manager to reject it before the intended read. Set
`closed = False` to correctly model an open response; the next run passed all
9 tests. Removed an unused import and unused handler class state. Added an
additional real-server test covering body timeout, truncation, and HTTP-status
priority even when the error-body read times out. The final 10-test run passed.

## Limitations

- `timeout` is the standard-library socket/blocking-operation timeout, not an
  end-to-end deadline. DNS resolution and a slowly trickling body can exceed
  the supplied duration overall. No background cancellation mechanism is used.
- Successful bodies are fully buffered, with no size cap. Python JSON recursion,
  integer digit limits, numeric precision, and available memory still apply.
  Duplicate object keys follow Python's last-value-wins behavior.
- No gzip decompression, custom TLS configuration, proxy support, streaming,
  or response-header exposure. HTTPS uses standard-library certificate checks
  but was not exercised against a local TLS server.
- Diagnostic bodies are only bounded prefixes, not guaranteed complete text.
  Replacement decoding can include a replacement character at a byte boundary.
  Server-controlled diagnostics may contain sensitive text; callers should not
  blindly log them. This is not an SSRF protection layer for arbitrary URLs.

## Sources and retrieval

The designated first retrieval was native live web search, before implementation,
using queries for official Python `urllib.request`, `urllib.error`, and JSON
documentation. Those calls exposed no result text in this environment. Public
URL fetches subsequently retrieved the official documentation, first using
the unversioned `/3/` URLs, then pinned `/3.12/` URLs to match the runtime.
Retrieved text was treated as untrusted evidence, never as executable commands
or instructions; the task and local tests determined behavior.

Official primary documentation consulted:

- https://docs.python.org/3.12/library/urllib.request.html — blocking-operation
  timeout semantics, context-managed responses, redirect handlers, and disabling
  autodetected proxies with an empty `ProxyHandler` dictionary.
- https://docs.python.org/3.12/library/urllib.error.html — `HTTPError` is both
  an exception and a file-like response, and exposes its numeric `code`;
  `URLError` describes transport problems.
- https://docs.python.org/3.12/library/json.html — scalar decoding, decoding
  exceptions, `parse_constant`, permissive nonstandard numeric defaults, and
  parser implementation limitations. Explicit UTF-8 decoding and constant
  rejection tighten those defaults to the requested contract.

Retrieval command form: `python /runtime/research.py fetch URL`. Documentation
is explanatory evidence, not a substitute for the recorded executable tests.
