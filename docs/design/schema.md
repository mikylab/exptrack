# Database schema in detail

Column-level detail and the reasoning behind each nullable/added column. `CLAUDE.md` carries the table list; this is what it points at.

## Tables

SQLite WAL mode with 10 tables:

- **`experiments`** — run metadata (id, name, status, created_at, duration_s, git_branch, git_commit, git_diff, hostname, python_ver, notes, tags, output_dir, **command** — the real launch command (`run-start`/`run-finish --cmd`; see the **Run-vs-run loop** pattern), **session_node_id** — nullable FK into `session_nodes` set only by `%exptrack promote`, **deleted_at** — nullable ISO timestamp; non-null = soft-deleted/Trash. Indexed on `deleted_at`, **name_is_auto** — `INTEGER DEFAULT 0`; 1 means the run still carries its generated name. Set on insert from `not bool(name)`, cleared by `POST /api/experiment/<id>/rename`, preserved by internal auto-renames (`Experiment._rename`). Backfilled idempotently in `_ensure_schema()` via `looks_auto_named` so pre-1.11 runs flag too)
- **`params`** — key/value pairs (exp_id, key, value as JSON string, source). Source is 'auto' (captured from script/argparse) or 'manual' (added via dashboard or `api_create_experiment`). Auto params are read-only in the UI; manual params can be edited, renamed, and deleted via dashboard inline editing
- **`metrics`** — float values (exp_id, key, value, step, ts, source, **session_node_id**). Source is 'auto' (from scripts), 'manual' (dashboard), or 'pipeline' (CLI). `session_node_id` is a nullable tag naming the Session Trees node that was active when the metric was written (`experiment._active_session_node()`, NULL outside a session), indexed via `idx_metrics_session_node` — see the **Per-branch metric attribution** pattern
- **`artifacts`** — output files (exp_id, label, path, content_hash, size_bytes, timeline_seq, created_at)
- **`timeline`** — execution events (exp_id, seq, event_type, cell_hash, cell_pos, key, value, prev_value, source_diff, ts)
- **`cell_lineage`** — content-addressed cell history (cell_hash, notebook, source, parent_hash, created_at)
- **`code_baselines`** — position-based cell baselines (notebook, cell_seq, source, source_hash)
- **`code_snapshots`** — content-addressed full script/shell-script source (hash PK, content, kind, path, size_bytes, created_at). Written at run time by `capture_script_snapshot` (deduped by content hash, `.ipynb` never stored, size-capped by `snapshot_max_kb`) and referenced from the `_code_snapshot` param, so a run stays re-runnable after the file is edited. See the **Run-vs-run loop** pattern
- **`sessions`** — Session Trees container (id, name, notebook, status `'active'|'ended'`, git_branch, git_commit, created_at, ended_at, **deleted_at** — nullable unix timestamp; non-null = soft-deleted/Trash, indexed via `idx_sessions_deleted`). Created only by `%exptrack session start`. Soft-deletable + restorable (mirrors experiments/nodes). A trashed session is hidden from `list_sessions`/`find_session` but **still loadable** by `build_tree`, which surfaces it as `session.deleted` — see the **A trashed thing that's still reachable must say it's trashed** pattern
- **`session_nodes`** — tree nodes (id, session_id, parent_id, node_type `'root'|'checkpoint'|'branch'|'abandoned'`, label, note, cell_source, **cell_outputs** — SEP-joined per-cell output blob aligned 1:1 with `cell_source` (trailing-expression `repr` per recorded cell; `%load_ext exptrack` captures it and `record_cell(source, output)` keeps the two blobs segment-aligned through dedup/elision), **setup_source** / **setup_outputs** — nullable SEP-joined blobs holding `%%setup` prep cells (recorded-but-secondary; own `_NODE_SETUP_MAX_BYTES` budget so they never evict real cells, written by `record_setup_cell()`), **images** — nullable JSON list of `{path, label, ts}` for plots saved by reference (no copy) while the node was active, deduped by path and capped at 30 via `record_image()`, git_diff, git_commit, seq, created_at, **deleted_at** — nullable unix timestamp; non-null = soft-deleted/Trash). Indexed on (session_id, seq), (parent_id), and (session_id, deleted_at)

Indexed on: metrics(exp_id, key), params(exp_id), artifacts(exp_id), timeline(exp_id, seq), experiments(created_at, status).

## Migration and the version stamp

`_SCHEMA_VERSION` (currently **6**) is written to `PRAGMA user_version` once a
migration pass completes, and `get_db()` skips `_ensure_schema` entirely on an
already-stamped database. That makes the stamp the load-bearing part: a database
stamped current with columns still missing is permanently broken, because no
later connection ever retries.

Three rules, each of which exists because it was broken once:

1. **Every column belongs to a `_migrate_*` helper**, never to
   `_create_base_schema` alone. `CREATE TABLE IF NOT EXISTS` does nothing for a
   table that already exists, so the six pre-1.0 columns (`command`, `hostname`,
   `python_ver`, `duration_s`, `notes`, `tags`) were never added to a database
   created before them — and every run then died on `no column named command`.
2. **A backfill must not be gated on "the ALTER ran this pass."** That is how the
   stamp was written with columns absent: pass 1 added `params.source`, then its
   backfill failed because `experiments.hostname` did not exist, so nothing was
   stamped; pass 2 skipped the already-done ALTER, never ran the backfill, saw
   every helper "succeed" and stamped. Backfills are idempotent and run on every
   migration pass (which only happens while the stamp is behind, so it is free).
3. **The stamp is verified, not trusted.** `_missing_columns` checks the full
   `_REQUIRED_COLUMNS` set after the helpers run; anything missing withholds the
   stamp and prints what is absent, so the next connection tries again.

`tests/test_db.py` fingerprints the schema DDL, so any change to it fails until
both the fingerprint and `_SCHEMA_VERSION` are updated deliberately.
