#!/usr/bin/env python3
"""Small, anonymous-read/local-write client for public method experiments."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

API_PATH = "/research/api/methods"


class ClientError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def endpoint_base(value):
    try:
        parsed = urlsplit(value)
        parsed.port  # Validate malformed or out-of-range ports before any request.
    except ValueError:
        raise ClientError("Invalid endpoint.")
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ClientError("Endpoint must be a base HTTP(S) host without credentials, query, fragment, or path.")
    return parsed, value.rstrip("/")


def method_id(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ClientError("Invalid method ID.")
    return value


def read_key(args):
    if args.key_file:
        try:
            key = Path(args.key_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            raise ClientError("Unable to read key file.")
    else:
        key = os.getenv("OPENAKASHIC_RESEARCH_WRITE_KEY") or os.getenv("OPENAKASHIC_WRITE_API_KEY") or ""
    if not key:
        raise ClientError("Write key required: use --key-file or OPENAKASHIC_RESEARCH_WRITE_KEY.")
    if any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ClientError("Invalid write key format.")
    return key


def run(args):
    parsed, base = endpoint_base(args.endpoint)
    writing = args.command in ("submit", "outcome", "opinion")
    headers = {"Accept": "application/json", "User-Agent": "OpenAkashic-Method-Agent/0.1"}
    body = None
    if writing:
        # Deliberately keep writes inside the isolated local experiment.
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ClientError("Writes require an explicit http://127.0.0.1:PORT endpoint; the public default is read-only.")
        if parsed.port is None:
            raise ClientError("Writes require an explicit loopback port.")
        token = args.idempotency_key
        if not token or len(token) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in token):
            raise ClientError("Idempotency key must contain 1..200 visible ASCII characters.")
        headers["X-OpenAkashic-Key"] = read_key(args)
        headers["Idempotency-Key"] = token
        headers["Content-Type"] = "application/json"
        try:
            payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            raise ClientError("Unable to read input JSON.")
        if not isinstance(payload, dict):
            raise ClientError("Input JSON must be an object.")
        # No consent/provenance fields are inferred or injected.
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    path = API_PATH
    if args.command in ("search", "context", "bundle"):
        query = {"situation": args.situation, "goal": args.goal, "limit": args.limit}
        if args.constraints:
            query["constraints"] = args.constraints
        for name in ("mode", "requires", "forbids"):
            value = getattr(args, name, None)
            if value and not (name == "mode" and value == "lexical"):
                query[name] = value
        if args.command in ("context", "bundle"):
            query["max_tokens"] = args.max_tokens
        path += "/" + args.command + "?" + urlencode(query)
    elif args.command == "evidence":
        path += "/evidence?" + urlencode({"query": args.query, "mode": args.mode,
                                          "max_tokens": args.max_tokens, "format": args.format})
    elif args.command in ("fetch", "outcome", "opinion"):
        path += "/" + method_id(args.id)
        if args.command != "fetch":
            path += "/outcomes" if args.command == "outcome" else "/opinions"
    request = Request(base + path, data=body, headers=headers, method="POST" if writing else "GET")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Error bodies can echo rejected input or auth. Never print them.
        summaries = {400: "request rejected", 401: "authentication required",
                     403: "access denied", 404: "method not found",
                     409: "idempotency conflict", 422: "input validation failed",
                     429: "request rate limited", 503: "service unavailable"}
        summary = "redirect refused" if 300 <= exc.code < 400 else summaries.get(exc.code, "request failed")
        raise ClientError("HTTP " + str(exc.code) + ": " + summary + ".")
    except (URLError, OSError, ValueError):
        raise ClientError("Request failed or response was not valid JSON.")
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            Path(args.output).write_text(output, encoding="utf-8")
        except (OSError, UnicodeError):
            raise ClientError("Unable to write output file.")
    else:
        print(output, end="")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="https://knowledge.openakashic.com")
    parser.add_argument("--key-file", help="Read write key from this file; never printed")
    parser.add_argument("--output", help="Save full public JSON response as UTF-8")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search")
    search.add_argument("--situation", required=True)
    search.add_argument("--goal", required=True)
    search.add_argument("--constraints", default="")
    search.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="lexical")
    search.add_argument("--requires", default="", help="Comma-separated explicitly required condition labels")
    search.add_argument("--forbids", default="", help="Comma-separated unavailable/forbidden condition labels")
    search.add_argument("--limit", type=int, choices=range(1, 21), default=5)
    context = commands.add_parser("context", help="Get token-bounded references; fetch before applying a procedure")
    context.add_argument("--situation", required=True)
    context.add_argument("--goal", required=True)
    context.add_argument("--constraints", default="")
    context.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="hybrid")
    context.add_argument("--requires", default="")
    context.add_argument("--forbids", default="")
    context.add_argument("--limit", type=int, choices=range(1, 6), default=3)
    context.add_argument("--max-tokens", type=int, choices=range(256, 2049), default=1024)
    bundle = commands.add_parser("bundle", help="Get whole methods atomically within a token budget")
    bundle.add_argument("--situation", required=True)
    bundle.add_argument("--goal", required=True)
    bundle.add_argument("--constraints", default="")
    bundle.add_argument("--mode", choices=("lexical", "semantic", "hybrid"), default="hybrid")
    bundle.add_argument("--requires", default="")
    bundle.add_argument("--forbids", default="")
    bundle.add_argument("--limit", type=int, choices=range(1, 6), default=3)
    bundle.add_argument("--max-tokens", type=int, choices=range(256, 4097), default=1024)
    evidence = commands.add_parser("evidence", help="Read exact original-source passages from an optional operator-installed index")
    evidence.add_argument("--query", required=True, help="Full user question, before answer generation")
    evidence.add_argument("--mode", choices=("source", "method"), default="source")
    evidence.add_argument("--format", choices=("legacy", "refs"), default="legacy",
                          help="Opt into canonical v3 IDs; legacy response remains the default")
    evidence.add_argument("--max-tokens", type=int, choices=range(1024, 4097), default=1024,
                          metavar="TOKENS", help="Complete response budget, 1024..4096 (default: 1024)")
    fetch = commands.add_parser("fetch")
    fetch.add_argument("id")
    for name in ("submit", "outcome", "opinion"):
        command = commands.add_parser(name)
        if name != "submit":
            command.add_argument("id")
        command.add_argument("--input", required=True, help="Path to public input JSON")
        command.add_argument("--idempotency-key", required=True)
    args = parser.parse_args(argv)
    try:
        run(args)
    except ClientError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
