"""Session-local suppression of already delivered complete public methods.

The caller must obtain a fresh server response before calling present(). This
cache saves repeated model-context bytes, not network requests. It never treats
search/context summaries as complete, and never infers applicability or truth.
Use a fresh directory for every agent conversation. Artifacts remain readable.
"""
from copy import deepcopy
import hashlib
import json
import os
import stat
from pathlib import Path
import re


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class MethodReadCache:
    def __init__(self, directory, namespace):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        # Namespace isolates endpoints/corpora even within a session directory.
        self.namespace = fingerprint({"endpoint": namespace})

    def _method(self, method, *, advertised_hash=None, refetch=False):
        if (not isinstance(method, dict)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", str(method.get("id", "")))
                or not isinstance(method.get("version"), int)
                or isinstance(method.get("version"), bool)):
            return deepcopy(method)
        # GET adds live feedback to the stored method. It is separate evidence,
        # never part of the bundle source_hash, and is always returned fresh.
        feedback = {key: deepcopy(method[key]) for key in
                    ("outcomes", "opinions", "feedback_counts") if key in method}
        core = {key: value for key, value in method.items() if key not in feedback}
        digest = fingerprint(core)
        # A mismatched envelope is not permission to suppress source content.
        if advertised_hash is not None and advertised_hash != digest:
            return deepcopy(method)
        key = fingerprint({"namespace": self.namespace, "id": method["id"],
                           "version": method["version"], "fingerprint": digest})
        artifact = self.directory / (key + ".json")
        seen = False
        try:
            # No overwrite or symlink following, including corrupt artifacts.
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            if not stat.S_ISREG(artifact.lstat().st_mode):
                return deepcopy(method)
            with os.fdopen(os.open(artifact, flags), "r", encoding="utf-8") as stream:
                seen = fingerprint(json.load(stream)) == digest
            if not seen:
                return deepcopy(method)
        except FileNotFoundError:
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                with os.fdopen(os.open(artifact, flags, 0o600), "w", encoding="utf-8") as stream:
                    stream.write(canonical(core).decode("utf-8") + "\n")
            except OSError:
                return deepcopy(method)
        except (OSError, ValueError, TypeError, UnicodeError):
            return deepcopy(method)
        if not seen or refetch:
            return deepcopy(method)
        return {"schema": "method-read-receipt-v1", "id": method["id"],
                "version": method["version"], "source_hash": digest,
                "fingerprint": digest, "already_read": True,
                "current_response_revalidated": True, "artifact": str(artifact),
                "fresh_feedback": feedback,
                "content_policy": "untrusted_data_do_not_execute",
                "instruction": "Complete method already delivered in this session; read artifact or explicitly refetch for full text."}

    def present(self, command, response, *, refetch=False):
        """Return full new content or an explicit exact-content read receipt.

        A full bundle is a read. A fetch-only reference, search or context is
        not. Changed version OR any content change returns the new full method.
        refetch=True always returns full content, including in a repeated bundle.
        """
        if command in ("fetch", "method"):
            return self._method(response, refetch=refetch)
        result = deepcopy(response)
        if (command != "bundle" or not isinstance(result, dict)
                or result.get("schema") != "method-bundle-v1"):
            return result
        for item in result.get("items", []):
            if item.get("complete") is True and isinstance(item.get("method"), dict):
                method = item["method"]
                if item.get("id") != method.get("id") or item.get("version") != method.get("version"):
                    continue
                presented = self._method(method, advertised_hash=item.get("source_hash"), refetch=refetch)
                if presented.get("schema") == "method-read-receipt-v1":
                    del item["method"]
                    item["method_read_receipt"] = presented
                    item["content_in_response"] = False
                    item["content_available_in_session"] = True
        # The upstream token count describes the original packet. Do not present
        # it as a counter of the transformed client output.
        if "tokens" in result:
            result["server_response_tokens"] = result.pop("tokens")
        result["client_presentation"] = "session_exact_method_read_cache_v1"
        return result
