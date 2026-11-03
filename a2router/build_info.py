"""Release provenance collection (build-time) and embedded metadata reading."""

import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from a2router import __version__


def collect_build_info(source_root, native_dll=None):
    def git(*args):
        try:
            result = subprocess.run(
                ["git", "-C", str(source_root), *args], capture_output=True, text=True, check=False, timeout=5
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    status = git("status", "--porcelain")
    packages = {}
    for name in ("PySide6-Essentials", "shiboken6", "numpy", "pyinstaller", "cmake", "ninja"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            continue
    return {
        "app_version": __version__,
        "source_commit": git("rev-parse", "HEAD") or os.environ.get("GITHUB_SHA"),
        "source_dirty": status != "" if status is not None else None,
        "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workflow": {
            key: os.environ.get(variable)
            for key, variable in (
                ("name", "GITHUB_WORKFLOW"),
                ("run_id", "GITHUB_RUN_ID"),
                ("attempt", "GITHUB_RUN_ATTEMPT"),
                ("repository", "GITHUB_REPOSITORY"),
            )
        },
        "native_dll_sha256": hashlib.sha256(Path(native_dll).read_bytes()).hexdigest()
        if native_dll
        else None,
        "python": sys.version,
        "packages": packages,
    }


def read_build_info(path=None):
    if path is None and not getattr(sys, "frozen", False):
        return {"app_version": __version__, "development": True}
    try:
        data = json.loads(
            (Path(path) if path else Path(__file__).parent / "assets/build-info.json").read_text()
        )
        return data if isinstance(data, dict) else {"app_version": __version__}
    except (OSError, ValueError):
        return {"app_version": __version__}


def about_text():
    data = read_build_info()
    workflow = data.get("workflow")
    workflow = workflow if isinstance(workflow, dict) else {}
    state = data.get("source_dirty")
    dirty = "modified tree" if state is True else "clean tree" if state is False else "tree state unknown"
    return (
        f"A2Router {data.get('app_version', __version__)} — Advanced Audio Router\n"
        f"Source: {data.get('source_commit') or 'development / metadata unavailable'} ({dirty})\n"
        f"Built UTC: {data.get('built_at_utc') or 'not packaged'}\n"
        f"Workflow run: {workflow.get('run_id') or 'local / unknown'}\n"
        f"Native DLL SHA-256: {data.get('native_dll_sha256') or 'not included / unavailable'}\n\n"
        "Native WASAPI / PipeWire audio routing\nBased on MultiRoute. Developed with OpenAI Codex.\n"
        "VB-CABLE © VB-Audio Software."
    )
