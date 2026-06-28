# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.35.0] - 2026-06-22

### Fixed
- **Failed runs now capture the traceback (file + line), not just the error message** — when a script wrapped by `exptrack run` / `python -m exptrack` crashed, only the one-line exception message was stored (as an `error` param) and the full traceback was lost: it was printed to stderr *after* `stderr.log` had already been closed, so the log was blank and the dashboard showed nothing useful. The crash handler now prints the traceback *before* restoring streams (so it tees into `stderr.log`) and passes the full formatted traceback to `Experiment.fail(error, traceback=…)`, which stores it as the `_error_traceback` param. The experiment detail view shows it in a prominent **Run failed** panel (with a Copy button) on failed runs.
- **`sys.exit(1)` failures no longer swallow the real error** — when a script (or a framework/library it uses) caught an exception and called `sys.exit(1)`, exptrack recorded only `SystemExit(1)` and the actual cause never appeared in the terminal, in `stderr.log`, or in the dashboard. The `SystemExit` handler now surfaces the chained cause (`SystemExit.__context__`): it prints that traceback to the terminal **and** `stderr.log` and captures it on the run, so you can see what actually failed and on which line. A deliberate bare `sys.exit(code)` with no underlying error still just records the exit code (no invented traceback).
- **`with Experiment(...)` blocks capture the traceback too** — the context-manager failure path (`__exit__`) now records the full traceback (file + line), matching the `exptrack run` wrapper, so programmatic runs get the same **Run failed** panel instead of just the bare message.
- **`I/O operation on closed file` tee warning** — the `_TeeWriter` that mirrors stdout/stderr into the log files now no-ops on writes/flushes after the log is closed (interpreter shutdown, or a library holding a stale stream reference) instead of printing `[exptrack] warning: could not tee flush log: I/O operation on closed file.`.

## [1.34.0] - 2026-06-15

### Added
- **Materialized runs carry their own metrics** — a notebook session logs every `metric()` into one auto-started run, so a graduated branch used to have the code but not its accuracy/loss. Materializing a node now also copies the live run's metrics that were logged **while that node's cells ran** (attributed by timestamp window: `[node.created_at, next node's created_at)`), so each finalized branch experiment is self-contained for comparison — the 0.7 branch gets the 0.7 accuracy, the 0.5 branch gets the 0.5 accuracy. Best-effort and source-preserving.

## [1.33.1] - 2026-06-15

### Fixed
- **Materialized / finalized runs now carry their setup code** — promoting a session node to an experiment (the Finalize action, the dashboard `＋ Promote to experiment`, or `materialize_experiment`) now replays the node's **whole ancestor chain** of cells (session root → upstream checkpoints → the node), not just the node's own fragment. A branch like `run_pipeline(data, threshold)` is meaningless without the upstream cell that defined `run_pipeline`/`data`; folding the ancestor setup code in makes each graduated experiment self-contained and re-runnable instead of "output but no code." The Finalize modal explains this, and a code-less checkpoint is labelled a *marker* (its branches carry the code) rather than implying it can be saved on its own.

## [1.33.0] - 2026-06-15

### Added
- **Finalize a session** — a new `✓ Finalize` button on the session view (and `exptrack session finalize <id>`) graduates a session into self-contained, grouped experiments: it materializes the un-promoted nodes you select into standalone runs (full code, `%%setup`, plots), groups every run from the session under a study named after the session, then moves the session to the Trash. The dashboard modal shows which nodes are already promoted vs. un-promoted and lets you pick which to materialize; the CLI prints the same plan and prompts unless `-y`. So once you've finished exploring, you know exactly what to re-run and can safely delete the session.
- **Sessions are now grouped by a study** — whenever a run is linked to a session (auto-linked notebook runs, `%exptrack promote`, dashboard promote/link, or materialize) it is added to a study named after the session. The grouping persists even after the session is deleted, so a session's runs stay together in the sidebar/table grouping.
- **Sessions are recoverable (Trash)** — deleting a session now moves it to the Trash by default instead of permanently erasing it. A new **Sessions** section in the unified Trash (Settings → 🗑 Open Trash) lists trashed sessions with **Restore** and **Delete forever**. CLI: `exptrack session rm` soft-deletes (use `--permanent` to purge), plus `exptrack session restore <id>` and `exptrack session purge <id>`. Schema: new nullable `sessions.deleted_at` column (idempotent migration; `exptrack upgrade`-safe).

### Changed
- **`delete_session` is now soft by default** — `delete_session(session_id)` sets `deleted_at` (recoverable) and leaves nodes + linked experiments untouched; pass `permanent=True` (or use the Trash's Delete forever) to hard-delete. Live listings (`list_sessions`, `find_session`, the dashboard sessions list) filter out trashed sessions.

## [1.32.1] - 2026-06-14

### Fixed
- **Settings UI** - fixed settings box, where vacuum and delete db were cut off. Settings now scrollable.

## [1.32.0] - 2026-06-14

### Added

- **Dataset / input versioning** — a run isn't reproducible if you don't know *what data* trained it, so exptrack now fingerprints dataset paths passed as params and records them as a `_dataset_manifest` param when a run finishes (wired into `Experiment.finish()`, so scripts, notebooks, and programmatic runs are all covered). Detection is zero-friction (it piggybacks on the params already captured by the argparse/argv patches): any value that is an existing data file (`.csv`/`.parquet`/`.npy`/`.h5`/…) or a dataset-shaped key (`--data_dir`, `--train`, …) pointing at an existing path is fingerprinted — files via a partial content hash, directories via their `(relpath, size)` listing (no byte reads, so huge datasets stay fast). The dashboard surfaces it as a **Datasets** section in the experiment detail (path · size · fingerprint), so a changed hash makes "the data changed between runs" visible. New module `exptrack/capture/dataset.py` (`build_manifest`, `capture_dataset_manifest`); never raises (a capture failure can't crash your run).
- **Chart PNG export** — the Charts tab has a **⬇ PNG** button that downloads the visible chart(s) as PNG (composited onto a theme-matched background so the export isn't transparent); in "Show All" mode it downloads one PNG per metric.
- **Dashboard loading, empty, and error states** — the experiment detail panel now shows a shimmer **skeleton** while its three API calls are in flight (first entry only, so in-place refreshes don't flicker) and a friendly **error card with Retry / Back** if a fetch fails or the run is gone (previously a failed load silently left stale content). The experiment table renders a real **empty state** — distinguishing "no experiments yet" (with a getting-started hint) from "no matches" (with a **Clear filters** button) instead of a blank table.

### Changed

- **Compare view metric deltas** — pair-compare metric deltas now include a **% change** alongside the absolute delta, and the multi-compare table highlights the **highest (green) / lowest (red)** value per metric row so the spread across runs is scannable at a glance.

### Internal

- **`refreshDetail` slimmed** — the dashboard's ~400-line detail builder now delegates its Code Changes / Variables / Datasets blocks (and loading/error states) to small named helpers, and a pre-existing dead `summaryHtml` block was removed.
- **Tests** — added `tests/test_hashing.py`, `tests/test_git.py`, `tests/test_gpu.py`, and `tests/test_dataset.py` covering previously-untested modules (file hashing incl. partial, git capture incl. outside-a-repo and exclude patterns, GPU info / `nvidia-smi` absence, and the new dataset manifest), plus query-layer tests for the batched list helpers and the `datasets` detail key.

## [1.31.1] - 2026-06-14

### Changed

- **Experiment list no longer does N+1 queries** — `list_experiments` (the dashboard's hottest path) previously issued three queries *per* experiment (latest metrics, sparklines, params), so a 50-run list fired 150+ queries. It now batch-loads all three in three queries total via `get_latest_metrics_with_source_batch` / `get_metrics_sparkline_batch` / `get_params_batch`, so the list scales with one round-trip per data kind instead of per row. Malformed param JSON now degrades to the raw string instead of crashing the whole listing.
- **`cmd_stale` commits once per batch** — marking timed-out runs previously opened a transaction (and fsync) per experiment; it now wraps the whole batch in a single transaction.
- **Unified-trash counts batched** — the Trash view's per-experiment metric/artifact counts are now one grouped `COUNT` each instead of two queries per trashed run.

### Removed

- **Duplicated orphan-sweep logic** — `_sweep_orphans` (internal) and `sweep_orphans` (public) were near-identical; both now delegate to one `_sweep_orphans_counts` helper driven by an `_ORPHAN_SPECS` table, so future schema changes touch one place.

## [1.31.0] - 2026-06-14

### Added

- **`EXPTRACK_DEBUG` diagnostics for silent capture failures** — exptrack runs inside your training process and deliberately swallows capture errors so a hiccup never crashes a run, but that historically left failures invisible. Set `EXPTRACK_DEBUG=1` (or `true`/`on`) to surface those swallowed exceptions on stderr (tagged `[exptrack:debug]`), so when a variable, diff, or DB reconnect silently fails you can actually see why. The flag is read fresh each time, so you can toggle it mid-notebook-session without restarting the kernel.
- **`core/utils.py` shared safety helpers** — `debug_enabled()` / `debug_log()` (the `EXPTRACK_DEBUG` gate) and `safe_call(fn, …, default=…, context=…)`, a one-liner for the `try/except: <fallback>` idiom that recurs across the capture and db layers. The stale-DB-connection reconnect path in `core/db.py:get_db()` now reports via `debug_log` instead of swallowing the error entirely.
- **`max_assignment_expr_len` config key** (default `500`) — the cap on how many characters of an assignment right-hand side are kept in a variable's timeline/`_var/` display before falling back to a bare `Type()` form. Previously hardcoded in two places; lower it if long inline literals bloat your timeline.

### Changed

- **Capture diagnostics unified on `debug_log` / `safe_call`** — the per-cell and per-savefig warning prints scattered across `cell_lineage.py`, `notebook_hooks.py`, `matplotlib_patch.py`, `script_tracking.py`, `session_hooks.py`, and `core/git.py` previously wrote to stderr unconditionally, so a recoverable capture hiccup could spam the notebook on every cell. They now route through `debug_log` (silent unless `EXPTRACK_DEBUG` is set), and `variables.var_summary` builds its summaries through `safe_call` — so capture failures are quiet by default but fully visible, with a `context` label, when you turn the debug flag on.
- **Atomic `run-finish`** — `exptrack run-finish` now gathers metrics, extra params, and newly-discovered artifacts via reads first, then writes them together with the `status='done'` / duration update in a **single transaction**. Previously each piece committed separately, so a crash mid-finish could leave a run with metrics logged but status still `running` (or artifacts registered against an unfinished run). Now a finish either fully lands or not at all.
- **Tag / note writes honor `batched_writes()`** — `Experiment.add_tag`/`remove_tag`/`set_note`/`add_note` now defer their commit inside a `batched_writes()` block (matching `log_params`/`log_event`) instead of always committing immediately, so a burst of metadata edits collapses into one fsync.
- **`_ensure_schema()` split into focused, individually-testable migration helpers** — the ~270-line schema function is now an orchestrator that calls `_create_base_schema()` plus one `_migrate_*` helper per table (`_migrate_session_nodes`, `_migrate_artifacts`, `_migrate_metrics`, `_migrate_params`, `_migrate_experiments`, `_migrate_experiment_session_link`). Behavior is identical — each helper still checks column existence before `ALTER`, so the whole thing stays idempotent — but migrations are now readable and unit-tested for idempotency.
- **Giant capture/CLI functions split into focused, unit-tested helpers** — `cmd_run_start` is now an orchestrator over `_parse_freeform_params` / `_collect_env_context` / `_resolve_run_start_experiment` / `_apply_study_stage` / `_emit_run_env`, and the notebook `_post_run_cell` hook over `_handle_scratch_or_setup` / `_record_cell_on_session` / `_process_tracked_cell`. Behavior is unchanged; the pieces are now small enough to read and have direct unit tests (param parsing, SLURM context, study/stage inheritance, env emission, finish-row gathering, scratch-cell gating).
- **Generalized column migrations via `_add_columns(conn, table, {col: ddl})`** — every `_migrate_*` helper now declares its columns as a `{name: ddl}` map and calls the shared `_add_columns` primitive (built on `_table_columns`), which adds only the absent ones and returns the set it actually added. One-time backfills (e.g. `name_is_auto`, `params.source`) and index creation are gated on that return set, so the repetitive per-column `PRAGMA`/`if not in cols`/`ALTER` boilerplate is gone and an already-migrated DB is a provable no-op (now unit-tested).

## [1.30.0] - 2026-06-13

### Changed

- **Unified Trash — one place for trashed experiments *and* trashed session nodes** — the global Trash view (Settings → Database → **🗑 Open Trash**) now shows two sections: **Experiments** (as before, with bulk select / restore / permanent-delete) and **Session nodes**, grouped by session, each node with **Restore** / **Delete forever** and a per-session **Empty (N)** button. The per-session trash *panel* that used to live inside each session's view is gone; the session header's `🗑 Trash` button now opens the unified Trash (its `(N)` chip still reflects that session's trashed-node count), and a session group header links back to the session in the Sessions tab. So a node soft-deleted from the tree (the hover `×`) and an experiment moved to Trash are now managed side by side instead of in two disconnected places. The Trash badge count in Settings now reflects the **combined** total (experiments + nodes).

### Added

- **`core/trash.py` shared aggregation module** — `list_unified_trash(conn)` and `count_unified_trash(conn)` gather both soft-delete domains (`experiments.deleted_at` and `session_nodes.deleted_at`) into one payload, so the dashboard has a single source of truth for "what's in the trash." Backed by a new cross-session `list_all_trashed_nodes(conn)` in `sessions/manager.py` (each trashed node annotated with its owning session's id/name/status). The destructive-file primitive (`_trash_or_local`) was already shared between the two domains; this completes the consolidation at the listing layer. `GET /api/trash` now returns `{experiments, sessions, counts}` instead of a bare experiment array (the dashboard tolerates both), and `get_stats` exposes `trashed_nodes` / `trashed_total` alongside the existing experiment-only `trashed`.

### Fixed

- **Closing the Trash returns you to the Sessions tab if that's where you opened it from** — opening Trash from a session's `🗑 Trash` button and then closing it used to dump you on the main/welcome page; Trash now remembers it was opened from the Sessions tab and restores it on close (other origins still fall back to the welcome screen as before).
- **Clicking an experiment's name in the sidebar now opens it (and double-click-to-rename no longer mis-fires)** — the sidebar card name span used to swallow the click entirely (`stopPropagation` with no action), so the name was a dead zone for opening a run; it now uses the same debounced single-vs-double-click pattern as the main table (`onRowClick` on single click, `cancelRowClick()` before `startInlineRename` on double click), so a single click opens the run and a double click renames without also opening it.

## [1.29.0] - 2026-06-13

### Fixed

- **Promoting a session node now carries its code over so you can retrace and rerun** — when a session node is promoted to a standalone experiment (the dashboard's **＋ Promote to experiment** / `materialize_experiment`), each replayed cell now writes its **full source** to the content-addressed `cell_lineage` table and sets the timeline event's `cell_hash`. Before, only a one-line preview survived the promotion and the Timeline's "view source" button never appeared (it's gated on `cell_hash`), so the session's code looked like it didn't transition at all — now the whole cell is viewable and copyable on the promoted run, which stays linked to its session node.
- **Clicking a just-promoted experiment in the sidebar no longer needs two clicks** — `showDetail()` only toggles back to the welcome screen when the experiment's detail is the view actually on screen. While the Sessions (or Trash) tab overlays the canvas, `currentDetailId` could already equal the clicked run from an earlier visit, so the first click was read as "close" and silently did nothing; it now opens on the first click. Promoting also refreshes the experiment list immediately so the new run is clickable without waiting for an auto-refresh.

## [1.28.1] - 2026-06-13

### Changed

- **Calmer, clearer session-tree rail** — readability fixes to the branch graph: (1) **the palette no longer grows with the number of branches** — the per-branch rainbow (a djb2 hash into `--branch-c0..c5`) is replaced by bounded, state-based color: a neutral spine, one teal for *every* branch line, and amber for abandoned. A tree's lanes never merge, so lane *position* already tells branches apart and color is free to carry meaning instead of identity. (2) **Dot fill is now consistent** — a node's dot is colored by its **type**, independent of the lane color, so a checkpoint is *always* a neutral filled dot (even when it sits on a colored branch line), a branch is always an open ring, abandoned always a dashed ring; the legend spells out "dot shape = node type · line color = spine vs. branch." (3) **Fork curves fan apart immediately** at a divergence (control points lead horizontally right out of the dot) instead of sharing a near-vertical run near the origin, so two sibling branches no longer read as overlapping lines.

### Fixed

- **Tree dots now line up with their own node, and fork lines no longer overshoot** — the node dot (and every line junction) is pixel-anchored to the title line instead of the vertical middle of a stretched, variable-height row, so on tall rows (a node with a param + result line) the dot no longer floats down toward the next node and read as "between" two nodes. The rail's verticals are now position-anchored CSS divs and each fork is a small fixed-height (20px) elbow followed by a straight vertical, so a fork curve can no longer stretch long or run *past* its own dot and dangle (a leaf/abandoned branch's line used to overshoot below its dot).
- **Legend dots no longer doubled** — the legend was rendering both a styled swatch *and* a literal `●`/`○`/`◌` glyph next to each label; removed the redundant glyph so each key shows one mark.
- **Divergence halo is neutral, not violet** — a forking checkpoint's ring halo used the compare-pick purple (`--compare-bg`), which clashed with "purple = a compare pick"; it's now a neutral grey so purple stays reserved for picks.

## [1.28.0] - 2026-06-13

### Changed

- **Session trees now render as a branch graph, not a flat list** — the Sessions tab draws each session as a git-graph-style lane rail: the **checkpoint chain is the neutral dark spine** and **every branch forks into its own color-coded lane that descends straight from the checkpoint dot it came from**, so two experiments tried from the same checkpoint read as equal siblings instead of a main-line + offshoot (the old "first child sits on the trunk" layout made a dead-end branch look like the primary path, with a stray parallel spine-line reaching down to the lower branch). Promoting a branch to a checkpoint makes it rejoin the spine as the main line on the next render. A `⑂ N` divergence badge marks a fork, the most-recent live node is tagged `← latest`, any node with children can be collapsed (persisted per session in localStorage), and a compact **legend** explains the spine/branch-color/dot-shape/`⑂`/`← latest` marks so the graph is self-describing. Lane color is bounded and state-based — neutral spine, one teal for every branch, amber for abandoned (`--branch-c0/c1/ab` in `css/reset.py`, redeclared for dark mode, clear of the violet compare-accent); branches are told apart by lane *position*, not color.

### Added

- **Trace code straight from the tree** — every node now shows a one-line **defining change** (`✎ threshold = 0.7 → 0.5`, pulled from its diff-vs-parent or first cell line) so you can read what made a branch different at a glance, plus a `⟨⟩` toggle that expands the node's **full cell source, syntax-highlighted, inline in the row** — no detour to the detail pane to see what a branch actually ran.
- **Branch context on a converted experiment** — a promoted/materialized run's detail view now shows the **other branches tried from the same checkpoint** (each with its captured result and a link to its own experiment, the current run highlighted), so a run keeps the exploratory context it came out of instead of arriving as an orphan. Backed by `_sibling_branches` on the experiment's `session_origin`.
- **Clickable lineage breadcrumb in the node detail** — selecting a node now shows its ancestor path (`root › checkpoint › branch › …`) as clickable crumbs that jump to any ancestor, so you can orient yourself and retrace where a node sits in the tree. Built from an id-bearing lineage now attached to every node by `build_tree` (no new endpoint).
- **Per-session outcome summary in the tree header** — a **Produced** strip lists the experiments a session generated (clickable chips that open the run) plus checkpoint/branch/abandoned counts, answering "what did this session give me?" at a glance.

### Fixed

- **Session "→ exp" links now actually open the experiment** — clicking a node's `→ exp` badge (or the node-detail Linked-experiment link) previously appeared to do nothing: the Sessions tab overlay hides the detail view with `display:none !important`, and the navigation never dropped that overlay. `showDetailView()` now closes the Sessions tab first, so the experiment detail opens and its sidebar card highlights as expected.

## [1.27.1] - 2026-06-13

### Fixed

- **Dashboard failed to load (blank experiment list)** — a mis-escaped apostrophe in the new experiment→session "From session" back-link (`title="Open this run\'s session node"` inside a raw JS string) closed the JS string early, a syntax error that broke the *entire* dashboard script so nothing past the static header rendered. Replaced the apostrophe with the `&#39;` HTML entity.

## [1.27.0] - 2026-06-13

### Added

- **Link an experiment to a session node from the dashboard ("UI promote")** — the node-detail **Linked experiment** row now lets you point a node at an existing run, **Change** it, or **Unlink** it (the dashboard equivalent of `%exptrack promote`), sitting alongside the existing **＋ Promote to experiment** (materialize a new run) action. Linking is 1:1 with the node so its `→ exp` badge is unambiguous, and only the session pointer is touched — the experiment is never modified or deleted. Backed by `manager.link_experiment` and `POST /api/session/<sid>/link-experiment`.
- **End a session from the dashboard** — an **⏹ End session** button in the Sessions header (UI equivalent of `%exptrack session end`) closes the session and marks any open branches abandoned; ended sessions show a `session ended` tag instead. (The `/api/session/<sid>/end` route already existed; this adds the missing UI.)

### Fixed

- **Copy a single line from a session cell without it snapping shut** — releasing a drag-selection on a cell block's header no longer collapses the `<details>`, so you can select and copy one line (line numbers excluded) with a normal select + copy.

## [1.26.0] - 2026-06-11

### Added

- **`exptrack notebook-guard` — portable notebooks** — prints a paste-able guard cell for the top of a notebook so the same notebook runs with OR without exptrack installed. When exptrack is present it loads normally (full tracking); when it isn't, the `%%scratch` / `%%setup` / `%%pin` / `%exptrack` magics are registered as harmless no-ops that still run the cell body, instead of raising an "unknown magic" error (which, for a cell magic, would silently skip the whole cell). Solves the "it's hard to remove the inline magics" friction when sharing a notebook with collaborators who don't have exptrack.

### Documented

- **`%%setup` in the Session Trees guide** — `docs/session-trees.md` previously documented only `%%scratch` and `%%pin`; it now covers the `%%setup` demoted-prep tier throughout (a three-tiers table, the timing guide, the runnable example, the per-node "what gets attached" section, and the schema), including the positional-scoping gotcha (a `%%setup` cell lands on whichever node is active, and promote/materialize replays only a node's *own* setup, not an ancestor checkpoint's). Added a new **portability** section documenting the guard cell, the `auto_capture.notebook: false` opt-out, and how to strip the magics.

## [1.25.0] - 2026-06-10

### Added

- **Trace an experiment back to its session** — the experiment detail view now shows a "From session" back-link banner whenever a run came from (or is linked to) a Session Trees node, with the session name, the node type (checkpoint/branch), and a `checkpoint → branch` lineage breadcrumb. Clicking it opens the Sessions tab focused on that exact node. Previously the link only worked one way (tree → exp); now you can navigate exp → tree, so a promoted/materialized run is no longer orphaned from the exploration it came from. (`get_experiment_detail` exposes a new `session_origin` field.)
- **Capture settings in the dashboard** — Settings → Capture now exposes two config knobs that previously required hand-editing `.exptrack/config.json`. **Notebook auto-capture** (a checkbox for `auto_capture.notebook`) lets you turn off the per-cell auto-experiment so Session Trees can be used standalone with runs started explicitly. **Variable fingerprint cap (MB)** (`var_fingerprint_max_mb`) controls how large a DataFrame/array is content-hashed for per-cell change detection — lower it if notebook cells are slow to *finish* (objects over the cap fall back to a cheap shape/dtype signature, so the post-cell hook stops re-hashing big frames every run). Both persist to project config via `GET`/`POST /api/config/capture`; a note reminds you to restart the notebook kernel to apply.

### Fixed

- **Promote-to-experiment now carries plots and prep cells** — materializing a session node into an experiment (the `＋ Promote to experiment` button) previously dropped the node's saved plots and its `%%setup` prep cells, so the resulting run was hard to understand. It now registers the node's by-reference plots as artifacts (they appear in the Images tab) and replays `%%setup` cells as muted `setup` Timeline events, and prepends a lineage breadcrumb (`From session 'X' (branch): checkpoint → branch`) to the run's notes.

## [1.24.0] - 2026-06-10

### Added

- **Promote a session node to a real experiment** — a `＋ Promote to experiment` button in the Sessions node detail (for any branch/checkpoint not already linked to a run) materializes a first-class experiment from that node: it copies the node's label as the name, its git commit/diff/branch and note, and replays the node's cells as Timeline events, then links it so the node shows its `→ exp` badge and the run appears in the main list. This is the dashboard equivalent of `%exptrack promote` when there's no live notebook run to attach.
- **Per-line copy in session cells** — every code line in a Session Trees cell block now has a hover-revealed `⧉` button that copies just that one line to the clipboard. No more dragging a selection (which picks up the line-number gutter and can snap the `<details>` cell shut) when you only want a single line.
- **Stale-print flag** — `print()` statements that emit a hardcoded number (e.g. `print("accuracy 98")` instead of `print(f"accuracy {acc}")`) are flagged with an amber `⚠ stale?` marker, since a hardcoded result is usually a value you meant to interpolate from a variable. Surfaced both on the Sessions-tab cell blocks (per-line ⚠ + a per-cell count chip) and in the experiment Timeline (a badge on the cell row + per-line marks in the expanded source). Numbers inside f-string `{…}` placeholders and format specs like `%.4f` are ignored, so it only fires on genuinely hardcoded literals.

### Changed

- **Sticky branch-compare bar** — the Compare / Clear bar in the Sessions tab now sticks to the top of the view while you scroll, and gained a **Done** button to exit Compare-branches mode. Combined with the existing per-node `⇄` pin (start) you can now start and stop a comparison anywhere in a long tree without scrolling back to the header toggle.
- **Expanded session cells survive a re-render** — expanding a cell block in the node detail no longer collapses when the panel re-renders (e.g. saving a note or toggling the diff Split/Unified mode); open cells are remembered and restored.

## [1.23.0] - 2026-06-09

### Added

- **Copy buttons on session cells, outputs & results** — every cell source block, `Out` panel, **Latest result**, and **Compare** column in the Sessions tab now has a small `⧉ Copy` button that copies the full raw text (newlines intact, line-number gutter stripped) to the clipboard in one click. No more fighting scroll, soft-wrap, or a `<details>` block snapping shut mid-selection when you just want to grab a few lines or an output.
- **Per-node compare pin (`⇄`)** — every checkpoint/branch node in the tree gets a hover `⇄` button that adds it straight to the branch comparison, enabling Compare-branches mode on demand. You no longer have to find and toggle the global Compare mode first before clicking nodes — handy when the tree is long and the toggle has scrolled out of view. Picked nodes show the pin filled in the comparison's violet accent.

### Changed

- **Session cell source & output no longer cut off** — the node-detail cell-code (was capped at 360px) and output/result blocks (latest result was capped at 200px) now expand fully so nothing is hidden behind an inner scrollbar; drag the bottom edge to shrink a huge block. Makes reading and copying long cells/outputs straightforward.

### Added

- **`%%setup` cells — recorded but secondary (Session Trees)** — a new cell magic for prep code (e.g. building a `df`) that you'll want to recover later but don't weight like real cells. Unlike `%%scratch` (thrown away), a `%%setup` cell is recorded onto the active session node's *own* byte-budgeted store (`setup_source`/`setup_outputs`), kept out of the tracked-cell lineage/variable churn, and attached to the active run as a muted `setup` timeline event so a promoted experiment stays self-contained. The dashboard shows them dimmed under a collapsed **Setup / prep** section in the node detail (and a 🛠 count on the tree node), so promoting a branch keeps the provenance of your `df` with no rerun and no giant git diff.
- **Promote a branch to a checkpoint from the UI/CLI** — a hover `↑ checkpoint` button on every branch node (and `exptrack session promote-checkpoint <node>`, `POST /api/session/<id>/promote-to-checkpoint`) converts a branch into a checkpoint, freezing its current diff so later branches attach under it.

### Changed

- **Session cells collapse by default** — node-detail cell blocks now all start collapsed (previously the last three stayed open); the "N cells collapsed — expand all" hint reveals them. Keeps long branches scannable.
- **A session groups under one experiment** — while a Session-Trees session is active, the notebook's auto-created run is linked to the current session node the first time a real cell runs (an explicit `%exptrack promote` still re-targets it), instead of floating as a separate, unconnected experiment. `%%scratch`, `%%setup`, and `%exptrack` magic cells never trigger run creation, so a session full of prep/exploration no longer spawns an empty run.

### Fixed

- **`%%scratch` / `%%setup` now display a trailing expression** — these cell magics ran their body with `exec()`, which swallows a bare final expression, so a DataFrame on the last line produced no output unless you added a `print`. Both now split off and route the trailing expression through IPython's display hook, so a final `df` renders normally.

## [1.21.1] - 2026-06-09

### Changed

- **Per-cell timeline writes are batched into one transaction** — a single notebook cell used to issue up to ~52 separate SQLite commits (one fsync each: `cell_exec` + every `var_set` event + the `_var/` params). They now commit once per cell via a new `Experiment.batched_writes()` context, cutting per-cell write latency sharply on large notebooks.

### Fixed

- **Stable DataFrame / object-array fingerprints** — `var_fingerprint` hashed a DataFrame via `df.values.tobytes()`, which for object/string columns serializes Python *pointer addresses* (not content). The hash therefore changed every cell even when the data was untouched, falsely flagging the variable as "changed". DataFrames/Series are now content-hashed with `pandas.util.hash_pandas_object` (object-column safe and stable), object-dtype arrays avoid `tobytes()`, and every fallback uses a stable shape/dtype signature instead of `id()`.
- **No more spurious `_var/` "param overwritten" warning** — the false "changed" detection above re-logged the `_var/<name>` param each cell, and the stored value flipped between the assignment-form display and the bare summary, printing a noisy `[exptrack] warning: param '_var/df_model' overwritten` line. The warning is now suppressed for internal bookkeeping keys (`_var/`, `_code_change/`, `_cells_ran`), and the `_var/` param value is normalized to the bare summary so re-logging an unchanged variable is idempotent.

## [1.21.0] - 2026-06-08

### Added

- **`var_fingerprint_max_mb` config knob** — caps how large a DataFrame/array/Tensor exptrack will content-hash for per-cell change detection (default 100 MB). Lower it (e.g. to `5`) if a notebook namespace full of medium DataFrames makes every cell feel slow — bigger objects then fingerprint by shape+id instead of a full hash.

### Changed

- **`auto_capture.notebook` is now honored** — the flag was documented but ignored; `%load_ext exptrack` always auto-created an experiment from your first code cell. Setting `"auto_capture": {"notebook": false}` now registers the magics and Session-Trees/cell hooks **without** auto-creating a run, so you can use `%exptrack session ...` on its own and start runs explicitly with `%exp_start` / `start()`.

### Fixed

- **Per-cell capture no longer hashes every DataFrame twice** — `_capture_variables` walked the whole notebook namespace and content-hashed each variable in *two* passes (change-detection + snapshot) on every cell. It now computes each fingerprint exactly once per cell, roughly halving the dominant per-cell overhead in DataFrame-heavy notebooks.

## [1.20.1] - 2026-06-08

### Fixed

- **`%exptrack checkpoint` / `branch` no longer hang on git** — the git subprocess helper now redirects stdin from `/dev/null` and disables interactive prompts (`GIT_TERMINAL_PROMPT=0`, `GIT_ASKPASS`) so a misconfigured credential helper or terminal prompt can't freeze a notebook cell on the kernel's inherited stdin, and sets `GIT_OPTIONAL_LOCKS=0` so read-only `rev-parse`/`diff` calls skip waiting on a contended `index.lock`. Session-tree magics (and any other git capture) now fail fast instead of blocking.

## [1.20.0] - 2026-05-29

### Added

- **Notebook cells now capture `print()` output, not just the returned value** — exptrack previously only recorded a cell's trailing-expression `repr` (e.g. a bare `df.head()`), so anything emitted via `print()` was lost. A `pre_run_cell`/`post_run_cell` stdout tee now captures printed output too (while still letting it show normally in the notebook), and the experiment Timeline merges it with the trailing-expression value into one **Out** panel that mirrors what you saw in the notebook (prints first, then the returned value). This applies to both regular experiment tracking and Session Trees. Output is capped at 4000 chars per cell so a chatty training loop can't bloat the database.

### Changed

- **Timeline cell output is shown as a full "Out" panel, below the code** — the cramped, 80-char inline `result:` line is replaced by a proper multi-line **Out** block (scrollable past ~220px) styled to match the Sessions tab. It now always renders *below* the cell's code — previously, expanding "view source" left the result floating *above* the freshly-expanded source; the source is now inserted above the Out panel so the output stays anchored at the bottom.
- **Cell-output panels use a neutral bar, not green** — the **Out** panel (Timeline) and the Sessions `cell-output` / `Latest result` / compare-result blocks previously had a green left bar, but green means "added" in diffs everywhere else. They now use a neutral border so the color doesn't imply a meaning that isn't there.

### Fixed

- **Dark mode no longer shows white cards on a dark background** — the semantic-palette refactor left the legacy color aliases (`--card-bg`, `--fg`, `--muted`, `--code-bg`, `--green`, `--blue`, …) defined only in `:root`. Because a custom property whose value is `var(--other)` resolves at the scope where it's declared, those aliases kept their *light* values in dark mode even though the primitives they point at (`--surface`, `--text-1`, …) were overridden — so every card, table, and toolbar that used an alias stayed white while only the page background went dark. The aliases are now redeclared inside `body.dark` so they recompute against the dark primitives.
- **Timeline "Output saved" no longer appears above the code that saved it** — an artifact logged mid-cell (e.g. `plt.savefig`) used to get a lower timeline `seq` than the `cell_exec` "Code run" event (which is emitted after the cell finishes), so the saved output sorted *above* the code. The `pre_run_cell` hook now reserves the cell_exec's seq before the cell body runs (`Experiment.reserve_timeline_seq()` + `log_event(seq=…)`), so code sorts before the outputs it produced.
- **No more duplicate "cell 1" / "cell_1" on a Timeline row** — a notebook code-run row was showing both the human-readable `cell N` position chip *and* the raw stored `cell_<N>` key (e.g. "cell 1" immediately followed by a bold "cell_1"), which was redundant and read like two different things. The Timeline now shows a single cell label per row: the `cell N` chip when the notebook cell position is known, falling back to the stored key reformatted (`cell_1` → `cell 1`) for scripts or runs captured before cell positions were tracked. The internal `cell_<exec_num>` key is never surfaced alongside the chip.

## [1.19.0] - 2026-05-29

### Changed

- **Calmer, semantic dashboard palette** — the dashboard now draws from a tightened, centralized token set instead of ~10–12 competing hues. `css/reset.py` is the single source of truth: one primary `--accent`, three semantic status colors (`--status-success`/`-danger`/`-warning`) each with a matching soft tint, a single distinct `--compare-accent` (the only remaining purple), and de-saturated Python syntax tokens (`--tok-*`). The 5-color Timeline scheme is reduced to mostly-neutral left bars with the accent reserved for code runs and warning kept for metrics — events are now told apart by **icon + label**, not a wall of color. The `--diff-*` and `--compare-*` variables (previously defined in `css/sessions.py`) moved into `reset.py` so every color lives in one place, and scattered hardcoded `rgba()` tints and `var(--red,#hex)` fallbacks across modules were migrated to the new tokens (including the non-standard `--y`).
- **More readable type, spacing, and structure** — the UI now uses a system **sans-serif** for prose and controls while code, diffs, and raw values stay **monospace**, so long text is easier to skim. Secondary text is darker for contrast (`--muted` → `#5a5a5a`), the three near-identical light surfaces (`--bg`/`--surface`/`--surface-2`) are now genuinely distinct, sub-11px font sizes were lifted to an 11px floor, and a 4px-based spacing scale (`--space-1..6`) plus a type scale (`--text-xs..lg`) back the layout.
- **The Timeline tells you what each event means** — event types now carry plain-language labels ("Code run", "Variable set", "Output saved", "Metric", and "Ran, no change" instead of the cryptic "observe"), a coherent icon set replaces the ad-hoc `>>`/`..`/`=` glyphs, and a compact always-visible **legend** plus hover tooltips explain every icon, label, and badge. The filter bar now matches the same wording (and the stale "Lineage"/"Resumed" label mismatch is fixed).
- **No more jargon or color collisions on a Timeline code row** — the cryptic `← <hash>` "lineage" badge is now `← earlier version` with a plain tooltip ("This cell was edited from an earlier version — click to view it"), and the **Lineage** filter is renamed **Edited cells**, so the internal parent-hash term never surfaces. A second **Badges:** legend row explains every chip on a code-run row (`new` / `edited` / `rerun` / `result` / `← earlier version`). The overloaded word "output" is disambiguated — the cell-result chip and its preview are now labelled **result** (a returned value), distinct from the **Output saved** event (a file written). Most importantly, **inside a diff color now means only one thing: added vs. removed** — syntax token colors are muted to plain ink within diff rows so a green string literal can no longer read as an "added" line; the red/green tints, sign gutter, and word-level pills carry all the change meaning, while non-diff code previews keep full syntax highlighting.
- **Cleaner Timeline rows — calmer color, fewer badges, quieter diffs** — green is now reserved for *added / new* everywhere: string literals moved off the success-green to the same amber as numbers (one "literal value" color), so a green string can't be confused with an added line even in a non-diff preview. A code-run row now shows at most **one** status chip — `new`, `edited`, or `rerun` — the `result` chip is gone (the inline `result:` line already shows it) and the separate `← earlier version` chip folded into `edited`, which is now itself the click-to-view-earlier-version link. And the word-level diff only spotlights genuine small in-place edits: when two lines are more rewrite than tweak (less than ~50% shared tokens) it falls back to plain add/del lines instead of peppering the row with word-pills.
- **Readable word-diff spotlight + an off switch** — the in-place word-diff pill (e.g. the `0.7` → `0.5` on an otherwise identical line) was a solid green/red block with white text and a strikethrough, which fought the surrounding code and was hard to read when you expanded a long line. It now keeps normal ink on a soft tint with a colored underline carrying the add/remove signal, so the changed token pops against the line's own faint wash without whiting out the code. And there's a new **Highlight word-level diff changes** toggle in Settings → Display (default on) — turn it off to get plain line-level add/remove everywhere diffs appear (Code Changes, Uncommitted Changes, and the Timeline), handy when an edit is large enough that the per-word pills get busy.
- **Word-level diff in the full cell source, not just the preview** — expanding **view source** on an edited Timeline cell now renders the whole source as a diff (current vs. previous) with the same word-level spotlight as the short timeline preview, instead of two separate plain blocks you had to eyeball-compare. Unchanged lines stay as context so the full source is still visible, and it honors the word-diff toggle (off ⇒ plain line-level). Expanding the source now also collapses the row's short inline preview so the two no longer duplicate each other (it returns when you hide the source). Very large sources fall back to the previous side-by-side dimmed view.
- **Line numbers in diffs + clearer Timeline numbers** — code diffs (the **view source** cell diff and the **Uncommitted Changes** git diff) now show an old/new line-number gutter, seeded from the `@@` hunk headers for git diffs, so you can place a change in the file. And the small number on each Timeline row — previously a bare figure that read like it might be a line or cell number — is now prefixed with `#` and explained on hover as execution order. Notebook code-run rows also show a small grey `cell N` chip (the notebook cell position) so you can tell *which cell* ran, separately from when it ran.

## [1.18.1] - 2026-05-28

### Fixed

- **Timeline no longer word-diffs exptrack magic cells against unrelated cells** — a cell containing only `%exptrack` magics (`checkpoint "…"`, `branch "…"`, `%load_ext exptrack`) is a command, not editable code, but cell lineage was treating it like any other cell: the fuzzy `SequenceMatcher` parent finder (30% similarity) easily matched two short magics that merely share `%exptrack ` and quotes, so a `checkpoint` cell showed up as `edited` with a `← <hash>` lineage badge and a nonsensical red/green word-diff against, say, an earlier `session start` cell. `cell_lineage.is_magic_only()` now excludes magic-only cells from lineage both as the diff subject and as parent candidates (so they can't pollute matching for real code cells either), and `_process_cell_lineage` emits no new/edited badge or diff for them — they render as the command they are. A render-time guard in the Timeline view (`_isMagicOnlyCell`) suppresses the stale badges/diff for runs captured before this fix, so existing experiments read cleanly without a re-run. Note: this only affects magic-*only* cells; a cell that begins with `%exptrack branch` but then runs real code is still tracked and diffed normally.

## [1.18.0] - 2026-05-28

### Added

- **Syntax highlighting + word-level diffs in the experiment view** — the IDE-style Python coloring previously only in the Sessions tab now applies everywhere code shows up in the experiment detail view: the **Code Changes** section, the **Uncommitted Changes** git diff, the **Timeline** cell-source viewer, and the inline cell previews. More importantly, diffs now spotlight *exactly what changed* — when a line is edited in place (the classic `threshold=0.7` → `0.5` re-run, where the whole line looks identical except one token), a word-level diff highlights just the changed span in a solid pill instead of showing two near-identical red/green lines you have to eyeball-compare. Diff lines also switched from color-only text to a background tint + sign gutter so syntax colors and add/del status are both visible at once. The highlighter and word-diff logic are extracted into a shared `js/highlight.py` module (single source of truth for both the Sessions tab and the experiment view), with token colors moved to unscoped rules in `css/code.py`.

### Fixed

- **Auto-generated run names no longer break on notebook bookkeeping params** — in a notebook session, internal params exptrack logs for its own tracking (`_var/…` assignment captures, `_code_change/…` diff fragments, `_cells_ran`) were being fed into `make_run_name`; since it takes the *first* N params, they crowded out the real hyperparameter, and their values (which contain slashes and spaces — e.g. `_var/data` → `data = make_data()`) turned the run name into a nested path like `May28_Untitled___var/datdata = make…`, making the on-disk output-folder rename fail with `No such file or directory`. `make_run_name` now skips any param key beginning with `_` before picking the top N, and path-sanitizes every name component, so names stay short, readable (`May28_Untitled__threshold0.7__a3f2…`), and always a single valid folder name.

## [1.17.0] - 2026-05-28

### Added

- **Plots attach to branches, by reference** — when `plt.savefig(...)` runs while a session node is active, exptrack now records the file path on that node (no copy, consistent with its no-copy artifact rule). The dashboard renders the plots as a thumbnail grid in the node detail (**Plots (N)**), side-by-side in the branch **Compare** view, and shows a `🖼 N` indicator on the tree node — so you can fire off `threshold = 0.7` / `threshold = 0.5` branches that each `savefig` a train/test curve and eyeball them next to each other. Thumbnails link to the full image and degrade to a "⚠ image missing on disk" note if the file was moved or overwritten. Backed by a new nullable `session_nodes.images` column (JSON list of `{path, label, ts}`, deduped by path, capped at 30 most-recent) populated by `SessionManager.record_image()`. **Note:** because plots are tracked by reference, saving every branch to the *same* filename (`roc.png`) overwrites the earlier branch's plot on disk — give each branch a distinct filename (`roc_0.7.png`) to compare them.
- **Attached plot files are removed when a node is permanently deleted** — purging a trashed node (`purge-node`) or emptying a session's trash now moves that node's by-reference plot files to your **OS Trash** (recoverable; never `rm -rf` — the same mechanism experiment-delete uses), and reports how many were moved. Soft-deleting a node (`rm-node` / the tree `×`) leaves the files in place so Restore still works; the soft-delete confirm warns that the N attached plots will be trashed if you later purge. Whole-session `delete` (`session rm`) leaves plot files untouched, the same way it preserves linked experiments.

## [1.16.0] - 2026-05-28

### Added

- **Branch-label collision guard (auto-suffix + alert)** — re-using a branch label under the same checkpoint with *different* code (the classic copy-paste-and-edit footgun) no longer silently merges the two explorations into one node. `branch()` can't tell at call time whether you're re-running (Run All) or starting a new idea — the cells haven't executed yet — so it arms a one-shot guard and the next recorded cell decides: if its first cell matches the existing node's first cell it's a genuine re-run (merge, as before); if it differs, exptrack forks a fresh `label (2)` node, switches to it, and prints a stderr notice telling you it did so and how to rename it. New `SessionManager._resolve_branch_collision` / `_create_branch_node` / `_unique_branch_label`.
- **Rename session nodes** — node labels are now editable: double-click the label in the dashboard node-detail header (inline edit, Enter/blur saves, Escape cancels), `POST /api/session/<sid>/rename-node`, or `exptrack session rename-node <node_id> "label"`. Backed by `rename_node(node_id, label)` in `manager.py` (rejects empty labels and trashed nodes). Primarily for fixing up auto-suffixed forks, but works on any live branch/checkpoint.
- **Syntax-highlighted session cell code** — the cell-source blocks in the Sessions tab now render with lightweight, dependency-free Python highlighting (keywords, strings, comments, numbers, decorators, builtins, and function calls each get their own theme-aware color) and soft-wrap long lines so wide code stays readable without horizontal scrolling. The highlighter HTML-escapes every token as it emits, so it's safe against injection.

### Changed

- **Compare-picked nodes use a distinct violet accent** — picking a node for branch comparison previously drew the same blue bar as the hover/selected state, so a node you'd merely clicked looked already-picked. Picks now use a dedicated violet accent (`--compare-accent`, with a dark-mode variant) for the 6px bar, tint, order badge, the Compare toolbar, and the comparison columns' top border — clearly separate from the blue selection accent.

## [1.15.1] - 2026-05-28

### Fixed

- **Branch compare: picked nodes are no longer confusable with the one you were viewing** — entering `⇄ Compare branches` left the previously-selected node wearing its thin blue accent bar, which looked identical to the "picked for compare" bar, so it read as already-selected when it wasn't. The single-select highlight is now suppressed while comparing, picked nodes get a thicker 6px bar plus a tint, and each carries a numbered badge (1, 2, 3…) showing its order in the comparison. Removing a middle pick renumbers the rest.

## [1.15.0] - 2026-05-28

### Added

- **Branch results are captured automatically** — every cell that runs under a session node now records its output (the trailing-expression `repr`, e.g. the `{'kept': 157, 'rate': 0.314, 'accuracy': 0.814}` dict you see in the notebook) alongside its source, so after firing off a branch you can see what it produced without promoting it to an experiment first. A new `session_nodes.cell_outputs` column mirrors `cell_source` segment-for-segment (one output per recorded cell, kept aligned through dedup and elision). In the dashboard, each tree node shows a one-line `⤷ result` preview, the node detail shows a **Latest result** block and an `Out` panel under each cell, and re-running a cell back-to-back refreshes its captured output instead of duplicating the cell.
- **Compare branches side-by-side** — a new `⇄ Compare branches` toggle in the session view header turns the tree into a multi-select; click any checkpoints/branches to add them to a comparison, then **Compare N** renders them as side-by-side columns showing each node's type, cell count, `+N −M` diff summary, promoted-experiment link, and captured **Result**. Makes "which threshold won" obvious at a glance. Picked nodes get a thick blue accent bar and a numbered order badge; the selection survives tree re-renders.
- **Empty the session trash / delete trashed nodes for good** — previously a trashed session node could only be *restored*; the sole way to truly remove it was deleting the entire session. New `purge_node(node_id)` and `empty_trash(session_id)` in `exptrack/sessions/manager.py` permanently drop trashed rows (refusing anything not already trashed, so removal stays a deliberate trash → purge two-step). Surfaced as **Delete forever** per row and an **Empty trash (N)** button in the dashboard Trash panel (both with no-undo confirms), plus `POST /api/session/<sid>/purge-node` and `POST /api/session/<sid>/empty-trash`. CLI gains `exptrack session purge-node <node_id>` and `exptrack session empty-trash <id_or_name>` (both prompt unless `-y`/`--yes`). Linked experiments are preserved throughout.

## [1.14.0] - 2026-05-27

### Changed

- **Session node deletion is now soft (Trash + Restore) instead of permanent** — the `×` button on tree nodes (and `exptrack session rm-node`) used to hard-`DELETE FROM session_nodes` the moment you confirmed, taking the node's `cell_source` snapshot and `git_diff` with it. The same operation now flips a new `session_nodes.deleted_at` timestamp instead: the row stays in place, `build_tree` filters it out, and a new per-session Trash panel surfaces it for recovery. Lives under a new `🗑 Trash (N)` button in the session view header — clicking it expands a panel listing each trashed node with its type, label, deletion time, cell-source size, and a **Restore** button. Restore brings the node and its entire trashed subtree back atomically; if the node's parent was also trashed (e.g. you restore a child of a cascaded delete), the parent and any trashed ancestors are revived too so you never end up with a re-orphaned subtree dangling off the root. Linked experiments are *not* re-attached on restore — `delete_node` cleared `experiments.session_node_id` and we have no way to know which run was the "right" one. The hard-delete escape hatch is still available via `delete_session` (deleting a session also drops its trashed nodes).
- **New endpoints + CLI for the Trash workflow** — `GET /api/session/<sid>/trash` returns the trashed-node list, `POST /api/session/<sid>/restore-node` (body `{node_id}`) restores a subtree. CLI gains `exptrack session trash <id_or_name>` (list a session's trashed nodes) and `exptrack session restore-node <node_id>` (prefix match). The dashboard confirm prompt for delete no longer says "This cannot be undone" — it now reads "Moves the node(s) to this session's Trash — restore from the Trash panel."

### Added

- **`session_nodes.deleted_at` column** — nullable `REAL` (unix timestamp). Added via idempotent `ALTER TABLE` in `_ensure_schema()` so `exptrack upgrade` migrates existing projects in place. Indexed on `(session_id, deleted_at)` so the Trash list query stays cheap on large sessions.
- **`list_trashed_nodes(session_id)` and `restore_node(node_id)`** in `exptrack/sessions/manager.py` — the same module that already owns `delete_node` / `delete_session`. `restore_node` walks the trashed subtree and any trashed ancestors in a single transaction; both functions are tested for the obvious paths (round-trip restore, refusing to restore a live node, orphan-guard on parent revival).

## [1.13.0] - 2026-05-27

### Added

- **Delete a single session node (cascade)** — until now the only way to remove session-tree clutter was to nuke the whole session. New `delete_node(node_id)` in `exptrack/sessions/manager.py` cascade-deletes one branch or checkpoint and every descendant (a branch without its children is rarely useful, so cascade is the only mode). Linked experiments are preserved with `session_node_id` cleared, matching the existing whole-session-delete behavior. Refuses to delete the session root (use `exptrack session rm` for that). If the live in-memory `SessionManager` was pointing at a node about to be deleted, `_current_node_id` / `_last_checkpoint_id` are reset so subsequent `checkpoint()` / `branch()` calls don't dangle on a vanished row. Surfaced as:
  - **CLI**: `exptrack session rm-node <node_id>` (prefix match, prompts with a `{nodes_total}, {experiments_linked}` summary; `-y` / `--yes` to skip the prompt).
  - **Dashboard**: a tiny `×` button appears on hover (and when selected) on every non-root tree node. Clicking it POSTs to `/api/session/<sid>/delete-node-preview` first to fetch counts, then shows a native confirm with the node label, the descendant count, and the number of linked experiments that will be preserved. Confirming POSTs to `/api/session/<sid>/delete-node`.
  - New companion helper `preview_node_delete(node_id)` returns `{label, node_type, is_root, nodes, descendants, experiments}` so callers can show counts without doing a trial delete.

## [1.12.0] - 2026-05-27

### Added

- **`git_diff_exclude` config — keep notebooks out of the captured diff** — a new top-level config key (default `["*.ipynb"]`) takes a list of git pathspec patterns that are excluded from every diff capture (experiment creation, session checkpoint, session branch, and the per-cell branch refresh). The old behavior dumped the full output of `git diff HEAD` into `experiments.git_diff` and `session_nodes.git_diff`, which on projects with a committed `.ipynb` meant the notebook's JSON churn (output cells, execution counts) ate the `max_git_diff_kb` byte budget before any real `.py` changes made it in. Notebook work is already captured by the cell snapshot + cell-lineage system, so excluding `.ipynb` from `git diff` by default keeps the captured diff focused on actual source edits. Override by setting `git_diff_exclude: []` in `.exptrack/config.json` to restore the old behavior, or extend with additional pathspecs (e.g. `["*.ipynb", "*.csv", "data/**"]`). Implemented as a new `git_diff(*range_args)` helper in `core/git.py` that appends `-- :(exclude,glob)<pattern>` args; threaded through `git_info()` and every `_git("diff", …)` call in `sessions/manager.py`.
- **"awaiting first cell…" placeholder on empty session nodes** — a branch or checkpoint created via `%exptrack branch "foo"` / `%exptrack checkpoint "bar"` in a magic-only cell has no `cell_source` until the user runs another cell (the magic cell itself is intentionally skipped by `_is_session_cell`). Previously this rendered as a silent blank node and users assumed branching was broken. The tree now renders an italic monospaced `awaiting first cell…` line under any branch/checkpoint node that has no recorded cells and no children, so the empty-state is explicit and the user understands the node will populate on the next cell run.

## [1.11.5] - 2026-05-27

### Changed

- **Sessions tab UI polish** — the node tree, session cards, and detail panel were dense and hard to scan. Each tree node now renders on two lines (label + abandoned/exp pills on top, a dim mono-font meta line with time · cells · `+N −M` below, and any note wrapping under that). The selected node is marked with a 3px blue left accent bar instead of relying on background tint alone, and selection sync no longer parses `onclick` strings — it reads `data-node-id`. Abandoned branches now show an amber `abandoned` pill, an amber-dashed left border, and a strike-through label so they read at a glance instead of just fading out. Session cards in the left rail collapsed from three lines into a tighter two-row layout (name + status pill on top, notebook · checkpoints · relative time below).
- **Note editor in the session detail panel gives feedback** — the Save note button now disables until the textarea is dirty, shows "Saving…" during the POST, and stamps "Saved · HH:MM" (in green) on success. Saving silently refreshes the tree in-place instead of redrawing the whole detail and yanking the just-confirmed indicator away.
- **Sticky diff toolbar in the session detail** — the Split / Unified toggle and `+N −M` summary now sit in a sticky header bar at the top of the diff section, so they stay reachable while scrolling a long diff instead of disappearing off-screen.
- **Collapsed cells in the node detail are visible** — when a node records more than three cells, the older ones still default to collapsed, but a clickable `▸ N earlier cells collapsed — expand all` hint now sits at the top of the cell list so the user can see what's hidden and open everything in one click.

## [1.11.4] - 2026-05-26

### Fixed

- **Inline rename in the main table no longer hides what you're typing** — the name column is narrow with `overflow: hidden; white-space: nowrap`, and the `auto` badge eats ~30px at the front, so the `width: 100%` rename input ended up extending past the cell's right edge into the clipped zone. As you typed, the input scrolled its content to keep the cursor on the right — which was exactly where the column clipped — so old characters scrolled into view on the left and your current typing lived behind the clip, making the box look empty. The truncate-cell now lifts its `overflow: hidden` (and bumps `z-index`) while a `.name-edit-input` is mounted inside, so the input renders fully and the cursor stays visible. Added an explicit `color: var(--fg)` to `.name-edit-input` defensively so inputs always pick up the theme text color (some browsers don't inherit color into `<input>`/`<textarea>` by default).
- **Renaming a run with "Needs naming" checked no longer makes it vanish** — committing an inline rename clears `name_is_auto`, which used to drop the row out of the filtered view instantly with no visible confirmation that the rename worked (and made multi-step edits like fixing a typo feel impossible). Just-renamed rows now stay visible in the "Needs naming" view for the rest of the session — the missing `auto` badge is the visual confirmation, and the `(N)` count still reflects the real backlog. Toggling the filter off (or reloading) clears the held-over rows.

## [1.11.3] - 2026-05-26

### Fixed

- **Inline rename in the main table no longer disappears mid-edit (real fix)** — the v1.11.2 attempt only addressed the sidebar; the table bug had a different cause. Any of several normal events (a tag added in detail view, a metric POST, a backend `loadExperiments()` cycle from mutations) calls `renderExperiments()` while the user is still typing in the rename input, blowing away `#exp-body` innerHTML and triggering the input's blur — which then committed the partial text. `startInlineRename` now stores the in-progress input on a module-level `activeRename`, and `renderExperiments`, `renderExpList`, and the detail-panel rewrite each call `_preserveActiveRename()` to detach the input *before* the innerHTML reset and re-mount it in the freshly-rendered name slot (with value, focus, and selection preserved) afterwards. The blur handler now no-ops when the input has been detached, so a re-render no longer counts as the user finishing.
- **Cursor jump in `{{template}}` variable inputs (real fix)** — the v1.11.2 surgical-span update wasn't enough; the underlying cause was `draggable="true"` on the parent `.cmd-item`. In several browsers (notably Firefox/Safari) a draggable ancestor disrupts cursor and selection behavior in child inputs as soon as you click into them, sending the caret back to position 0 between keystrokes. `draggable="true"` now lives on the `.cmd-drag-handle` glyph only; the card itself only listens for `dragover`/`drop`. Reorder still works the same — you just grab the handle, not the card body.

## [1.11.2] - 2026-05-26

### Fixed

- **Inline rename in the sidebar no longer disappears mid-edit** — double-clicking a run name in the sidebar used to bubble the first click up to the card, which fired `showDetail` → `renderExpList`, redrawing the sidebar while the user was still typing and losing the input. The name span now stops single-click propagation (matching how the main table already handles it), so the rename input survives until you press Enter or click away.
- **Cursor no longer jumps to the front when editing a `{{template}}` variable** — the previous keystroke handler rebuilt the entire command code block via `innerHTML` on every keypress, which on some browsers stole focus from the variable input and reset its cursor to position 0. Each `.cmd-fill` span now carries a `data-var` attribute, and the handler updates only the matching spans' `textContent` / class in place, so focus and caret position stay put.

## [1.11.1] - 2026-05-26

### Added

- **Drag-and-drop reorder for saved commands** — every command card in the Commands notepad now has a drag handle in its header; drag a card up or down to set the order, which persists in `.exptrack/config.json` via a new `POST /api/commands/reorder` endpoint. The list no longer sorts by "most recently edited" — your hand-picked order is what shows.
- **Color-highlighted template fills** — when a command contains `{{var}}` placeholders, the substituted values in the rendered command line are now visually highlighted (blue tint for filled, amber for still-empty), so you can see at a glance which segments came from the variable inputs vs. the literal command text.
- **Live count on the "Needs naming" filter** — the toggle in the Group-by bar now shows `(N)` next to its label with the number of un-renamed runs in the current set, so the filter has a visible signal even when every run still needs naming. Updates on load and after every inline rename.

### Changed

- **Filled-in commands go to the export** — `.sh` / `.md` / `.json` exports of saved commands now write the *substituted* version of templated commands (with the variable values you typed in), so the exported script is runnable as-is. Tokens you never filled in stay as `{{var}}` in the export so they're visible. JSON keeps both `command` (raw template) and `filled` (substituted) on each entry for round-tripping.
- **Clearer command-card hierarchy** — the title (label) is now bigger and bolder, the header has a subtle gradient + bottom border, and the code area sits in its own contrasted block — so it's easier to tell title vs. command at a glance. Empty labels fall back to `(unlabeled)` instead of rendering as an invisible gap.
- **Removed the `{{ }}` badge next to command titles** — it was redundant noise; the variable inputs above the code already make the templated-ness obvious.

### Fixed

- **Inline rename now refreshes the "Needs naming" count** — renaming an experiment from the dashboard immediately clears its in-memory `name_is_auto` flag and updates the count next to the filter toggle, so you don't have to reload to see the badge disappear.

## [1.11.0] - 2026-05-22

### Added

- **Command templates with `{{variables}}`** — any saved command in the Commands notepad can now contain `{{name}}` placeholders. Each unique placeholder renders an editable input above the command; the code block shows the live-substituted result and **Copy** copies that filled-in version, so you can tweak a value (e.g. a date) and re-run without retyping the whole command. The template text (with `{{...}}`) is never mutated. Filled-in values are remembered per command (persisted to `.exptrack/config.json` as a `values` map). Variables named `date`/`today` (or ending in `date`) get a native date-picker input and **default to today** every session instead of going stale. A small `{{ }}` badge marks templated commands.
- **"Auto-named" flag + "Needs naming" filter** — exptrack now tracks whether a run still carries its auto-generated name (vs. one you deliberately renamed). Un-renamed runs show a small amber **auto** badge in the sidebar and the experiments table, and a **Needs naming** toggle in the Group-by bar filters the list down to just those, so the runs you forgot to name stop getting lost. A deliberate rename (dashboard double-click or `POST /api/experiment/<id>/rename`) clears the flag. Adds a `name_is_auto` column to `experiments` (idempotent migration) that **backfills your existing backlog** by fingerprinting generated names.
- **Group experiments by Day** — the main table's Group-by bar gains a **Day** option that clusters runs under `Today` / `Yesterday` / `Wed, May 20, 2026` headers (timezone-aware). Days other than the most recent start collapsed so old work folds away while today's runs stay in view.
- **Date-range filter** — a **Show:** control in the Group-by bar (`All time` / `Today` / `7d` / `30d`) filters both the sidebar and the main table to runs created in that window. Pairs with the existing search box. Selection persists in localStorage.

### Changed

- **Readable date in auto-generated run names** — `make_run_name` now front-loads a friendly month/day so un-renamed runs read chronologically: `May22_train__lr0.01_bs32__a3f2…` instead of the old `train__lr0.01_bs32__0312_a3f2…`. Set `naming.date_style` to `"numeric"` in `.exptrack/config.json` to keep the legacy `MMDD` layout.
- **Clearer search placeholders** — the sidebar and main search boxes now read "Search name, params, tags…" / "Search name, params, tags, notes…" to surface that search already matches parameter keys/values, tags, studies, branch, and notes — not just the name.

## [1.10.1] - 2026-05-17

### Changed

- **Permanent-delete now moves files to the OS Trash, not `rm -rf`** — when the "Also move files to system Trash" checkbox is ticked on a permanent delete, artifact files and the experiment's output directory are sent to the user's system Trash (Finder Trash via `osascript` on macOS, XDG `~/.local/share/Trash` on Linux) instead of being unlinked. If the OS-trash call fails (or platform isn't supported), files fall back to `<project>/.exptrack/trash/<timestamp>__<name>/`. Files are never destructively deleted — if both OS-trash and local-fallback fail, the file is left alone with a stderr warning. `delete_experiment` now returns a `{os_trash, local_trash, missing, failed}` count dict; `POST /api/experiment/<id>/delete-permanent` and `/api/bulk-delete-permanent` include this as `file_stats` in the response. Modal copy updated: "Also delete files on disk" → "Also move files to system Trash" with a hint about Finder/Files recovery and the `.exptrack/trash/` fallback. Bumped patch version since the API response shape is additive

## [1.10.0] - 2026-05-17

### Added

- **Soft-delete (Trash) for experiments** — the dashboard delete button (and bulk delete) now defaults to a reversible **Move to Trash** instead of an immediate, destructive hard delete. Trashed experiments are hidden from the experiment list, stats cards, tag/study/branch aggregations, and pickers — but their database rows, artifact files, and output directories are completely untouched. A new **Trash** view (header button, 🗑) lists trashed experiments with **Restore** and **Permanently delete…** actions, plus bulk Restore / Permanent-delete. Adds a `deleted_at` column to `experiments` (nullable; non-null = trashed), `trash_experiment` / `restore_experiment` / `list_trashed_experiments` helpers in `core.db`, a new `trashed` field on the stats endpoint, and an `include_trashed=` opt-in on `list_experiments`. Schema migration is idempotent (`exptrack upgrade` is a no-op on already-migrated DBs)
- **Delete-confirm modal with full scope preview** — replaces the bare `confirm('… cannot be undone')` browser dialog. Before deleting, the modal now shows the experiment name + id, metric/param/timeline/artifact counts, the output directory (with file count + total size), and notebook history snapshot count. Two tabs split the choice: **Move to Trash** (default, non-destructive) and **Permanently delete…** (destructive). Bulk delete shows aggregate totals across the selected experiments plus a scrollable per-experiment list. New endpoints: `GET /api/experiment/<id>/delete-preview`, `POST /api/bulk-delete-preview`
- **"Keep artifacts" by default on permanent delete** — the permanent-delete tab includes a checkbox **"Also delete files on disk"** that defaults to **OFF**. The DB record (metrics, params, artifacts, timeline, notebook history snapshots) is removed, but artifact files and the experiment's output directory are preserved unless the user opts in. New endpoints: `POST /api/experiment/<id>/delete-permanent` (body: `{delete_files}`), `POST /api/bulk-delete-permanent`, `POST /api/experiment/<id>/restore`, `POST /api/bulk-restore`, `GET /api/trash`

### Changed

- **`POST /api/experiment/<id>/delete` and `POST /api/bulk-delete` are now soft-deletes** — they set `deleted_at` and leave files alone. The destructive path is now only reachable through the new `/delete-permanent` endpoints. Code that relied on the old hard-delete semantics from these endpoints should switch to `/delete-permanent` with an explicit `{delete_files: true}` body
- **Default queries now filter out trashed experiments** — `list_experiments`, `get_stats` (every count), `get_all_tags`, `get_all_studies`, `get_studies`, and unique-branches stats all add `deleted_at IS NULL`. Single-experiment lookups (`find_experiment`, `get_experiment_detail`) are deliberately unfiltered so the Trash view can still load detail by id

## [1.9.2] - 2026-05-07

### Added

- **Side-by-side diff in the Sessions tab** — node diffs now render as a GitHub-style split view with one column per side, grouped by file (collapsible), with per-file `+N −M` stats, hunk headers, and a `Split / Unified` toggle (`localStorage` key `exptrack-diff-mode`). Replaces the single-column wall of green/red lines
- **Branches capture and refresh their diff** — `%exptrack branch "label"` now snapshots `git diff` against the parent checkpoint at creation, and `record_cell` refreshes the branch's `git_diff` after each non-`%%scratch` cell so the dashboard always shows the current divergence under that branch. Checkpoints still freeze their diff at creation. New `SessionManager._compute_diff_vs_checkpoint` helper concatenates the committed-range diff with the working-tree diff when commits differ

### Changed

- **Diff coloring is theme-aware and subtler** — added/removed lines now use semi-transparent tints driven by new `--diff-add-bg`, `--diff-add-bar`, `--diff-del-bg`, `--diff-del-bar`, `--diff-empty-bg`, `--diff-hunk-bg` CSS variables (with separate values for `body.dark`), plus a 3px inset bar instead of the old saturated `rgba(...)` block. Easier on the eyes than the previous wall-of-green/wall-of-red
- **Sessions tab buttons and inputs match the rest of the dashboard** — the per-node "Save note" button and note `<textarea>` previously used hard-coded colors and an undefined `--input-bg` / `--text` variable (so dark mode showed white-on-white); they now follow the same `var(--code-bg)` / `var(--card-bg)` / `var(--border)` pattern as `.bulk-bar button` and other action buttons. Same fix applied to all `var(--accent)` / `var(--hover-bg)` references in the sessions stylesheet, which were also undefined

## [1.9.1] - 2026-05-07

### Changed

- **Sessions tab — readable diffs and cell runs** — the node-detail panel previously rendered git diffs and captured cells as undifferentiated `<pre>` blobs. Diffs now render line-by-line with green/red coloring (added/removed) plus dimmed context, file/hunk headers, and a `+N −M` summary next to the section title. Captured cell runs render as collapsible `<details>` blocks with a header (`cell N / M`, line count) and inline line-number gutter; when a node has more than three cells, older ones default to collapsed so the most recent work stays in view

### Fixed

- **`CHANGELOG.md` version-bracket links** — reference-style URL definitions only existed for `[1.0.0]`–`[1.1.0]`, so every version header from `[1.2.0]` onward (including `[1.9.0]`) rendered as plain text instead of a GitHub compare link. Added the missing definitions through `[1.9.1]`

## [1.9.0] - 2026-05-07

### Added

- **Sessions tab auto-refresh** — the Sessions list now reloads automatically when the dashboard window regains focus (the most common moment a session was just created in the notebook), and the list header gets explicit Refresh (`↻`) and Close (`×`) buttons. Clicking the `☰ Sessions` header toggle while the tab is already active reloads instead of closing — the previous behavior of "click again to close" was confusable with "click again to see new data"
- **`%%pin "label"` cell magic** — runs the cell, captures stdout and the trailing expression's repr, and saves a markdown artifact (`pin_<timestamp>_<label>.md`) on the active experiment. If a session is active, also appends `pinned: <label>` to the current node's note. Lets you freeze "this is the result I want to come back to" without leaving the notebook
- **Delete sessions from the dashboard** — every session card in the `☰ Sessions` tab now has a `×` button (with a confirmation prompt) that calls the new `POST /api/session/<id>/delete` endpoint. Linked experiments are preserved with their `session_node_id` cleared, matching `exptrack session rm`
- **`%exptrack` magic + code in the same cell now records the code** — putting `%exptrack branch "X"` (or `checkpoint "Y"`) at the top of a working cell with code below it is the natural pattern, but the previous filter saw the leading magic line and skipped the whole cell, so cells run "under" a freshly-declared branch were invisible until the *next* cell ran. Now `%exptrack` line magics are stripped from the recorded cell source while the rest of the cell is captured live. Pure-magic cells (only `%exptrack` lines plus comments/blanks) and cell magics (`%%scratch` / `%%pin`) still skip entirely
- **Cells stream into the active node live, idempotent re-runs** — every non-magic cell that runs while a session node is active is appended to *that* node's `cell_source` immediately, so cells under a `branch` show up under the branch right away (no need to make a follow-up checkpoint to materialize them). Re-running a cell that contains `%exptrack checkpoint "X"` or `%exptrack branch "Y"` reuses the existing node by label instead of creating a duplicate; abandoned branches revive when their label is re-declared. Immediate re-runs of the same cell are deduped. Replaces the previous "buffer + drain on next node" model that left cells invisible until a follow-up checkpoint
- **Session Trees per-node cell capture** — every non-`%%scratch` cell run while a session node is active is appended to that node's `cell_source`, so the dashboard's node-detail panel shows the verbatim cells (split out into individual code blocks) and the tree-row shows an "N cells" badge. Makes it possible to see *what actually diverged* on each path
- **`exptrack storage` reports Session Trees** — adds a Sessions row to the database breakdown and per-column hotspot rows for `session_nodes.cell_source` and `session_nodes.git_diff`
- **Session Trees** — an opt-in layer for exploratory notebook work that records the *shape* of your thinking (checkpoints, branches, scratch cells) as a navigable tree, not a flat log. Drive it from the notebook with new IPython magics: `%exptrack session start "name"` to begin, `%exptrack checkpoint "label"` to mark a stable point (snapshots a per-checkpoint git diff), `%exptrack branch "label"` to declare intent before diverging, `%%scratch` to opt a cell out of all tracking, `%exptrack promote "label"` to link the active experiment to the current node, and `%exptrack session end` to close. Sessions live in two new tables (`sessions`, `session_nodes`) and add a nullable `session_node_id` to `experiments`; standard `%load_ext exptrack` tracking is unchanged when no session is active. New CLI: `exptrack sessions`, `exptrack session show <id|name>` (ASCII tree), `exptrack session nodes <id>`, `exptrack session rm <id>` (preserves linked experiments), `exptrack session note <node_id> "..."`. New dashboard tab toggled from the header (`☰ Sessions`) renders the tree as a vertical node graph with checkpoint/branch/abandoned styles, click-to-inspect (cell source, diff, note), and links to promoted experiments. Stdlib only, no new deps

## [1.8.0] - 2026-05-07

### Added

- **Collapsible study groups in the sidebar AND the main table** — both the left experiments sidebar (via a new "Group by study" toggle next to the search box) and the main experiments table (via a new "Study" button in the Group by row) can now group experiments under their first study, so a study with four runs collapses to a single row instead of dominating the panel. Defaults differ: the **sidebar** starts each study **collapsed** (the busy-rail case is the main reason), while the **main table** starts each study **expanded** like the other groupings (Git Commit / Branch / Status). State persists in localStorage (`exptrack-sidebar-group-study`, `exptrack-expanded-studies`); experiments without a study fall under "(no study)"

## [1.7.4] - 2026-05-06

### Fixed

- **Detail canvas no longer scrolls horizontally and hides content on the left** — reverted `#main-content` to `overflow-x: hidden`. With `overflow: auto`, focusing an input (e.g. the "Add Path" field on the Data Files tab) auto-scrolled the canvas to the right and tucked the start of every line behind the left edge. Now horizontal scroll is opt-in per-element instead of canvas-wide
- **Tab bar wraps to a second row when squeezed** — `.tabs` now `flex-wrap: wrap`, so Timeline / Charts / Images / Data Files / Compare Within / Confusion Matrix flow onto a new row instead of one being shoved past the edge when both sidebars are open
- **Confusion matrix and per-class table scroll inside their own area** — re-added `max-width: 100%; overflow-x: auto` on `#conf-matrix-area` and `#conf-results` only (not on the whole canvas), so a wide NxN grid gets its own scrollbar without anything else on the page being affected

## [1.7.3] - 2026-05-06

### Fixed

- **Wide content (confusion matrix etc.) is reachable instead of clipped** — `#main-content` switched from `overflow-x: hidden` to `overflow-x: auto`. Previously a wide unbreakable element (NxN confusion matrix grid) was being clipped against the canvas edge with no way to see the rest. Now the canvas itself scrolls horizontally when content can't shrink, so nothing is hidden. Removed the inner `overflow-x: auto` wrap on the matrix areas — it was causing the matrix to vanish behind a narrow inner scroll region instead of letting the canvas scroll naturally

## [1.7.2] - 2026-05-06

### Fixed

- **Confusion matrix no longer overflows the canvas** — `#conf-matrix-area` and `#conf-results` (per-class table) now scroll horizontally inside the detail panel instead of pushing past the right edge when both the experiments sidebar and a pinned Todos / Commands panel are open
- **Confusion matrix Compare view stacks based on canvas width** — switched the `.conf-compare-grid` two-column → one-column breakpoint from a viewport `@media` rule to the same `@container main` query used by the rest of the detail layout
- **Detail two-column layout keeps both columns longer** — bumped the `.detail-grid` stack threshold from 760px to 980px (and `.info-grid` from 520px to 600px) so two columns only collapse when the canvas is genuinely too narrow, not while there's still comfortable room

## [1.7.1] - 2026-05-06

### Changed

- **Configurable exports directory** — `exports_dir` (default `"exports"`) is now a config key, matching the `outputs_dir` convention. `api_save_export` reads it from `config.json` instead of hard-coding the folder name
- **`api_save_export` collision fallback** — capped numeric-suffix retries at 999 (down from 9999) and added a microsecond-timestamp fallback after that, so the endpoint never silently fails on a saturated exports directory
- **`saveOrDownload` surfaces server errors** — when the server returns `{error: "..."}`, the dashboard toast now includes the message before falling back to a browser download
- **`setExportToFolder` storage style** — writes `'true'`/`'false'` via `_storageSet` for both states, matching the rest of the dashboard's preference handling instead of using `removeItem` for false

## [1.7.0] - 2026-05-06

### Added

- **Save exports to project folder (no overwrite)** — a new "Save exports to project folder" toggle under Settings → Display routes every download (Todos, Commands, experiment exports, bulk exports) to `<project_root>/exports/` instead of the browser. The server picks a non-conflicting filename by appending `_2`, `_3`, … so existing files are never overwritten. Backed by a new `POST /api/save-export` endpoint and the unified `saveOrDownload(text, filename, mime)` helper in `js/core.py`

### Changed

- **Toolbox tab switches no longer re-fetch from the API** — Todos / Commands are loaded once per session; subsequent tab switches just re-render local state. Mutations still refresh from the server
- **Toolbox resize is RAF-throttled** — drag updates coalesce on `requestAnimationFrame` and a single cached `innerWidth` per drag, eliminating the per-mousemove style invalidation hot loop. Drag also recovers cleanly if focus leaves the window mid-drag
- **Single source of truth for toolbox boot** — pin classes apply synchronously at module load (no FOUC), data loading happens once via `_bootDashboard` after auth clears, removing the previous double-fetch path
- **Shared `downloadBlob` helper** — promoted to `js/core.py`; new toolbox exports and the experiment Compare/Export flow now share it. The new `saveOrDownload` wraps it with the project-folder option

## [1.6.3] - 2026-05-06

### Fixed

- **Experiment-list cards no longer overflow the sidebar** — `.exp-card-name` is now a `flex: 1; min-width: 0` flex item so long names truncate with an ellipsis instead of pushing the card past the 280px sidebar width
- **"edit" / "del" / "view" buttons no longer wrap letter-by-letter** — added `white-space: nowrap` to artifact-action buttons and the notes "edit" overlay so their text stays on one line when the canvas is squeezed by a pinned Todos/Commands panel. The `.artifact-actions` row also wraps to a new line as a whole rather than letting the cell shrink each button
- **Detail layout stacks based on canvas width, not viewport width** — `#main-content` is now a CSS containment context (`container-type: inline-size`), and the two-up `.detail-grid` plus the `.info-grid` label/value pairs collapse to a single column once the canvas itself drops below 760px / 520px. Previously the stacking only triggered on a narrow viewport, so a pinned right panel could squeeze the canvas without ever flipping to single-column
- **Reverted forced equal-width columns on params/metrics tables** — `table-layout: fixed` was distributing the 6 metric columns equally, leaving badge / source cells too narrow. Returned to natural column sizing while keeping `word-break: break-word` so long values still wrap

## [1.6.2] - 2026-05-06

### Fixed

- **Detail overview no longer overflows the main canvas** — `#main-content` now clips horizontal overflow so wide content (long values in info-grid, params, metrics) wraps instead of pushing past the viewport edge when the Todos / Commands panel is pinned. Params and metrics tables use `table-layout: fixed` with `word-break: break-word` so long values wrap in-cell, and info-grid value columns use `minmax(0, 1fr)` so long paths and commit hashes wrap rather than expanding the grid

## [1.6.1] - 2026-05-06

### Added

- **Resizable Todos / Commands panel** — when the toolbox is pinned, drag the divider on its left edge to make the panel narrower or wider (clamped to 260–800px). Width persists across reloads in `localStorage` (`exptrack-toolbox-w`)

### Fixed

- **Pinned panel no longer pushes content off-screen** — the layout shift now uses a CSS variable (`--toolbox-w`) tied to the drawer width, and `body.toolbox-pinned` clips horizontal overflow so resizing the panel correctly reflows the header and main canvas instead of producing a horizontal scrollbar

## [1.6.0] - 2026-05-06

### Added

- **Persistent Todos / Commands side panel** — the toolbox drawer (Todos & Commands) can now be pinned as a persistent right-side panel, mirroring the experiment sidebar on the left. Pin via the new pushpin button in the drawer header or via the new "Pin Todos / Commands panel" checkbox under Settings → Display. When pinned, the drawer stays open across navigation, the page content is shifted to make room, and clicking the Todo / Cmds header buttons just switches tabs instead of toggling. Pin state and last-active tab persist in localStorage (`exptrack-toolbox-pinned`, `exptrack-toolbox-tab`)
- **Export Todos and Commands** — each toolbox panel now has download buttons. Todos export as `.md` (grouped Active / Done with checkboxes), `.txt`, or `.json`. Commands export as `.sh` (runnable script with label / tags / study comments), `.md` (fenced code blocks), or `.json`

## [1.5.1] - 2026-05-06

### Fixed

- **Dark-mode contrast across the dashboard** — added `color-scheme: light` / `color-scheme: dark` to `:root` and `body.dark` so browser-rendered form controls (text inputs, selects, number spinners, scrollbars) flip to dark UA defaults instead of leaving black-on-white text scattered through the UI when dark mode is on
- **Confusion matrix readability in dark mode** — heatmap cells now brighten the palette and use a higher base alpha so low-intensity fills are visible against the dark card background, and any filled cell uses white text in dark mode (instead of switching at 0.55 intensity, which left mid-range cells with low-contrast gray text)

## [1.5.0] - 2026-05-01

### Added

- **Multiple confusion matrices per experiment** — the Confusion Matrix tab now keeps a tab bar of named matrices. "+ New" adds another, double-click a tab to rename, "Duplicate" makes a copy, "Delete" drops one. Each matrix has its own classes, palette, and intensity, so you can keep e.g. "validation", "test", and "after threshold tuning" side-by-side on the same experiment
- **Compare confusion matrices** — once you have ≥2 matrices, a "Compare…" tab opens a side-by-side read-only view with two dropdowns (A and B) and a difference table for accuracy / macro & weighted precision-recall-F1 / total. Δ is colored green for B>A and red for B<A
- **Confusion matrix intensity slider** — new range control (0.3–1.5) in the matrix toolbar lets you lighten or darken the heatmap independently of the color palette, useful when high-count cells are saturating or low-count cells are too pale
- **Confusion matrices persist on the experiment** — matrices now save to the server (as a JSON-encoded manual param `_confusion_matrices`) so they survive across browsers and clean cache, and round-trip with the experiment record. Saves are debounced; legacy localStorage matrices are auto-migrated on first load. New endpoints `GET /api/confusion/<id>` and `POST /api/experiment/<id>/save-confusion`. Saved metrics are prefixed with the matrix name when more than one matrix exists, so saving from each doesn't clobber the previous

### Fixed

- **Sidebar no longer pops back open on every detail refresh** — adding a metric, param, tag, note, or any other in-place mutation kept re-expanding the experiment sidebar even after you collapsed it. The dashboard now only auto-expands the sidebar when transitioning into the detail view (or switching to a different experiment); subsequent refreshes leave the user's collapsed/open choice alone

## [1.4.5] - 2026-04-28

### Changed

- **Confusion matrix class names render in caps** — both the column header inputs and the mirrored row labels apply `text-transform: uppercase` so typing "class 1" displays as "CLASS 1" on both axes (the underlying value is preserved as-typed in storage and exports)
- **Color picker + dark-mode-friendly heatmap** — new "Color" dropdown in the matrix toolbar lets you switch between Blue, Green, Purple, Orange, Teal, and Grey palettes (choice persists in localStorage). The on-screen heatmap now uses an alpha-based fill so empty cells stay transparent against the card background, which fixes the washed-out look in dark mode while keeping the same gradient feel in light mode. The PNG export lerps from white to the chosen accent so it stays clean on a white background

## [1.4.4] - 2026-04-28

### Changed

- **Confusion matrix uses natural casing throughout** — dropped `text-transform: uppercase` from the axis labels ("Predicted" / "Actual"), the row/column "Total" labels, the metric stat labels, and the per-class table header. The PNG export now renders these in the same Title-case form. Domain abbreviations (TP/FP/FN/TN/F1) are kept since that's their conventional spelling

## [1.4.3] - 2026-04-28

### Changed

- **Confusion matrix row labels match column labels** — row class names share the same font, size, padding, and centering as the column-header inputs, so the two axes look like one set of labels rather than two visually distinct fields
- **Confusion matrix PNG export** — new "Export PNG" button rasterizes the matrix (with axis labels, totals, and the Blues heatmap) at 2× scale via SVG → canvas, ready to drop straight into a slide deck or paper

## [1.4.2] - 2026-04-28

### Changed

- **Confusion matrix totals, exports, and palette** — the matrix now grows a "Total" column on the right and a "Total" row at the bottom showing per-row, per-column, and grand-total counts. Cells are shaded with a single sklearn-style Blues gradient (no more red/green) so colorblind viewers and dark-mode users can read it without the traffic-light palette. New buttons export the matrix as **CSV** (download), **Markdown** (clipboard), or **JSON** (clipboard) — labels, row/column totals, and grand total included

## [1.4.1] - 2026-04-28

### Changed

- **Confusion matrix UX polish** — class names are now edited in one place (the column headers) and mirror onto the row headers, so labels stay in sync. Cells auto-fit large counts and drop the +/- spinner (counts can be pasted in directly). The "Actual" axis is rendered as a vertical sidebar that no longer overlaps row labels. A diagonal-green / off-diagonal-red heatmap shades each cell by relative magnitude so big confusions stand out at a glance. Per-class numbers in the results table are formatted with thousands separators

## [1.4.0] - 2026-04-28

### Added

- **Confusion matrix calculator in the dashboard** — every experiment detail view gains a "Confusion Matrix" tab where you punch in raw counts (binary or NxN multi-class) and immediately see accuracy, per-class precision/recall/F1, plus macro and weighted aggregates. Class labels are editable, the matrix size is adjustable up to 20 classes, and "Save as metrics" pushes accuracy and macro/weighted precision/recall/F1 onto the experiment as manual metrics. Matrix state is persisted per-experiment in localStorage so it survives reloads
- **Multi-line notes** — pressing Enter inside the inline notes editor now produces a real visual line break in the rendered notes; the detail view honors `\n` via `white-space: pre-wrap` so paragraphs read the way you typed them

## [1.3.0] - 2026-04-28

### Added

- **Editable manual params in the dashboard** — params now carry a `source` ('auto' or 'manual') alongside their value. Auto params (captured from the script via argparse/argv) are read-only with an "auto" badge; manual params (created via the New Experiment modal or the per-experiment "+ Add Param" form) get a "manual" badge and full inline-edit support: double-click the key to rename, double-click the value to edit, click `×` to delete. New endpoints: `/api/experiment/<id>/{add-param,edit-param,delete-param,rename-param}`
- **Per-experiment "+ Add Param" form** — every experiment detail view (auto or manual) gains a small form below the params table for attaching extra manual params after the run. Refuses to overwrite any existing key — to update a value, double-click to edit; to swap an auto key, pick a different name. Values are JSON-decoded when possible (so `50` stays a number, `true` stays a boolean) and fall back to a plain string otherwise

### Changed

- **`params` table now has a `source` column** — automatic ALTER TABLE migration on first run. Backfill marks params on manually-created experiments (those with NULL `hostname`/`python_ver`) as `manual`; everything else stays `auto`. Existing reads via `get_experiment_detail` are unchanged in shape; a new sibling `param_sources` map exposes per-key origin to the dashboard

## [1.2.0] - 2026-04-21

### Added

- **Auto-generated dashboard token** — `exptrack ui` now generates a per-session URL-safe token (`secrets.token_urlsafe`) when none is configured and prints a Jupyter-style URL with the token embedded. The token lives only in process memory: never persisted to `.exptrack/config.json`, never exported to the environment, so it can't leak to child processes. A fresh token is rolled on every restart. `--token` and `EXPTRACK_DASHBOARD_TOKEN` still take precedence when set
- **Jupyter-style login flow in the dashboard** — visiting with the token in the URL now stashes it in `localStorage` and strips it from the address bar (no more token in browser history), subsequent API calls send `Authorization: Bearer <token>` instead of a query param, and if the token is missing or rejected a modal login overlay appears with a token input. Bookmarking the bare `http://127.0.0.1:7331/` now just works across refreshes
- **`--no-auth` flag for `exptrack ui`** — opt out of the auto-generated token for fully-trusted local sessions
- **`exptrack ui-stop --port N`** — kill a dashboard process still holding a port (useful after a parent shell died without propagating SIGHUP, or you lost the auto-generated token in a different terminal). Uses `fuser` (Linux) with an `lsof` fallback (macOS/BSD)
- **EADDRINUSE hint** — `exptrack ui` now prints a helpful message pointing at `ui-stop` and `lsof -i :PORT` when the port is already taken

## [1.1.0] - 2026-04-20

### Added

- **Params-only export (CLI)** — new `exptrack export <id> --format` values that emit just the parameters: `params` (`key=value` lines, shell-friendly), `params-flags` (`--key value` CLI flags, with bare `--flag` for booleans), `params-json` (JSON object), `params-md` (markdown table, pastes into lab notebooks), and `params-tsv` (tab-separated, pastes into spreadsheets). Also available via `/api/export/<id>?format=<name>`
- **Params "Copy" button on the dashboard** — the detail view's Params section header now has a one-click Copy button (next to the section like the Reproduce box's Copy). Copies the parameters as a markdown table for direct paste into lab notebooks, Obsidian, GitHub, or Jupyter markdown cells. The main Export ▼ / Copy ▼ dropdowns remain unchanged (whole-experiment only)

### Changed

- **Artifacts list is truncated for runs with >50 artifacts** — the detail view now shows the first 50 artifacts with a "Show all N" expand button. Prevents the page from becoming unreadable on runs that produce hundreds of outputs
- **Artifacts filter** — a filter input appears above the artifact list when a run has more than 10 artifacts, so users can quickly locate a specific file by label or path. Typing into the filter also auto-expands any truncated rows

### Fixed

- **Duplicate `batch-size` / `batch_size` params** — scripts using argparse with dashed long flags (e.g. `--batch-size`) previously produced two keys in their params: the dashed form from the raw `sys.argv` fallback and the underscored form from argparse's Namespace. The fallback now normalizes dashes to underscores on capture, matching argparse's convention, so only one key lands in the params store

## [1.0.1] - 2026-03-27

### Added

- **Experiment resume** — `Experiment.resume(exp_id)` reopens a finished/failed experiment. Metrics, artifacts, and params aggregate into the same run. A `resume` timeline event records the command that triggered it
- **Auto-resume detection** — `exptrack run` auto-detects `--resume` (or flags listed in `resume_flags` config) from the script's own argv and resumes the latest experiment for that script. No extra flags needed
- **Shell pipeline resume** — `exptrack run-start --resume [EXP_ID]` resumes from shell scripts and SLURM jobs
- **Resume example** — `examples/resume_training.py` demonstrates first run + resume with metrics aggregation
- **Output auto-detection** — after a script finishes, new files (models, images, data) are scanned from the working directory and registered as artifacts. Recognizes `.pt`, `.pth`, `.ckpt`, `.safetensors`, `.h5`, `.onnx`, `.pkl`, and other ML file types

### Fixed

- **Model checkpoints not saved on resume** — argparse recapture was renaming the experiment's output directory mid-run, causing scripts to write to a stale path. Resumed experiments now preserve their original name and output directory
- **Model checkpoints not detected** — the `outputs/` directory was incorrectly skipped during auto-detection, so files saved there by the user's script were never registered
- **Artifact protection breaking resume** — `protect_previous_artifacts` was moving checkpoint files before the script started, breaking resume workflows that need to load from the same path. Removed entirely — artifacts are now tracked by reference only (path + hash), exptrack never copies or moves user files

### Removed

- **`protect_on_rerun` config option** — artifact protection removed. The deduplication set in auto-detect already prevents double-logging without needing to copy files
- **`artifact_protection.py` module** — no longer needed

## [1.0.0] - 2026-03-26

Initial public release.

### Core

- **Zero-friction tracking** — wrap any script with `exptrack run train.py --lr 0.01` and parameters, git state, and artifacts are captured automatically. No code changes required
- **Four integration modes**: CLI wrapper (`exptrack run`), Jupyter (`%load_ext exptrack`), shell/SLURM pipelines (`run-start`/`run-finish`), and Python API (`Experiment` context manager)
- **Argparse capture** — monkey-patches `parse_args()` and `parse_known_args()` with `sys.argv` fallback for non-argparse scripts
- **Matplotlib capture** — `plt.savefig()` and `Figure.savefig()` calls auto-register artifacts. Figures saved before experiment creation are buffered
- **Git state** — branch, commit hash, and diff against HEAD stored with every run
- **SQLite storage** (WAL mode) with 7 tables. No external dependencies — stdlib only
- **Plugin system** with 4 lifecycle hooks and a built-in GitHub Sync plugin

### Jupyter Notebooks

- Cell execution timeline with sequence numbers for full execution order reconstruction
- Content-addressed cell lineage (SHA-256 hashing, parent discovery via similarity matching)
- Variable fingerprinting with automatic hyperparameter detection (`lr`, `batch_size`, etc.)
- Code diffs between runs — stores only diffs, not full source copies

### Shell / SLURM Pipelines

- `run-start` / `run-finish` / `run-fail` commands with `eval $()` integration
- `log-metric` and `log-artifact` for logging from shell scripts
- Multi-step pipelines with `--study` and `--stage` flags
- Study/stage inheritance via environment variables across scripts
- SLURM environment variables captured automatically

### Web Dashboard (`exptrack ui`)

- Experiment list with status filters, search, sparkline charts, and customizable columns (resize, show/hide)
- Detail view with parameters, metrics, interactive charts (linear/log scale, zoom, downsampling), code changes, and git diff
- Reproduce command box with one-click copy and Save-to-Commands
- Compare experiments: side-by-side with overlay charts (2 runs) or bar charts (3+ runs)
- Image gallery with lightbox and side-by-side/overlay/swipe comparison
- Data file rendering: CSV, TSV, JSON, and JSONL displayed as interactive sortable tables
- Timeline view with cell executions, variable changes, and artifact creation
- Toolbox panel with commands notepad and todo list
- Manual experiment creation modal
- Studies and stages with highlight mode, filtering, and inline editing
- Inline editing for names, tags, notes, studies, and stages (double-click)
- Tag autocomplete, searchable filter dropdowns, bulk operations
- Timezone selector, dark mode
- Export to JSON, Markdown, CSV, TSV, and Plain Text
- Optional authentication via `EXPTRACK_DASHBOARD_TOKEN` or config

### CLI (24 commands)

- **Tracking**: `init`, `run`, `create`, `finish`
- **Pipelines**: `run-start`, `run-finish`, `run-fail`, `log-metric`, `log-artifact`
- **Inspect**: `ls`, `show`, `diff`, `compare`, `history`, `timeline`, `export`, `verify`
- **Organize**: `tag`, `untag`, `delete-tag`, `note`, `edit-note`, `study`, `unstudy`, `stage`
- **Maintain**: `rm`, `clean`, `stale`, `compact`, `backup`, `restore`, `storage`, `upgrade`
- Export supports JSON, Markdown, CSV, and TSV formats with `--all` for bulk export

### Configuration

- Per-project config via `.exptrack/config.json`
- Metric thinning: write-time (`metric_keep_every`) and read-time (min-max bucketing via `metric_max_points`)
- Artifact strategy, git diff size limits, naming conventions, auto-capture toggles
- Non-finite metric values (NaN, Inf) silently dropped

[1.11.0]: https://github.com/mikylab/exptrack/compare/v1.10.1...v1.11.0
[1.10.1]: https://github.com/mikylab/exptrack/compare/v1.10.0...v1.10.1
[1.10.0]: https://github.com/mikylab/exptrack/compare/v1.9.2...v1.10.0
[1.9.2]: https://github.com/mikylab/exptrack/compare/v1.9.1...v1.9.2
[1.9.1]: https://github.com/mikylab/exptrack/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/mikylab/exptrack/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/mikylab/exptrack/compare/v1.7.4...v1.8.0
[1.7.4]: https://github.com/mikylab/exptrack/compare/v1.7.3...v1.7.4
[1.7.3]: https://github.com/mikylab/exptrack/compare/v1.7.2...v1.7.3
[1.7.2]: https://github.com/mikylab/exptrack/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/mikylab/exptrack/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/mikylab/exptrack/compare/v1.6.3...v1.7.0
[1.6.3]: https://github.com/mikylab/exptrack/compare/v1.6.2...v1.6.3
[1.6.2]: https://github.com/mikylab/exptrack/compare/v1.6.1...v1.6.2
[1.6.1]: https://github.com/mikylab/exptrack/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/mikylab/exptrack/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/mikylab/exptrack/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/mikylab/exptrack/compare/v1.4.5...v1.5.0
[1.4.5]: https://github.com/mikylab/exptrack/compare/v1.4.4...v1.4.5
[1.4.4]: https://github.com/mikylab/exptrack/compare/v1.4.3...v1.4.4
[1.4.3]: https://github.com/mikylab/exptrack/compare/v1.4.2...v1.4.3
[1.4.2]: https://github.com/mikylab/exptrack/compare/v1.4.1...v1.4.2
[1.4.1]: https://github.com/mikylab/exptrack/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/mikylab/exptrack/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/mikylab/exptrack/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/mikylab/exptrack/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/mikylab/exptrack/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/mikylab/exptrack/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mikylab/exptrack/releases/tag/v1.0.0
