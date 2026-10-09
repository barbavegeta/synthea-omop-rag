"""Load Synthea FHIR bundles into raw.fhir_resource: one row per resource, JSONB payload.

Python's job is deliberately small (ADR-0002): split bundles, attach the patient id,
bulk-load with COPY. All field extraction happens in dbt.

The load is a full refresh inside one transaction: truncate, then reload everything.
A failed load rolls back to the previous state, and reruns are idempotent.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import psycopg


class BundleError(ValueError):
    """A file that is not a single-patient FHIR bundle."""


@dataclass(frozen=True)
class ResourceRow:
    resource_type: str
    resource_id: str
    patient_id: str
    payload: str  # compact JSON text; Postgres parses it into jsonb during COPY


@dataclass
class LoadSummary:
    n_bundles: int = 0
    n_resources: int = 0
    by_type: Counter = field(default_factory=Counter)
    input_digest: str = ""


def bundle_files(fhir_dir: Path) -> list[Path]:
    files = sorted([*fhir_dir.glob("*.json"), *fhir_dir.glob("*.json.gz")])
    if not files:
        raise FileNotFoundError(f"No *.json or *.json.gz bundles in {fhir_dir}")
    return files


def read_content(path: Path) -> tuple[str, bytes]:
    """(logical name, uncompressed bytes). foo.json and foo.json.gz are the same input,
    so checksums of the gzipped CI fixture match the bundles Synthea wrote."""
    data = path.read_bytes()
    if path.suffix == ".gz":
        return path.name.removesuffix(".gz"), gzip.decompress(data)
    return path.name, data


def split_bundle(bundle: dict) -> list[ResourceRow]:
    """One row per entry, each tagged with the bundle's single Patient id."""
    if bundle.get("resourceType") != "Bundle":
        raise BundleError(f"Expected a Bundle, got {bundle.get('resourceType')!r}")
    resources = [entry["resource"] for entry in bundle.get("entry", [])]
    patients = [r for r in resources if r.get("resourceType") == "Patient"]
    if len(patients) != 1:
        raise BundleError(f"Expected exactly one Patient per bundle, found {len(patients)}")
    patient_id = patients[0]["id"]
    rows = []
    for resource in resources:
        if not resource.get("id"):
            raise BundleError(f"{resource.get('resourceType')} resource without an id")
        rows.append(
            ResourceRow(
                resource_type=resource["resourceType"],
                resource_id=resource["id"],
                patient_id=patient_id,
                payload=json.dumps(resource, separators=(",", ":")),
            )
        )
    return rows


def load(conn: psycopg.Connection, fhir_dir: Path) -> LoadSummary:
    summary = LoadSummary()
    file_digests = []
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("TRUNCATE raw.fhir_resource, raw.fhir_bundle")
        with cur.copy(
            "COPY raw.fhir_resource (resource_type, resource_id, patient_id, bundle_file, payload)"
            " FROM STDIN"
        ) as copy:
            bundle_rows = []
            for path in bundle_files(fhir_dir):
                name, content = read_content(path)
                sha = hashlib.sha256(content).hexdigest()
                try:
                    rows = split_bundle(json.loads(content))
                except BundleError as exc:
                    raise BundleError(f"{path.name}: {exc}") from exc
                for row in rows:
                    copy.write_row(
                        (row.resource_type, row.resource_id, row.patient_id, name, row.payload)
                    )
                summary.by_type.update(row.resource_type for row in rows)
                summary.n_bundles += 1
                summary.n_resources += len(rows)
                bundle_rows.append((name, sha, rows[0].patient_id, len(rows)))
                file_digests.append(f"{name}:{sha}")
        cur.executemany(
            "INSERT INTO raw.fhir_bundle (bundle_file, sha256, patient_id, n_resources)"
            " VALUES (%s, %s, %s, %s)",
            bundle_rows,
        )
    conn.execute("ANALYZE raw.fhir_resource")
    summary.input_digest = hashlib.sha256("\n".join(file_digests).encode()).hexdigest()
    return summary
