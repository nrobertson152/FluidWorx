import io
import json
import os
import zipfile

import pytest

from fluidworx import study as st


@pytest.fixture
def example(examples_dir):
    return os.path.join(examples_dir, "lift_cylinder.schematix")


def test_round_trip(tmp_path, example):
    s = st.from_source(example)
    s.params = {"abc/1": {"setting": 123e5}}
    s.notes = "n"
    s.units = "us"
    s.source_rev = {"summary": "D1 Rev A"}
    p = tmp_path / "a.fluidworx"
    st.save(s, str(p))
    r = st.load(str(p))
    assert r.params == s.params and r.notes == "n" and r.units == "us"
    assert r.source_bytes == s.source_bytes and r.source_sha256 == s.source_sha256
    assert r.source_name == "lift_cylinder.schematix" and r.source_rev == {"summary": "D1 Rev A"}


def test_format_matches_the_family(tmp_path, example):
    p = tmp_path / "a.fluidworx"
    st.save(st.from_source(example), str(p))
    with zipfile.ZipFile(p) as z:
        info = z.infolist()[0]
        assert info.filename == "mimetype" and info.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype").decode() == st.MIMETYPE
        m = json.loads(z.read("manifest.json"))
        assert m["format"] == st.FORMAT_NAME and m["version"] == st.FORMAT_VERSION


def test_failed_save_leaves_the_old_file(tmp_path, example, monkeypatch):
    p = tmp_path / "a.fluidworx"
    s = st.from_source(example)
    st.save(s, str(p))
    before = p.read_bytes()

    def boom(*a):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    s.notes = "changed"
    with pytest.raises(OSError):
        st.save(s, str(p))
    monkeypatch.undo()
    assert p.read_bytes() == before
    assert [x.name for x in tmp_path.iterdir()] == ["a.fluidworx"], "temporary file left behind"


def _rewrite(data, **changes):
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in src.namelist():
            z.writestr(n, changes.get(n.replace("/", "_").replace(".", "_"), src.read(n)))
    return buf.getvalue()


def test_newer_version_refused_with_a_clear_message(example):
    data = st.to_bytes(st.from_source(example))
    m = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
    m["version"] = 99
    with pytest.raises(st.StudyError, match="newer"):
        st.from_bytes(_rewrite(data, manifest_json=json.dumps(m)))


def test_changed_schematic_copy_is_detected(example):
    data = st.to_bytes(st.from_source(example))
    with pytest.raises(st.StudyError, match="checksum"):
        st.from_bytes(_rewrite(data, source_schematic_schematix=b"tampered"))


@pytest.mark.parametrize("bad", [b"", b"not a zip", b"PK\x03\x04garbage"])
def test_junk_is_refused(bad):
    with pytest.raises(st.StudyError):
        st.from_bytes(bad)


def test_non_finite_and_wrongly_typed_values_are_refused_or_dropped(example):
    data = st.to_bytes(st.from_source(example))
    doc = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("study.json"))
    with pytest.raises(st.StudyError):
        st.from_bytes(_rewrite(data, study_json=json.dumps(doc).replace('"params": {}', '"params": {"a/1": {"x": NaN}}')))
    doc["params"] = {"a/1": {"good": 1.0, "text": "no", "flag": True}, "b/2": "nope"}
    assert st.from_bytes(_rewrite(data, study_json=json.dumps(doc))).params == {"a/1": {"good": 1.0}}


def test_source_change_detection(tmp_path, example):
    f = tmp_path / "c.schematix"
    f.write_bytes(open(example, "rb").read())
    s = st.from_source(str(f))
    assert st.source_changed(s) is False
    f.write_bytes(f.read_bytes() + b"x")
    assert st.source_changed(s) is True
    f.unlink()
    assert st.source_changed(s) is None
