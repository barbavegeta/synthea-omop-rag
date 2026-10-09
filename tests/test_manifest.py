import json

from rwe.config import load_config
from rwe.manifest import build_manifest, git_state, write_manifest


def test_manifest_records_seeds_and_config():
    cfg = load_config("ci")
    m = build_manifest(cfg, extra={"note": "x"})
    assert m["seeds"] == {"global": cfg.seed, "synthea": 42, "synthea_clinician": 42}
    assert m["config_fingerprint"] == cfg.fingerprint()
    assert m["config"]["synthea"]["population"] == 20
    assert m["note"] == "x"


def test_manifest_round_trips_as_json(tmp_path):
    path = write_manifest(build_manifest(load_config("default")), runs_dir=tmp_path)
    assert json.loads(path.read_text())["config_profile"] == "default"


def test_git_state_outside_a_repo(tmp_path):
    assert git_state(tmp_path) == {"sha": None, "dirty": None}
