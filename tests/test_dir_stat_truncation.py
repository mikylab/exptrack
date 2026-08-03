"""The directory-sizing walk is capped, and every surface says so.

``dir_file_stats`` used to walk an output tree with an unbounded ``rglob`` and
one ``stat`` per file. A checkpoint-per-epoch run is tens of thousands of
files, and a bulk delete previews *every* run in the batch, so a confirm
dialog could hold a request thread for seconds on a network filesystem.

Capping it is easy; capping it *honestly* is the point. A confirm that says
"4 files, 12 KB" for a directory holding 40,000 files is worse than the slow
version — it under-states what the delete is about to remove and gives no hint
that it did. So the cap is carried as a `truncated` flag through the preview
payload to both delete dialogs and the orphan-cleanup confirm, which render
the affected figures as "≥ N".
"""
from __future__ import annotations


def _make_tree(root, n):
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        (root / f"f{i}.bin").write_bytes(b"x")


def test_walk_stops_at_the_cap_and_reports_it(tmp_path):
    from exptrack.core.db import dir_file_stats

    _make_tree(tmp_path / "big", 12)
    files, size, truncated = dir_file_stats(tmp_path / "big", max_files=5)
    assert truncated is True
    assert files == 5                       # stopped, did not walk all 12
    assert size == 5                        # a lower bound, still true


def test_an_uncapped_walk_is_not_flagged(tmp_path):
    from exptrack.core.db import dir_file_stats

    _make_tree(tmp_path / "small", 3)
    files, size, truncated = dir_file_stats(tmp_path / "small", max_files=100)
    assert (files, size, truncated) == (3, 3, False)


def test_delete_preview_carries_the_flag_and_the_cap(tmp_project, db_conn):
    """Both halves matter: the flag makes the dialog say "≥", and the cap
    lets it name the number it stopped at instead of "the walk limit"."""
    import exptrack.core.db as dbmod
    from exptrack.core.db import get_db, get_delete_preview
    from exptrack.core.experiment import Experiment

    exp = Experiment(name="capped", script="train.py")
    out = tmp_project / "outputs" / "capped"
    _make_tree(out, 9)
    conn = get_db()
    conn.execute("UPDATE experiments SET output_dir=? WHERE id=?",
                 (str(out), exp.id))
    conn.commit()

    orig = dbmod.DIR_STAT_MAX_FILES
    dbmod.DIR_STAT_MAX_FILES = 4
    try:
        p = get_delete_preview(conn, exp.id)
    finally:
        dbmod.DIR_STAT_MAX_FILES = orig

    assert p["output_dir_truncated"] is True
    assert p["output_dir_files"] == 4
    assert p["dir_stat_max_files"] == 4

    # Uncapped: no flag, and the real total.
    p2 = get_delete_preview(conn, exp.id)
    assert p2["output_dir_truncated"] is False
    assert p2["output_dir_files"] == 9


def test_bulk_preview_totals_are_flagged_when_any_run_was_capped(
        tmp_project, db_conn):
    """A total summed from partial figures is partial. The batch dialog has
    to say "≥" if *any* run in it hit the cap, not only if all of them did."""
    import exptrack.core.db as dbmod
    from exptrack.core.db import get_db
    from exptrack.core.experiment import Experiment
    from exptrack.dashboard.routes.write_routes import api_bulk_delete_preview

    small = Experiment(name="small", script="a.py")
    big = Experiment(name="big", script="b.py")
    conn = get_db()
    for exp, n in ((small, 2), (big, 9)):
        out = tmp_project / "outputs" / exp.name
        _make_tree(out, n)
        conn.execute("UPDATE experiments SET output_dir=? WHERE id=?",
                     (str(out), exp.id))
    conn.commit()

    orig = dbmod.DIR_STAT_MAX_FILES
    dbmod.DIR_STAT_MAX_FILES = 4
    try:
        r = api_bulk_delete_preview(conn, {"ids": [small.id, big.id]})
    finally:
        dbmod.DIR_STAT_MAX_FILES = orig

    t = r["totals"]
    assert t["dir_sizes_truncated"] is True
    assert t["dir_stat_max_files"] == 4
    assert t["output_dir_files"] == 6           # 2 whole + 4 of big's 9


def test_owned_output_dirs_are_deduped(tmp_project, db_conn):
    """A run's recorded output_dir is normally *the same path* as the
    name-derived outputs/<name>. Both are candidates, so without a dedup the
    preview sized the directory twice and the confirm reported double the
    files and bytes — while the delete trashed it once."""
    from exptrack.core.db import get_db, get_delete_preview, output_dirs_owned_by
    from exptrack.core.experiment import Experiment

    exp = Experiment(name="dup", script="train.py")
    out = tmp_project / "outputs" / "dup"
    _make_tree(out, 5)
    conn = get_db()
    conn.execute("UPDATE experiments SET output_dir=? WHERE id=?",
                 (str(out), exp.id))
    conn.commit()

    assert len(output_dirs_owned_by(conn, exp.id, "dup", str(out))) == 1
    assert get_delete_preview(conn, exp.id)["output_dir_files"] == 5


def test_orphan_description_carries_the_flag(tmp_project, db_conn):
    import exptrack.core.db as dbmod
    from exptrack.core.db import describe_orphan_output_paths, get_db

    _make_tree(tmp_project / "outputs" / "nobodys", 9)
    conn = get_db()

    orig = dbmod.DIR_STAT_MAX_FILES
    dbmod.DIR_STAT_MAX_FILES = 4
    try:
        rows = describe_orphan_output_paths(conn)
    finally:
        dbmod.DIR_STAT_MAX_FILES = orig

    assert rows and rows[0]["truncated"] is True
    assert rows[0]["files"] == 4
