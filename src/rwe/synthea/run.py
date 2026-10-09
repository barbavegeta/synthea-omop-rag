"""Fetch (once, checksum-verified) and run Synthea.

Generation is the slowest step, so it is skipped when the output directory carries a
stamp whose key matches the current inputs (Synthea settings + properties file + jar).
Any change to those inputs regenerates from scratch, so stale output never mixes in.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import subprocess
import urllib.request
from pathlib import Path

from rwe.config import REPO_ROOT, SyntheaConfig

DATA_DIR = REPO_ROOT / "data" / "synthea"
PROPERTIES = REPO_ROOT / "config" / "synthea.properties"
STAMP_NAME = ".generation_key"


def jar_url(version: str) -> str:
    return (
        "https://github.com/synthetichealth/synthea/releases/download/"
        f"v{version}/synthea-with-dependencies.jar"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_jar(cfg: SyntheaConfig, bin_dir: Path = DATA_DIR / "bin") -> Path:
    """Download the pinned release if absent; refuse to run a jar with the wrong hash."""
    path = bin_dir / f"synthea-{cfg.version}.jar"
    if not path.exists():
        bin_dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(".part")
        urllib.request.urlretrieve(jar_url(cfg.version), partial)
        partial.rename(path)
    actual = sha256_file(path)
    if actual != cfg.jar_sha256:
        raise RuntimeError(
            f"{path.name}: SHA-256 {actual} does not match pinned {cfg.jar_sha256}. "
            "Delete the file to re-download, or update synthea.jar_sha256 deliberately."
        )
    return path


def synthea_args(cfg: SyntheaConfig, out_dir: Path) -> list[str]:
    return [
        "-p", str(cfg.population),
        "-s", str(cfg.seed),
        "-cs", str(cfg.clinician_seed),
        "-r", cfg.reference_date.strftime("%Y%m%d"),
        "-e", cfg.end_date.strftime("%Y%m%d"),
        "-c", str(PROPERTIES),
        f"--exporter.baseDirectory={out_dir}/",
        f"--exporter.years_of_history={cfg.years_of_history}",
        cfg.state,
    ]  # fmt: skip


def generation_key(cfg: SyntheaConfig) -> str:
    """Hash of every input that determines Synthea's output."""
    payload = json.dumps(
        {
            "synthea": cfg.model_dump(mode="json", exclude={"generate"}),
            "properties": PROPERTIES.read_text(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def generate(cfg: SyntheaConfig, out_dir: Path) -> dict:
    """Run Synthea into out_dir (FHIR lands in out_dir/fhir). Returns manifest info."""
    out_dir = out_dir.resolve()
    if not out_dir.is_relative_to(DATA_DIR):
        raise ValueError(f"Refusing to generate outside {DATA_DIR}: {out_dir}")
    key = generation_key(cfg)
    info = {"version": cfg.version, "jar_sha256": cfg.jar_sha256, "generation_key": key}
    stamp = out_dir / STAMP_NAME
    if stamp.exists() and stamp.read_text() == key:
        return {**info, "skipped": True}

    jar = ensure_jar(cfg)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    # UTC: the JVM otherwise renders timestamps in the machine's local zone, so the same
    # seed would produce different offsets (and near midnight, different dates) per machine.
    command = ["java", "-Duser.timezone=UTC", "-jar", str(jar), *synthea_args(cfg, out_dir)]
    subprocess.run(command, check=True, cwd=out_dir)
    stamp.write_text(key)
    return {**info, "skipped": False}


def write_fixture(fhir_dir: Path, fixture_dir: Path) -> list[Path]:
    """Gzip patient bundles into fixture_dir. mtime=0 makes the .gz bytes reproducible."""
    if fixture_dir.exists():
        shutil.rmtree(fixture_dir)
    fixture_dir.mkdir(parents=True)
    written = []
    for src in sorted(fhir_dir.glob("*.json")):
        dst = fixture_dir / f"{src.name}.gz"
        with dst.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(src.read_bytes())
        written.append(dst)
    return written
