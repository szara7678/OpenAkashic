import re
from typing import Any
from uuid import UUID


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def json_ready(row: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, UUID):
            output[key] = str(value)
        elif isinstance(value, list):
            output[key] = [str(item) if isinstance(item, UUID) else item for item in value]
        else:
            output[key] = value
    return output


def extract_mentions(text: str) -> list[str]:
    candidates: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9_+#./~-]{3,}|[\u3040-\u30ffー〜]{2,}|[\uac00-\ud7a3]{2,}", text):
        normalized = normalize_text(token)
        if normalized and len(normalized) >= 2:
            candidates.add(normalized)
    return sorted(candidates)[:12]
