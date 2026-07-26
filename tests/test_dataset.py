"""Tests for exptrack/core/dataset.py — dataset detection + manifest capture.

(Imported here via the ``exptrack.capture.dataset`` back-compat shim.)"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# _looks_like_dataset
# ---------------------------------------------------------------------------

def test_looks_like_dataset_existing_data_file(tmp_path):
    from exptrack.capture.dataset import _looks_like_dataset

    csv = tmp_path / "train.csv"
    csv.write_text("a,b\n1,2\n")
    assert _looks_like_dataset("anything", str(csv)) is True

    pq = tmp_path / "data.parquet"
    pq.write_bytes(b"PAR1")
    assert _looks_like_dataset("anything", str(pq)) is True


def test_looks_like_dataset_nonexistent_path(tmp_path):
    from exptrack.capture.dataset import _looks_like_dataset

    assert _looks_like_dataset("data", str(tmp_path / "nope.csv")) is False


def test_looks_like_dataset_non_data_scalar():
    from exptrack.capture.dataset import _looks_like_dataset

    # Non-string scalar values are never datasets.
    assert _looks_like_dataset("lr", 0.01) is False
    assert _looks_like_dataset("epochs", 10) is False


def test_looks_like_dataset_key_regex_on_existing_dir(tmp_path):
    from exptrack.capture.dataset import _looks_like_dataset

    d = tmp_path / "imgs"
    d.mkdir()
    # data_dir-shaped key pointing at an existing dir → True even with no ext.
    assert _looks_like_dataset("data_dir", str(d)) is True
    # A non-dataset key at the same dir → False (no data extension on a dir).
    assert _looks_like_dataset("output_folder", str(d)) is False


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

def test_build_manifest_selects_only_data_entries(tmp_path):
    from exptrack.capture.dataset import build_manifest

    csv = tmp_path / "train.csv"
    csv.write_text("a,b\n1,2\n3,4\n")
    ddir = tmp_path / "data_dir"
    ddir.mkdir()
    (ddir / "f1.bin").write_bytes(b"abc")
    (ddir / "f2.bin").write_bytes(b"defg")

    params = {
        "train_file": str(csv),
        "data_dir": str(ddir),
        "lr": 0.01,                       # non-data scalar
        "out": str(tmp_path / "out"),     # non-existent path, non-data key
        "_internal": str(csv),            # underscore key — excluded
    }

    manifest = build_manifest(params)

    assert set(manifest) == {"train_file", "data_dir"}

    file_entry = manifest["train_file"]
    assert file_entry["kind"] == "file"
    assert file_entry.get("hash")

    dir_entry = manifest["data_dir"]
    assert dir_entry["kind"] == "dir"
    assert dir_entry["n_files"] == 2


def test_build_manifest_excludes_underscore_keys(tmp_path):
    from exptrack.capture.dataset import build_manifest

    csv = tmp_path / "d.csv"
    csv.write_text("x\n1\n")
    assert build_manifest({"_dataset_manifest": str(csv)}) == {}


# ---------------------------------------------------------------------------
# directory fingerprint stability
# ---------------------------------------------------------------------------

def test_dir_fingerprint_stable_and_changes(tmp_path):
    from exptrack.capture.dataset import _dir_manifest

    d = tmp_path / "ds"
    d.mkdir()
    (d / "a.bin").write_bytes(b"aaa")

    m1 = _dir_manifest(d)
    m2 = _dir_manifest(d)
    assert m1["hash"] == m2["hash"]  # stable across calls

    # Adding a file changes the fingerprint.
    (d / "b.bin").write_bytes(b"bbb")
    m3 = _dir_manifest(d)
    assert m3["hash"] != m1["hash"]
    assert m3["n_files"] == 2

    # Resizing an existing file also changes the fingerprint.
    (d / "a.bin").write_bytes(b"aaaaaaaaaa")
    m4 = _dir_manifest(d)
    assert m4["hash"] != m3["hash"]


# ---------------------------------------------------------------------------
# capture_dataset_manifest
# ---------------------------------------------------------------------------

class _StubExp:
    """Minimal Experiment-like object: _params dict + log_params recorder."""

    def __init__(self, params):
        self._params = dict(params)

    def log_params(self, d):
        self._params.update(d)


def test_capture_dataset_manifest_logs_manifest(tmp_path):
    from exptrack.capture.dataset import build_manifest, capture_dataset_manifest

    csv = tmp_path / "train.csv"
    csv.write_text("a,b\n1,2\n")

    exp = _StubExp({"train_file": str(csv), "lr": 0.01})
    returned = capture_dataset_manifest(exp)

    expected = build_manifest({"train_file": str(csv), "lr": 0.01})
    assert returned == expected
    assert exp._params["_dataset_manifest"] == expected
    assert "train_file" in exp._params["_dataset_manifest"]


def test_capture_dataset_manifest_no_data_logs_nothing(tmp_path):
    from exptrack.capture.dataset import capture_dataset_manifest

    exp = _StubExp({"lr": 0.01, "epochs": 5})
    returned = capture_dataset_manifest(exp)
    assert returned == {}
    assert "_dataset_manifest" not in exp._params


def test_experiment_finish_captures_dataset_manifest(tmp_project):
    """A real Experiment.finish() fingerprints dataset-shaped params (the
    universal-exit-point wiring, not just `exptrack run`)."""
    from exptrack.core import Experiment, get_db

    csv = tmp_project / "train.csv"
    csv.write_text("a,b\n1,2\n3,4\n")

    exp = Experiment(script="train.py", params={"train_file": str(csv), "lr": 0.01})
    exp.finish()

    conn = get_db()
    row = conn.execute(
        "SELECT value FROM params WHERE exp_id=? AND key='_dataset_manifest'",
        (exp.id,),
    ).fetchone()
    assert row is not None
    import json
    manifest = json.loads(row["value"])
    assert "train_file" in manifest and manifest["train_file"]["kind"] == "file"
