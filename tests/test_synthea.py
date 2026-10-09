import gzip

import pytest

from rwe.config import load_config
from rwe.synthea import run as synthea


@pytest.fixture
def cfg():
    return load_config("default").synthea


def test_args_pin_every_source_of_variation(cfg, tmp_path):
    args = synthea.synthea_args(cfg, tmp_path)
    flags = dict(zip(args[:-1:2], args[1:-1:2], strict=False))
    assert flags["-p"] == "1000"
    assert flags["-s"] == "42" and flags["-cs"] == "42"
    assert flags["-r"] == "20251231" and flags["-e"] == "20251231"
    assert args[-1] == "Massachusetts"
    assert f"--exporter.baseDirectory={tmp_path}/" in args


def test_generation_key_tracks_inputs_but_not_the_generate_flag(cfg):
    key = synthea.generation_key(cfg)
    assert synthea.generation_key(cfg.model_copy(update={"population": 5})) != key
    assert synthea.generation_key(cfg.model_copy(update={"generate": False})) == key


def test_wrong_checksum_is_refused(cfg, tmp_path):
    (tmp_path / f"synthea-{cfg.version}.jar").write_bytes(b"not the real jar")
    with pytest.raises(RuntimeError, match="does not match pinned"):
        synthea.ensure_jar(cfg, bin_dir=tmp_path)


def test_generate_refuses_to_write_outside_data_dir(cfg, tmp_path):
    with pytest.raises(ValueError, match="Refusing"):
        synthea.generate(cfg, tmp_path)


def test_fixture_gzip_is_byte_reproducible(tmp_path):
    src = tmp_path / "fhir"
    src.mkdir()
    (src / "p.json").write_text('{"resourceType": "Bundle"}')
    first = synthea.write_fixture(src, tmp_path / "fx")[0].read_bytes()
    second = synthea.write_fixture(src, tmp_path / "fx")[0].read_bytes()
    assert first == second
    assert gzip.decompress(first) == b'{"resourceType": "Bundle"}'
