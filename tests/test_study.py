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
        assert m["format"] == st.FORMAT_NAME and m["version"] == 1, "the lowest format that holds what it has"


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


# ---------------------------------------------------------------- links, the one thing format 2 added
def _version_of(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return json.loads(z.read("manifest.json"))["version"]


def _edit_member(data, member, change):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as z, zipfile.ZipFile(out, "w") as w:
        for name in z.namelist():
            raw = z.read(name)
            if name == member:
                doc = json.loads(raw)
                change(doc)
                raw = json.dumps(doc)
            w.writestr(name, raw)
    return out.getvalue()


def _study_with(links=None):
    return st.Study(source_name="x.schematix", source_sha256=st.sha256(b"abc"), source_bytes=b"abc", links=links or {})


def test_a_study_without_links_stays_in_the_old_format():
    assert _version_of(st.to_bytes(_study_with())) == 1


def test_a_study_with_links_says_so_and_keeps_them():
    data = st.to_bytes(_study_with({"u/1": {"Senses": "A1 100%"}, "u/2": {"Solenoid a": ""}}))
    assert _version_of(data) == 2
    assert st.from_bytes(data).links == {"u/1": {"Senses": "A1 100%"}, "u/2": {"Solenoid a": ""}}


def test_a_format_1_study_opens_with_no_links():
    data = st.to_bytes(_study_with())
    assert st.from_bytes(data).links == {}


def test_a_newer_format_is_refused_with_a_message():
    data = _edit_member(st.to_bytes(_study_with()), "manifest.json", lambda m: m.update(version=99))
    with pytest.raises(st.StudyError, match="newer"):
        st.from_bytes(data)


@pytest.mark.parametrize("bad", [None, 5, "x", [], {"u/1": 5}, {"u/1": {"Nonsense": "x"}}, {"u/1": {"Senses": 7}}, {5: {"Senses": "x"}}])
def test_damaged_links_are_dropped_and_the_study_still_opens(bad):
    data = _edit_member(st.to_bytes(_study_with()), "st.json", lambda d: d.update(links=bad))
    assert st.from_bytes(data).links == {}


def test_links_are_limited_in_length(tmp_path):
    s = _study_with({"u/1": {"Senses": "x" * 5000}})
    p = str(tmp_path / "a.fluidworx")
    st.save(s, p)
    assert len(st.load(p).links["u/1"]["Senses"]) == st.MAX_LINK_TEXT
