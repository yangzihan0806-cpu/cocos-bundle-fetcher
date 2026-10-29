import io
import json
import zipfile
from pathlib import Path
import uuid

import pytest

from cocos_fetch.archive import safe_extract_zip
from cocos_fetch.bundles import BundleManifest, find_configs, native_candidates, pair_dict
from cocos_fetch.settings_parser import parse_settings_js
from cocos_fetch.uuid_codec import decode_uuid, encode_uuid


def test_decode_known_vector():
    assert decode_uuid("fcmR3XADNLgJ1ByKhqcC5Z") == "fc991dd7-0033-4b80-9d41-c8a86a702e59"


def test_round_trip_random():
    for _ in range(1000):
        u = str(uuid.uuid4())
        c = encode_uuid(u)
        assert len(c) == 22
        assert decode_uuid(c) == u


@pytest.mark.parametrize("s", ["0a1b2c3d4", "fc991dd7-0033-4b80-9d41-c8a86a702e59", ""])
def test_non_compressed_passthrough(s):
    assert decode_uuid(s) == s


def test_parse_settings_js():
    text = '''window._CCSettings = {
        server: "https://cdn.example.com/game/",
        remoteBundles: ["main", "ui"],
        subpackages: [],
        bundleVers: { main: "a1b2c", ui: "d3e4f" },
    };'''
    s = parse_settings_js(text)
    assert s.server == "https://cdn.example.com/game"
    assert s.remote_bundles == ["main", "ui"]
    assert s.bundle_vers == {"main": "a1b2c", "ui": "d3e4f"}


def test_parse_settings_js_missing_field():
    with pytest.raises(ValueError):
        parse_settings_js("server: 'x'")


def test_pair_dict():
    assert pair_dict([0, "v0", "pack1", "v1"]) == {0: "v0", "pack1": "v1"}


def test_manifest_and_candidates(tmp_path: Path):
    u = "fc991dd7-0033-4b80-9d41-c8a86a702e59"
    cfg = {
        "name": "main",
        "uuids": [encode_uuid(u)],
        "paths": {"0": ["fonts/Title", 1]},
        "versions": {"import": [0, "v1", "0abcdef12", "v2"], "native": [0, "v3"]},
    }
    p = tmp_path / "main" / "config.x.json"
    p.parent.mkdir()
    p.write_text(json.dumps(cfg))

    m = BundleManifest.load(p)
    assert m.import_name(0) == u
    assert m.import_name("0abcdef12") == "0abcdef12"  # pack IDs are used verbatim
    assert m.native_entry(0) == (u, "fonts/Title")

    png = native_candidates(m, u, "v3", "fonts/Title", ".png")
    assert png[0] == Path("native/fc") / f"{u}.v3.png"
    ttf = native_candidates(m, u, "v3", "fonts/Title", ".ttf")
    assert ttf[0] == Path("native/fc") / f"{u}.v3" / "Title.ttf"

    assert find_configs(tmp_path) == [p]


def test_zip_slip_rejected(tmp_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.txt", "x")
    buf.seek(0)
    with pytest.raises(ValueError):
        safe_extract_zip(buf, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()
