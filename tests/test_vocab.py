import json

import pytest

from rwe import db
from rwe.ingest import fhir_loader
from rwe.vocab import load_athena, stub

TAB = "\t"

ATHENA_FILES = {
    "CONCEPT.csv": [
        "concept_id\tconcept_name\tdomain_id\tvocabulary_id\tconcept_class_id\tstandard_concept\tconcept_code\tvalid_start_date\tvalid_end_date\tinvalid_reason",
        # A literal double quote inside a name: breaks a loader that uses CSV quoting.
        '1\t5" gauze pad\tDevice\tSNOMED\tPhysical Object\tS\t111\t19700101\t20991231\t',
        "2\tOld code\tCondition\tICD10CM\t3-char nonbill code\t\tA00\t19700101\t20991231\t",
    ],
    "VOCABULARY.csv": [
        "vocabulary_id\tvocabulary_name\tvocabulary_reference\tvocabulary_version\tvocabulary_concept_id",
        "None\tOMOP Standardized Vocabularies\tOMOP generated\tv5.0 TEST\t44819096",
    ],
    "DOMAIN.csv": ["domain_id\tdomain_name\tdomain_concept_id", "Condition\tCondition\t19"],
    "CONCEPT_CLASS.csv": ["concept_class_id\tconcept_class_name\tconcept_class_concept_id"],
    "RELATIONSHIP.csv": [
        "relationship_id\trelationship_name\tis_hierarchical\tdefines_ancestry\treverse_relationship_id\trelationship_concept_id"
    ],
    "CONCEPT_RELATIONSHIP.csv": [
        "concept_id_1\tconcept_id_2\trelationship_id\tvalid_start_date\tvalid_end_date\tinvalid_reason",
        "2\t1\tMaps to\t19700101\t20991231\t",
    ],
    "CONCEPT_ANCESTOR.csv": [
        "ancestor_concept_id\tdescendant_concept_id\tmin_levels_of_separation\tmax_levels_of_separation",
        "1\t1\t0\t0",
    ],
}


@pytest.fixture
def athena_dir(tmp_path):
    for name, lines in ATHENA_FILES.items():
        (tmp_path / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


def test_release_is_read_from_the_none_row(athena_dir):
    assert load_athena.release(athena_dir) == "v5.0 TEST"


def test_missing_file_is_reported(athena_dir):
    (athena_dir / "CONCEPT_ANCESTOR.csv").unlink()
    with pytest.raises(FileNotFoundError, match="CONCEPT_ANCESTOR.csv"):
        load_athena.load(None, athena_dir)


@pytest.mark.db
def test_athena_load_keeps_quotes_and_skips_when_unchanged(db_conn, athena_dir):
    db.bootstrap(db_conn)
    first = load_athena.load(db_conn, athena_dir, force=True)  # test DB persists between runs
    assert first["skipped"] is False and first["rows"]["concept"] == 2
    name = db_conn.execute("SELECT concept_name FROM vocab.concept WHERE concept_id = 1").fetchone()
    assert name == ('5" gauze pad',)
    standard = db_conn.execute(
        "SELECT standard_concept FROM vocab.concept WHERE concept_id = 2"
    ).fetchone()
    assert standard == (None,)  # empty field -> NULL, not ''
    assert load_athena.load(db_conn, athena_dir)["skipped"] is True


def test_stub_rows_skip_unknown_systems_and_licensed_cdt():
    rows = stub.build_rows(
        [
            ("http://snomed.info/sct", "44054006", "Diabetes", "Condition"),
            ("http://loinc.org", "4548-4", "HbA1c", "Observation"),
            ("http://www.ada.org/cdt", "D0120", "Oral evaluation", "Procedure"),
            ("http://example.org/unknown", "x", "?", "Observation"),
        ]
    )
    local = [r for r in rows if r[0] >= stub.LOCAL_ID_START]
    assert [(r[3], r[5], r[2]) for r in local] == [
        ("SNOMED", "44054006", "Condition"),
        ("LOINC", "4548-4", "Measurement"),
    ]
    fixed_ids = {r[0] for r in rows}
    assert {32817, 32818, 32838, 8507, 8532} <= fixed_ids


@pytest.mark.db
def test_stub_load_builds_self_mapping_vocabulary(db_conn, tmp_path):
    db.bootstrap(db_conn)
    bundle = {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "p"}},
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "c",
                    "code": {
                        "coding": [
                            {"system": "http://snomed.info/sct", "code": "1", "display": "x"}
                        ]
                    },
                }
            },
        ],
    }
    (tmp_path / "b.json").write_text(json.dumps(bundle))
    fhir_loader.load(db_conn, tmp_path)
    stub.load(db_conn)
    row = db_conn.execute(
        """SELECT c.domain_id, r.concept_id_2 = c.concept_id
           FROM vocab.concept c JOIN vocab.concept_relationship r ON r.concept_id_1 = c.concept_id
           WHERE c.vocabulary_id = 'SNOMED' AND c.concept_code = '1'"""
    ).fetchone()
    assert row == ("Condition", True)
    version = db_conn.execute(
        "SELECT vocabulary_version FROM vocab.vocabulary WHERE vocabulary_id = 'None'"
    ).fetchone()[0]
    assert version.startswith("STUB")
