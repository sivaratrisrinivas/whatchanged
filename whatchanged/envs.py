"""Cached `pip --target` installs of a given elevenlabs version, plus snapshot capture."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DEFAULT_CACHE = Path(".cache")
CAPTURE = Path(__file__).with_name("capture.py")


def env_dir(version: str, cache: Path) -> Path:
    return cache / "env" / version


def ensure_env(version: str, cache: Path) -> Path:
    d = env_dir(version, cache)
    if (d / "elevenlabs").is_dir():
        return d
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
         "--target", str(d), f"elevenlabs=={version}"],
        check=True,
    )
    return d


def snapshot(version: str, cache: Path, refresh: bool = False) -> dict:
    """Return the capture snapshot for a version, running capture.py in isolation (cached)."""
    snap = cache / "snapshots" / f"{version}.json"
    if snap.exists() and not refresh:
        return json.loads(snap.read_text())
    d = ensure_env(version, cache)
    proc = subprocess.run(
        [sys.executable, "-I", str(CAPTURE), str(d.resolve())],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"capture failed for {version}:\n{proc.stderr[-2000:]}")
    data = json.loads(proc.stdout)
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps(data))
    return data
