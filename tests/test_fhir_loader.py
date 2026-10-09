import gzip
import json

import psycopg
import pytest

from rwe import db
from rwe.ingest.fhir_loader import BundleError, bundle_files, load, read_content, split_bundle


def make_bundle(patient_id: str, *others: dict) -> dict:
    resources = [{"resourceType": "Patient", "id": patient_id}, *others]
    entries = [{"resource": r} for r in resources]
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


ENCOUNTER = {"resourceType": "Encounter", "id": "enc-1", "status": "finished"}
CONDITION = {"resourceType": "Condition", "id": "cond-1", "code": {"text": "x"}}


def test_split_tags_every_resource_with_the_patient():
    rows = split_bundle(make_bundle("pat-1", ENCOUNTER, CONDITION))
    assert [(r.resource_type, r.resource_id, r.patient_id) for r in rows] == [
        ("Patient", "pat-1", "pat-1"),
        ("Encounter", "enc-1", "pat-1"),
        ("Condition", "cond-1", "pat-1"),
    ]
    assert json.loads(rows[2].payload) == CONDITION  # payload is lossless


@pytest.mark.parametrize(
    "bundle, message",
    [
        ({"resourceType": "Patient", "id": "p"}, "Expected a Bundle"),
        ({"resourceType": "Bundle", "entry": [{"resource": ENCOUNTER}]}, "found 0"),
        (make_bundle("p1", {"resourceType": "Patient", "id": "p2"}), "found 2"),
        (make_bundle("p1", {"resourceType": "Encounter"}), "without an id"),
    ],
)
def test_split_rejects_malformed_bundles(bundle, message):
    with pytest.raises(BundleError, match=message):
        split_bundle(bundle)


def test_gzipped_and_plain_files_are_the_same_input(tmp_path):
    content = json.dumps(make_bundle("p")).encode()
    (tmp_path / "a.json").write_bytes(content)
    (tmp_path / "b.json.gz").write_bytes(gzip.compress(content))
    assert read_content(tmp_path / "a.json") == ("a.json", content)
    assert read_content(tmp_path / "b.json.gz") == ("b.json", content)


def test_empty_directory_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        bundle_files(tmp_path)


def write_bundles(directory, *bundles):
    directory.mkdir(exist_ok=True)
    for i, bundle in enumerate(bundles):
        (directory / f"b{i}.json").write_text(json.dumps(bundle))
    return directory


@pytest.mark.db
def test_load_is_idempotent(db_conn, tmp_path):
    db.bootstrap(db_conn)
    fhir_dir = write_bundles(tmp_path / "fhir", make_bundle("p1", ENCOUNTER), make_bundle("p2"))
    first = load(db_conn, fhir_dir)
    second = load(db_conn, fhir_dir)
    assert (first.n_bundles, first.n_resources) == (2, 3)
    assert first.input_digest == second.input_digest
    count = db_conn.execute("SELECT count(*) FROM raw.fhir_resource").fetchone()[0]
    assert count == 3
    status = db_conn.execute(
        "SELECT payload->>'status' FROM raw.fhir_resource WHERE resource_id = 'enc-1'"
    ).fetchone()[0]
    assert status == "finished"  # queryable as JSONB


@pytest.mark.db
def test_failed_load_leaves_previous_state_intact(db_conn, tmp_path):
    db.bootstrap(db_conn)
    good = write_bundles(tmp_path / "good", make_bundle("p1", ENCOUNTER))
    load(db_conn, good)
    # The same Encounter id in two bundles violates the primary key mid-COPY.
    dup = write_bundles(
        tmp_path / "dup", make_bundle("p1", ENCOUNTER), make_bundle("p2", ENCOUNTER)
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        load(db_conn, dup)
    db_conn.rollback()
    patients = db_conn.execute("SELECT patient_id FROM raw.fhir_bundle").fetchall()
    assert patients == [("p1",)]
