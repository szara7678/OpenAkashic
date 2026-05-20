"""StackOverflow ingest helpers.

StackOverflow content is licensed under CC-BY-SA-4.0. Any downstream evidence
created from this module must preserve attribution metadata, including source
URL, author, license, and fetch timestamp, and must comply with share-alike
requirements when republished.
"""
from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


_STACKEXCHANGE_SEARCH_URL = "https://api.stackexchange.com/2.3/search/advanced"
_STACKEXCHANGE_ANSWERS_URL = "https://api.stackexchange.com/2.3/questions/{question_id}/answers"
_TIMEOUT_SECONDS = 10


def _ensure_https_url(url: str) -> None:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https":
        raise ValueError(f"only https URLs are allowed: {url}")


def _api_key_params() -> dict[str, str]:
    key = os.getenv("STACKEXCHANGE_KEY")
    return {"key": key} if key else {}


def _get_json(url: str, params: dict[str, object]) -> dict:
    _ensure_https_url(url)
    query = urlencode(params)
    full_url = f"{url}?{query}" if query else url
    request = Request(full_url)
    try:
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _fetch_best_answer(question_id: int) -> dict | None:
    url = _STACKEXCHANGE_ANSWERS_URL.format(question_id=question_id)
    params: dict[str, object] = {
        "site": "stackoverflow",
        "sort": "votes",
        "filter": "withbody",
        **_api_key_params(),
    }
    payload = _get_json(url, params)
    answers = [item for item in payload.get("items", []) if isinstance(item, dict)]
    accepted = next((item for item in answers if item.get("is_accepted") is True), None)
    if accepted is not None:
        return accepted
    scored_answers = [item for item in answers if int(item.get("score") or 0) >= 3]
    if not scored_answers:
        return None
    return max(scored_answers, key=lambda item: int(item.get("score") or 0))


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def search_stackoverflow(query: str, max_results: int = 5) -> list[dict]:
    params: dict[str, object] = {
        "site": "stackoverflow",
        "sort": "relevance",
        "filter": "withbody",
        "q": query,
        "pagesize": max_results,
        **_api_key_params(),
    }
    payload = _get_json(_STACKEXCHANGE_SEARCH_URL, params)
    questions = [item for item in payload.get("items", []) if isinstance(item, dict)]

    results: list[dict] = []
    for question in questions:
        if question.get("is_answered") is not True:
            continue
        question_id = question.get("question_id")
        if question_id is None:
            continue
        answer = _fetch_best_answer(int(question_id))
        if answer is None:
            continue
        owner = answer.get("owner") if isinstance(answer.get("owner"), dict) else {}
        results.append(
            {
                "question_id": int(question_id),
                "title": str(question.get("title") or ""),
                "link": str(question.get("link") or ""),
                "score": int(question.get("score") or 0),
                "is_answered": bool(question.get("is_answered")),
                "tags": list(question.get("tags") or []),
                "answer_body": str(answer.get("body") or ""),
                "source_url": str(question.get("link") or ""),
                "author": str(owner.get("display_name") or "unknown"),
                "license": "CC-BY-SA-4.0",
                "fetched_at": _utc_now_iso(),
            }
        )
    return results


def stackoverflow_to_evidence_payload(result: dict) -> dict:
    return {
        "content": result["answer_body"],
        "title": result["title"],
        "source_type": "stackoverflow",
        "attribution": {
            "source_url": result["source_url"],
            "author": result["author"],
            "license": result["license"],
            "fetched_at": result["fetched_at"],
        },
        "tags": result["tags"],
    }
