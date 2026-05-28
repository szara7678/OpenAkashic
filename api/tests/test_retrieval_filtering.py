from __future__ import annotations

import sys
import types
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
_previous_sys_path = list(sys.path)
_previous_app_modules = {
    module_name: module
    for module_name, module in sys.modules.items()
    if module_name == "app" or module_name.startswith("app.")
}
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
elif sys.path[0] != str(API_ROOT):
    sys.path.remove(str(API_ROOT))
    sys.path.insert(0, str(API_ROOT))

for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

db_stub = types.ModuleType("app.db")
db_stub.get_conn = lambda: None
sys.modules.setdefault("app.db", db_stub)

embeddings_stub = types.ModuleType("app.embeddings")
embeddings_stub.EmbeddingError = RuntimeError
embeddings_stub.embed_one = lambda *args, **kwargs: None
sys.modules.setdefault("app.embeddings", embeddings_stub)

from app import retrieval  # noqa: E402

for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]
sys.modules.update(_previous_app_modules)
sys.path[:] = _previous_sys_path


def test_dedupe_claim_rows_keeps_one_normalized_text_and_prefers_metadata():
    rows = [
        {"id": "plain", "text": "Same claim text", "score": 0.8, "metadata": {}},
        {
            "id": "rich",
            "text": " same   claim text ",
            "score": 0.8,
            "metadata": {"source_note": "personal_vault/source.md", "confirm_count": 2},
        },
        {"id": "other", "text": "Other claim text", "score": 0.7, "metadata": {}},
    ]

    deduped = retrieval._dedupe_claim_rows(rows, top_k=10)

    assert [row["id"] for row in deduped] == ["rich", "other"]


def test_dedupe_claim_rows_excludes_publication_request_artifacts():
    rows = [
        {
            "id": "request",
            "text": "Request text",
            "score": 1.0,
            "metadata": {"kind": "publication_request"},
        },
        {
            "id": "request-path",
            "text": "Request path text",
            "score": 0.9,
            "metadata": {"source_note": "personal_vault/projects/ops/librarian/publication_requests/x.md"},
        },
        {"id": "claim", "text": "Normal text", "score": 0.5, "metadata": {}},
    ]

    deduped = retrieval._dedupe_claim_rows(rows, top_k=10)

    assert [row["id"] for row in deduped] == ["claim"]
