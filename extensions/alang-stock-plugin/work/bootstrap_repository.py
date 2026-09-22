#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bootstrap Big-A-chovy in cloud/Work environments without relying on HTTP/2.

Why this exists
---------------
Some browser-backed cloud environments can fail while opening/downloading a
GitHub repository with ``net::ERR_HTTP2_PROTOCOL_ERROR``.  This bootstrap avoids
that path completely: Python's urllib client downloads the GitHub codeload ZIP
using HTTP/1.1-compatible stdlib networking, retries transient failures, verifies
that the expected runner exists, and extracts to a predictable directory.

This file is additive and does not modify upstream Big-A-chovy files.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_REPO = "GeorgeCao1987/Big-A-chovy"
DEFAULT_REF = "feature/alang-cloud-plugin-v2"
DEFAULT_DEST = "Big-A-chovy"
EXPECTED_RUNNER = Path("extensions/alang-stock-plugin/work/runner.py")


def _receipt(event: str, **extra) -> None:
    payload = {
        "alang_bootstrap": True,
        "event": event,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        **extra,
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _download(url: str, target: Path, retries: int = 5, timeout: int = 45) -> None:
    # urllib/http.client does not negotiate Chromium's HTTP/2 stack; this is
    # intentionally used as the fallback for browser HTTP/2 protocol errors.
    ctx = ssl.create_default_context()
    headers = {
        "User-Agent": "alang-stock-work-bootstrap/1.0",
        "Accept": "application/zip,application/octet-stream,*/*",
        "Connection": "close",
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    raise RuntimeError(f"unexpected HTTP status: {status}")
                with target.open("wb") as fh:
                    shutil.copyfileobj(resp, fh, length=1024 * 1024)
            if target.stat().st_size < 1024:
                raise RuntimeError("downloaded archive is unexpectedly small")
            return
        except Exception as exc:  # transient network/provider failures
            last_error = exc
            _receipt("download_retry", attempt=attempt, error=f"{type(exc).__name__}: {exc}")
            if attempt < retries:
                time.sleep(min(8, 2 ** (attempt - 1)))
    raise RuntimeError(f"repository download failed after {retries} attempts: {last_error}")


def _safe_extract(zf: zipfile.ZipFile, target: Path) -> None:
    target_resolved = target.resolve()
    for member in zf.infolist():
        out = (target / member.filename).resolve()
        if target_resolved not in out.parents and out != target_resolved:
            raise RuntimeError(f"unsafe zip member: {member.filename}")
    zf.extractall(target)


def bootstrap(repo: str, ref: str, dest: Path, force: bool = False) -> Path:
    if "/" not in repo:
        raise ValueError("repo must be owner/name")
    owner, name = repo.split("/", 1)
    dest = dest.resolve()

    if dest.exists():
        runner = dest / EXPECTED_RUNNER
        if runner.exists() and not force:
            _receipt("reuse_existing", repo=repo, ref=ref, path=str(dest), runner=str(runner))
            return dest
        if not force:
            raise RuntimeError(f"destination already exists but runner is missing: {dest}; use --force to replace it")
        shutil.rmtree(dest)

    # GitHub codeload accepts branch names containing '/'. urllib percent-encodes
    # only the path-safe portions below so refs such as feature/foo remain valid.
    from urllib.parse import quote

    encoded_ref = quote(ref, safe="/")
    url = f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/{encoded_ref}"
    _receipt("download_start", repo=repo, ref=ref, url=url)

    with tempfile.TemporaryDirectory(prefix="alang_repo_bootstrap_") as td:
        tmp_dir = Path(td)
        archive = tmp_dir / "repo.zip"
        unpack = tmp_dir / "unpack"
        unpack.mkdir(parents=True, exist_ok=True)
        _download(url, archive)
        with zipfile.ZipFile(archive) as zf:
            _safe_extract(zf, unpack)

        roots = [p for p in unpack.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(f"unexpected archive layout: {len(roots)} roots")
        extracted = roots[0]
        runner = extracted / EXPECTED_RUNNER
        if not runner.exists():
            raise RuntimeError(f"archive does not contain expected runner: {EXPECTED_RUNNER}")

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(extracted), str(dest))

    runner = dest / EXPECTED_RUNNER
    _receipt(
        "ready",
        repo=repo,
        ref=ref,
        path=str(dest),
        runner=str(runner),
        python=sys.executable,
    )
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Big-A-chovy without browser HTTP/2")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--dest", default=DEFAULT_DEST)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        root = bootstrap(args.repo, args.ref, Path(args.dest), args.force)
    except Exception as exc:
        _receipt("failed", error=f"{type(exc).__name__}: {exc}")
        return 2
    print(str(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
