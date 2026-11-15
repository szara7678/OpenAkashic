"""Owner import of reviewed public skill originals; dry run unless --apply."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from app.research_skill_sources import (CATALOG, SourcePackages, bounded_bytes,
                                        safe_file)
from app.research_store import canonical
from app.research_methods import MethodRequest


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("owner writer redirects are forbidden")


def private_writer(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            parsed.path not in ("", "/", "/research/api/methods")):
        raise ValueError("plain private writer origin required")
    if parsed.hostname != "localhost":
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError as exc:
            raise ValueError("use localhost or a literal private writer address") from exc
        private_networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
        if not (address.is_loopback or any(address in ipaddress.ip_network(net) for net in private_networks)):
            raise ValueError("owner writer must be private or loopback")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/research/api/methods", "", ""))


def validate_plan(packages, path):
    if not path:
        return []
    data = json.loads(Path(path).read_text())
    if data.get("schema") != "public-skill-method-import-v1":
        raise ValueError("unsupported skill method import plan")
    rows, seen = [], set()
    for row in data.get("methods", []):
        public_id = row["public_id"]
        if not isinstance(public_id, str) or not public_id or len(public_id) > 100 or public_id in seen:
            raise ValueError("unique bounded method public_id required")
        seen.add(public_id)
        payload = MethodRequest.model_validate(row["payload"]).model_dump(mode="json")
        if not payload["skill_sources"]:
            raise ValueError("skill-derived methods require exact original source links")
        for link in payload["skill_sources"]:
            packages.validate_link(link)
        sha = hashlib.sha256(canonical(payload).encode()).hexdigest()
        rows.append({"public_id": public_id, "payload": payload, "payload_sha256": sha,
                     "idempotency_key": "public-skill-method-" + hashlib.sha256(
                         canonical([public_id, payload]).encode()).hexdigest()})
    if not 1 <= len(rows) <= 100:
        raise ValueError("bounded nonempty skill method plan required")
    return rows


def inspect_packages(packages):
    manifests = []
    for key in packages.ids:
        manifest = packages.manifest(key)
        base = packages.root / "packages" / key
        expected = set()
        for item in manifest["files"]:
            packages.file_bytes(key, item["path"])
            expected.add(item["path"])
        actual = set()
        original = base / "original"
        for path in original.rglob("*"):
            if path.is_symlink():
                raise ValueError("source symlinks are not allowed")
            if path.is_file():
                actual.add(path.relative_to(original).as_posix())
        if actual != expected:
            raise ValueError("original directory and pinned file manifest differ")
        manifests.append(manifest)
    return manifests


def external_runtime(path):
    target = Path(path).absolute()
    # In a checkout this file is public-methods/api/scripts/*.py; in a portable
    # release it is release/api/scripts/*.py. The module root is the boundary,
    # never its deployment parent (which also holds the external preview).
    code_root = Path(__file__).resolve().parents[2]
    checkout = code_root.parent
    boundary = checkout if (checkout / ".git").exists() else code_root
    if target.resolve().is_relative_to(boundary):
        raise ValueError("source runtime must stay outside the repository")
    for part in (target, *target.parents):
        if part.is_symlink():
            raise ValueError("runtime symlinks are forbidden")
    return target


def install_packages(source, manifests, target):
    target.mkdir(parents=True, exist_ok=True)
    external_runtime(target / "packages")
    (target / "packages").mkdir(exist_ok=True)
    # A prepared source root can itself be the deployment root; still verify it.
    if target.resolve() != source.root.resolve():
        for manifest in manifests:
            key = manifest["package_id"]
            destination = target / "packages" / key
            if destination.exists():
                if json.loads(bounded_bytes(safe_file(target,
                        "packages/" + key + "/manifest.json"), 1024 * 1024)) != manifest:
                    raise ValueError("immutable package already exists with different metadata")
                for item in manifest["files"]:
                    body = bounded_bytes(safe_file(target,
                        "packages/" + key + "/original/" + item["path"]), 2 * 1024 * 1024)
                    if len(body) != item["size_bytes"] or hashlib.sha256(body).hexdigest() != item["sha256"]:
                        raise ValueError("immutable package file differs")
                continue
            temporary = Path(tempfile.mkdtemp(prefix=".skill-import-", dir=target))
            try:
                original = temporary / "original"
                original.mkdir()
                for entry in manifest["files"]:
                    _, _, body = source.file_bytes(key, entry["path"])
                    file = original / entry["path"]
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(body)
                (temporary / "manifest.json").write_text(canonical(manifest) + "\n")
                temporary.rename(destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        prior_ids = []
        if (target / "catalog.json").exists():
            prior_ids = SourcePackages(target).ids
        ids = sorted(set(prior_ids + source.ids))
        if len(ids) > 1000:
            raise ValueError("merged source catalog exceeds package limit")
        fd, tmp = tempfile.mkstemp(prefix=".catalog-", dir=target)
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(canonical({"schema": CATALOG, "packages": ids}) + "\n")
            os.replace(tmp, target / "catalog.json")
        finally:
            if Path(tmp).exists():
                Path(tmp).unlink()
    inspect_packages(SourcePackages(target))


def save_receipt(path, result):
    target = external_runtime(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".skill-receipt-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(canonical(result) + chr(10))
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def import_sources(args):
    source_root = Path(args.input_manifest).parent if args.input_manifest else args.source_root
    source = SourcePackages(source_root)
    manifests = inspect_packages(source)
    rows = validate_plan(source, args.methods_plan)
    target = external_runtime(args.runtime_root)
    result = {"schema": "public-skill-import-receipt-v1", "dry_run": not args.apply,
              "packages": [item["package_id"] for item in manifests],
              "methods": [{key: row[key] for key in ("public_id", "payload_sha256", "idempotency_key")}
                          for row in rows],
              "content_policy": "untrusted_data_do_not_execute",
              "dependency_policy": "originals_preserved_dependencies_not_installed_or_executed"}
    if args.write_methods and (not args.apply or not args.receipt):
        raise ValueError("--write-methods requires --apply and external --receipt")
    writer = private_writer(args.writer_url) if args.write_methods else None
    key = os.environ.get(args.key_env, "") if args.write_methods else ""
    if args.write_methods and (not key or not rows):
        raise ValueError("owner writer credential and methods plan required")
    if args.receipt:
        external_runtime(args.receipt)
    if args.apply:
        install_packages(source, manifests, target)
    if args.write_methods:
        save_receipt(args.receipt, result)
        # Credentials are read only from the named environment variable, never copied to receipt.
        opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
        for row, receipt in zip(rows, result["methods"]):
            request = urllib.request.Request(writer, data=canonical(row["payload"]).encode(),
                headers={"Content-Type": "application/json", "X-OpenAkashic-Key": key,
                         "Idempotency-Key": row["idempotency_key"]}, method="POST")
            try:
                with opener.open(request, timeout=30) as response:
                    saved = json.loads(response.read(4 * 1024 * 1024))
            except urllib.error.HTTPError as exc:
                # Do not print error bodies, request headers or authenticated URLs.
                raise ValueError("owner writer rejected request (HTTP " + str(exc.code) + ")") from None
            if not saved.get("id") or saved.get("version") != 1:
                raise ValueError("writer returned unexpected method identity")
            receipt.update(id=saved["id"], version=saved["version"])
            # Persist each completed write so partial failures retain exact mappings.
            save_receipt(args.receipt, result)
    if args.receipt and args.apply:
        save_receipt(args.receipt, result)
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--source-root")
    group.add_argument("--input-manifest", help="prepared public source catalog.json")
    p.add_argument("--runtime-root", required=True)
    p.add_argument("--methods-plan")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--write-methods", action="store_true")
    p.add_argument("--writer-url", default="http://127.0.0.1:8000")
    p.add_argument("--key-env", default="OPENAKASHIC_RESEARCH_WRITE_KEY")
    p.add_argument("--receipt")
    return p


if __name__ == "__main__":
    try:
        print(json.dumps(import_sources(parser().parse_args()), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        # Exception messages are controlled validation errors, never source/request payloads.
        raise SystemExit(str(exc))
