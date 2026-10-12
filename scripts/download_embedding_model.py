"""
Download a supported multilingual embedding model for OPENCRAB_EMBEDDING_MODEL.

Fetches the pinned ONNX export and tokenizer from the model's Hugging Face
repository into OPENCRAB_EMBEDDING_MODEL_DIR (default
~/.cache/opencrab/models/<model>). Only the files listed for the model in
opencrab.stores.onnx_embedding.MODELS are fetched, from the pinned commit,
and each one must match its recorded sha256. This is the only step that
touches the network; embedding itself runs locally.

Usage (from the repository root):
    python scripts/download_embedding_model.py multilingual-e5-small
    python scripts/download_embedding_model.py bge-m3 --dest /models/bge-m3
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from opencrab.stores.onnx_embedding import (  # noqa: E402
    MANIFEST_FILE,
    MODELS,
    check_model_dir,
    resolve_model_dir,
)

_HF = "https://huggingface.co"
LOCK_FILE = ".download.lock"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CHUNK = 1 << 20


def file_url(model: str, name: str) -> str:
    spec = MODELS[model]
    return f"{_HF}/{spec.repo}/resolve/{spec.revision}/onnx/{name}"


def fetch(url: str, target: Path, sha256: str) -> None:
    """Stream ``url`` to ``target``; keep it only if its sha256 matches."""
    if not _SAFE_NAME.match(target.name):
        raise ValueError(f"unsafe file name: {target.name!r}")
    # A private temporary file per call, so concurrent runs never share one.
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".part")
    part = Path(tmp_name)
    digest = hashlib.sha256()
    try:
        # Own the descriptor before connecting, so a failed connection still closes it.
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=60) as resp:
            while chunk := resp.read(_CHUNK):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sha256:
            raise ValueError(f"sha256 mismatch for {target.name}: got {digest.hexdigest()}, expected {sha256}")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(model: str, dest: Path) -> None:
    """Write the manifest through a temporary file so an existing link is replaced, not followed."""
    spec = MODELS[model]
    payload = json.dumps({"model": model, "repo": spec.repo, "revision": spec.revision}, indent=2)
    fd, tmp_name = tempfile.mkstemp(dir=dest, prefix=f".{MANIFEST_FILE}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as out:
            out.write(payload)
        Path(tmp_name).replace(dest / MANIFEST_FILE)
    finally:
        Path(tmp_name).unlink(missing_ok=True)


@contextlib.contextmanager
def directory_lock(dest: Path):
    """Serialize downloads into one directory (POSIX only; a no-op elsewhere)."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows
        yield
        return
    with open(dest / LOCK_FILE, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def ensure_files(model: str, dest: Path) -> int:
    """Make every pinned file in ``dest`` match its sha256; return how many were fetched.

    Files already present are checked, not trusted; only missing or mismatched
    files are downloaded. The manifest is removed first and written again only
    after all files match, so a failed repair never leaves a valid-looking
    directory behind.
    """
    dest.mkdir(parents=True, exist_ok=True)
    (dest / MANIFEST_FILE).unlink(missing_ok=True)
    fetched = 0
    for name, sha256 in MODELS[model].files:
        target = dest / name
        if target.is_file() and sha256_of(target) == sha256:
            continue
        print(f"  {name}", flush=True)
        fetch(file_url(model, name), target, sha256)
        fetched += 1
    write_manifest(model, dest)
    return fetched


def check_and_fetch(model: str, dest: Path) -> int:
    """Refuse a directory owned by another model, then verify or fetch every file."""
    spec = MODELS[model]
    manifest = dest / MANIFEST_FILE
    if manifest.is_file():
        try:
            recorded = json.loads(manifest.read_text())
        except ValueError:
            recorded = None  # unreadable manifest: rewritten once all files verify
        if isinstance(recorded, dict) and recorded.get("model") not in (None, model):
            raise ValueError(f"{dest} already holds {recorded.get('model')!r}; choose a different --dest")
    print(f"Checking {model} ({spec.repo}@{spec.revision[:12]}) in {dest}")
    fetched = ensure_files(model, dest)
    check_model_dir(model, dest)
    return fetched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument("--dest", type=Path, default=None, help="target directory")
    args = parser.parse_args(argv)
    dest = (args.dest or resolve_model_dir(args.model)).expanduser()
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with directory_lock(dest):
            fetched = check_and_fetch(args.model, dest)
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1
    print(f"Done ({fetched} file(s) downloaded, all checksums match).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
