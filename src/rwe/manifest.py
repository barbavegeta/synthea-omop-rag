"""Run manifest: a JSON record of everything needed to reproduce a run.

Each pipeline run writes one to data/runs/<UTC timestamp>/manifest.json. Later phases
add their own entries (Synthea version, Athena vocabulary release, embedding model
revision, test-set hash) through `extra`.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from rwe.config import REPO_ROOT, PipelineConfig

TRACKED_PACKAGES = ("rwe", "psycopg", "pydantic", "typer")
RUNS_DIR = REPO_ROOT / "data" / "runs"


def git_state(repo: Path = REPO_ROOT) -> dict[str, Any]:
    """Commit SHA and whether the working tree had uncommitted changes."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout
    except OSError, subprocess.CalledProcessError:
        return {"sha": None, "dirty": None}
    return {"sha": sha, "dirty": bool(status.strip())}


def package_versions(names: tuple[str, ...] = TRACKED_PACKAGES) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def build_manifest(cfg: PipelineConfig, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git": git_state(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": package_versions(),
        "config_profile": cfg.profile,
        "config_fingerprint": cfg.fingerprint(),
        "seeds": {
            "global": cfg.seed,
            "synthea": cfg.synthea.seed,
            "synthea_clinician": cfg.synthea.clinician_seed,
        },
        "config": cfg.model_dump(mode="json"),
        **(extra or {}),
    }


def write_manifest(manifest: dict[str, Any], runs_dir: Path = RUNS_DIR) -> Path:
    stamp = manifest["created_utc"].replace(":", "").replace("-", "")
    path = runs_dir / stamp / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path
