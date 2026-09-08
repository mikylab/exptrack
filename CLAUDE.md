# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

**This file is the index, not the manual.** It is loaded into context on every
session, so it carries only what is needed to *orient* — the map, the rules, and
one line per design pattern. The reasoning behind each pattern (what was tried,
what broke, why the code is shaped the way it is) lives in `docs/design/`, and is
read on demand. **Before changing a subsystem, read its pattern file.** Those
files are where the non-obvious constraints are; the one-liners here are only
enough to tell you which one you need.

## Project Overview

**exptrack** is a local-first, zero-friction Python experiment tracker for ML
workflows. It automatically captures parameters, metrics, and git state by
monkey-patching argparse and IPython hooks — no code changes required in user
scripts. SQLite (WAL mode) for storage, **stdlib only**, no external
dependencies.

## Installation

```bash
pip install -e .            # console script `exptrack` -> exptrack.cli:main
pip install -e ".[dev]"     # + pytest, ruff
```

## Testing & Linting

CI is the authoritative gate (6 Python versions + both linters + an
integration-skip guard). The local pre-check block below runs the same things in
order — use it before committing. `python tests/smoke.py` is a 30-second real
end-to-end sanity check; `python tests/release_check.py` guards a release.
Solo-maintainer guidance (including working with Claude in a browser) lives in
`MAINTENANCE.md`.

```bash
pip install -e ".[dev,integrations]"     # matplotlib/numpy/pandas — capture tests
                                         # SKIP without these; CI fails on skips
python -m pytest tests/ -x -q            # the suite (drop -x for the full run)
python tests/run_all.py                  # legacy per-file runner, also in CI
ruff check .                             # enforced in CI
npx eslint exptrack/dashboard/static/js  # enforced in CI
```

`tests/run_all.py` (the legacy runner, also in CI) executes each test file as a
script, so it needs exptrack actually installed (`pip install -e .`, not just
pytest's `pythonpath`) — otherwise every file fails on `ModuleNotFoundError`,
which looks alarming and means nothing.

Orientation: `test_experiment.py`, `test_cli.py`, `test_db.py`,
`test_pipeline_shell.py` (shell/SLURM), `test_capture_argparse.py`,
`test_dashboard_routing.py` (GET dispatch + ordering guards),
`test_dashboard_headers.py` and `test_dashboard_concurrency.py` (both over a
real socket), `test_dashboard_js_integrity.py` (static JS contracts).

## Running

```bash
exptrack init [project_name]              # creates .exptrack/, patches .gitignore
exptrack run train.py --lr 0.01           # wrap any training script

eval $(exptrack run-start --lr 0.01)      # shell/SLURM pipeline
exptrack run-finish $EXP_ID --metrics results.json
exptrack run-fail $EXP_ID "reason"

exptrack run train.py --resume            # auto-detected; aggregates into one run
```

Notebooks: `%load_ext exptrack`. Session Trees are opt-in and no-op until
`%exptrack session start`.

Full command + notebook-magic quick reference (multi-step pipelines, every
`%exptrack` magic, `%exp_log`, `variant-of`, `primary-metric`):
**`docs/design/usage.md`**.

The authoritative command list is `cli/main.py:_DISPATCH`. **Don't quote a
command count in docs** — it has drifted twice. User-facing docs live in
`docs/cli-reference.md` and `docs/session-trees.md`.

## Architecture

Condensed map. Full module-by-module detail with rationale:
**`docs/design/architecture.md`**.

```
exptrack/
  __init__.py               Exports Experiment, load_ipython_extension
  __main__.py               `python -m exptrack` / `exptrack run` — wraps scripts via
                              runpy, publishes the adoptable run wrapper, auto-resume
  config.py                 .exptrack/config.json, project-root detection, gitignore
                              rules, dashboard-token location + writer
  notebook.py               %load_ext exptrack magics + explicit API
  core/
    experiment.py           Experiment class: lifecycle, param/metric/artifact logging
    db.py                   SQLite schema (10 tables), migrations, WAL, blob refcounting
    queries.py              Read-side query layer for CLI + dashboard
    utils.py                Shared safety helpers, param-namespace primitives, json_dumps
    reference.py            The run everything else is measured against
    param_study.py          Reading a set of runs as a parameter search + duplicates
    leaderboard.py          top_runs / best_so_far / pareto_front (views over build_matrix)
    primary_metric.py       Which metric a run is judged by (4-level resolution)
    metric_alias.py         One canonical name per measurement (metric_aliases config)
    naming.py               Run-name generation + looks_auto_named
    hashing.py              File integrity hashing (SHA-256, partial for large files)
    dataset.py              Dataset/input versioning -> _dataset_manifest param
    script_snapshot.py      Content-addressed script source + git diff (memoized)
    storage.py              Storage measurement, metric prune, diff compaction
    trash.py                Unified-trash aggregation (experiments + sessions + nodes)
    git.py                  Branch/commit/diff capture; non-interactive, never blocks
  capture/
    argparse_patch.py       Patches parse_args/parse_known_args + raw argv fallback
    matplotlib_patch.py     Patches savefig -> artifacts (+ session node images)
    tensorboard_patch.py    Mirrors SummaryWriter scalars into the metrics table
    notebook_hooks.py       pre/post_run_cell: stdout capture, lineage, var diffing
    session_hooks.py        Session Trees magics (%exptrack ..., %%scratch, %%setup)
    cell_lineage.py         Content-addressed cell tracking (SHA-256, 30% similarity)
    variables.py            Variable fingerprinting, HP detection, assignment extraction
    script_tracking.py      Back-compat shim -> core/script_snapshot.py
    dataset.py              Back-compat shim -> core/dataset.py
  cli/
    main.py                 Thin dispatcher: _build_parser() + _DISPATCH map
    pipeline_cmds.py        run-start, run-finish, run-fail, log-metric, log-artifact
    inspect_cmds.py         ls, show, diff, compare (N-way), top, vs-reference,
                              history, timeline, export, verify, source, watch
    mutate_cmds.py          tag, note, rm, trash, restore-run, finish, clean
    admin_cmds.py           stale, upgrade, storage, prune, compact, notebook-guard
    session_cmds.py         sessions, session show|nodes|rm|finalize|...
    help_cmds.py            examples (bundled, listable/printable/copyable), docs (open in browser)
    formatting.py           ANSI colour helpers + die(msg, code) — the exit-code contract
  sessions/                 (split from the former ~1750-line manager.py)
    _shared.py              Cross-cutting layer: singleton, node-diff storage, helpers
    manager.py              SessionManager + build_tree; also the back-compat facade
    lifecycle.py            delete/restore/purge/finalize for sessions and nodes
    materialize.py          Node -> standalone experiment
    tree.py                 ASCII + JSON renderers, list_sessions, find_session
  examples/                 Runnable examples bundled in the wheel; served by `exptrack examples`
  plugins/
    __init__.py             Plugin base, event registry, make_exp_proxy()
    github_sync.py          Sync run metadata to a GitHub repo as JSONL
  dashboard/
    app.py                  DashboardServer (ThreadingHTTPServer), port 7331
    handler.py              Request handler, table-driven GET dispatch, security headers
    static.py               Assembles DASHBOARD_HTML + the JS/CSS bundles
    static/{js,css}/        THE ACTUAL JS/CSS CONTENT — edit these files
    static_parts/           Loader shims (~3 lines each) + html.py; see below
    vendor/                 Vendored Chart.js (no CDN)
    routes/read_routes.py   GET endpoints
    routes/write_routes/    POST endpoints, 11 submodules + _shared.py
```

### Dashboard JS/CSS — where to edit

The JS/CSS lives in **real files** under `exptrack/dashboard/static/{js,css}/`
(24 JS, 18 CSS) so it works with JS tooling. The `static_parts/{js,css}/*.py`
modules are thin loader shims that bind each file to its `JS_*`/`CSS_*`
constant. **Edit the `.js`/`.css` file, never the `.py` shim.**

`static.py` assembles the bundles; `DASHBOARD_HTML` references them as
hash-versioned external `<link>`/`<script>` so the browser caches ~600 KB
instead of re-inlining it per load. Static files ship via `pyproject.toml`
`package-data` + `MANIFEST.in`. Per-module breakdown:
`docs/design/architecture.md`.

Adding a `write_routes` endpoint: add it to its submodule **and** to `__all__`
— `tests/test_dashboard_routing.py` fails if `handler.py` references a name the
package doesn't export. Cross-package imports there are **absolute**; most are
function-local, so a wrong relative depth fails at *call* time, not import time.

## Key Design Patterns — index

One line each: the rule, and where the reasoning lives. **Read the pattern file
before changing the subsystem.** Detail is grouped by what you'd be editing, so
one Read usually covers a task.

### Which file to read, by what you're touching

| Editing | Read first |
|---|---|
| `core/experiment.py`, `__main__.py`, `core/script_snapshot.py` | `run-loop.md` |
| `core/param_study.py`, `leaderboard.py`, `primary_metric.py`, `reference.py` | `analysis.md` |
| `capture/*` , `notebook.py` | `capture.md` |
| metric logging, `get_metrics_series`, `js/charts.js` | `metrics.md` |
| `core/storage.py`, `core/trash.py`, delete/clean paths | `storage.md` |
| `sessions/*`, `capture/session_hooks.py`, `js/sessions.js` | `sessions.md` |
| `js/sidebar.js` view switching, anything feeding Compare | `dashboard-views.md` |
| `js/table.js`, `experiments.js`, `detail.js`, `inline_edit.js` | `dashboard-ui.md` |
| `css/reset.css`, `js/highlight.js`, `js/timeline.js` | `dashboard-render.md` |
| `dashboard/handler.py`, `app.py`, `routes/*` | `server.md` |
| `core/db.py` schema changes | `docs/design/schema.md` + bump `_SCHEMA_VERSION` |
| `core/metric_alias.py`, anything matching metric keys | `analysis.md` |

(All under `docs/design/patterns/` unless a full path is given.)

### `docs/design/patterns/run-loop.md` — the change-one-line-and-rerun loop
- **Run-vs-run loop**: broken runs self-identify; every run reports its delta vs the previous run of the same script; every run stays re-runnable. `_BASELINE_WHERE` is the one rule for what can be a baseline (trashed and `running` excluded, `failed` **kept**).
- **A code-change summary must not hide the change**: `summarize_changed_lines` is the one implementation; truncation is always *stated*; one merged "Uncommitted changes" panel, and its three empty states are not interchangeable.
- **Logging the numbers after the run is over**: `%exp_log` / `log_last()` attaches metrics post-hoc to this notebook's latest surviving run, always printing which run it chose.
- **A run can name its own baseline (`variant_of`)**: an explicit target beats chronology in *both* resolvers; a stale link degrades to chronological.
- **Run adoption**: `exptrack run` publishes its wrapper so a script's own bare `Experiment()` adopts it instead of spawning a phantom second run. Only a *bare* construction adopts, and only once.
- **A run's code is the script *plus* the modules it imported**: `capture_module_snapshots` records the project-local modules `sys.modules` shows at finish, so editing `script.py` and rerunning `main.py` reads as a code change instead of "no code change"; bounded by `snapshot_max_files`, never the tracker's own package or a vendored path.
- **Every run snapshots its own source, however it was started**: `Experiment._maybe_snapshot_script` is the single entry point, so plain `python train.py` captures source too — and `_install_capture_patches` arms argparse/savefig/TensorBoard capture there as well. Raw-argv capture only fires when `sys.argv[0]` is the run's own script.
- **Every way a run can end is an outcome**: Ctrl-C is recorded (`failed` + `_interrupted`, exit 130), never left `running`. A run's `script` is its identity and must not vary with its inputs.
- **The mtime window is not ownership, and ownership expires with the run**: the finish-time output scan skips files owned by a run still *in flight* (`runs_in_flight_since`), so concurrent launches don't cross-contaminate — while a rerun still records the fixed path it overwrote, which is what keeps the delete's file-claim rule able to see a second claimant.
- **"What changed" card**: auto-diffs this run against the previous run of the same script — params, metrics, and a lazily-fetched code diff.

### `docs/design/patterns/analysis.md` — reading a set of runs
- **What varies is a property of the set**: `param_study` works over an explicit id list, not a stored grouping. A missing param is a *variation*, not a blank; values compare after normalization; internal `_`-prefixed params never surface.
- **Ranking a search**: `leaderboard` is entirely views over `build_matrix`, so no ranking surface can disagree with the matrix's own best row.
- **Descriptive means descriptive**: confounded parameters are **not charted at all**; single-run-per-value is marked; unscored runs are counted separately. The effect chart spaces a few distinct values evenly (a sweep is multiplicative, not linear), states its finding in a sentence, and reports a tie as a tie. Ticking a run highlights it across every effect chart (point → run was the only direction, and the harder one); clicking a point identifies it in place rather than navigating away.
- **Three answers to "I already ran this"**: identical rerun / same params+different code / same params+different data lead to opposite actions and are never collapsed into one flag.
- **One primary metric, four levels**: run → study → project → heuristic. A configured metric is **never silently substituted**, and every answer states its `source`.
- **One name for one measurement**: `metric_aliases` maps a canonical metric name to the spellings that mean it, so two models naming a metric differently still compare. Canonicalization is display-level (storage keeps what the run logged) and every merge is reported.
- **Duplicate detection has a model dimension**: `script_differs` outranks the code and dataset verdicts — two models sharing a configuration are not a repeat.
- **Two objectives, and the honesty a frontier needs**: both Pareto axes are caller-named, goals are stated and switchable, and a run missing either metric is reported as unplaceable.
- **A pinned reference is a target, not a lineage**: resolution stops at the project level and never falls through to an implicit substitute; a broken reference is stated, not silently absent. `exptrack vs-reference` reads the whole set against it.

### `docs/design/patterns/capture.md` — getting data in without user code changes
- **Zero-friction capture**, **diff-only storage**, **content-addressed cell lineage** (magic-only cells excluded), **auto artifact linking**, **auto output detection**, **auto-resume detection**, **no-copy artifact tracking**, **dataset/input versioning**, **failure capture** (traceback, not just a message), **TensorBoard metric auto-capture** (the only auto-capture path for metrics), **notebook cell output capture**, param/metric **source tracking**, plugin system, per-project storage.

### `docs/design/patterns/metrics.md` — the only code inside the user's inner loop
- **Metric thinning**: count points, **never** test the step value (`step % N` silently stored *zero* points at common cadences). `metric_keep_every` is a divisor, not a budget — finish states points stored vs logged.
- **Metric write cost at loop scale**: a commit is an fsync. Time-windowed batching via `metric_commit_interval_ms`; never wrap metric writes in `with get_db()` — sqlite3's context manager commits on exit and defeats batching.
- **Charts must render faster than the poll that refreshes them**: bucketing runs in SQL; `/api/metrics` is polled every 5s on live runs.
- **A chart has to leave the page**: `_chartsSheetCanvas` composites *Show All* into one captioned image (opaque, at the canvases' own pixel size), and `⧉ Copy` puts it on the clipboard — stating why when the context is not secure enough to allow it.

### `docs/design/patterns/storage.md` — bytes, deletion and reclaim
- **Knowing where the bytes went**: per-table figures are *exact* (dbstat); anything below a table is apportioned and labelled **estimated**.
- **Reclaiming metric resolution (prune)**: first, last, min and max always survive; preview and delete share one selection function.
- **Exports are summaries, `--full` is the way back**: every format, JSON included; truncation is always reported.
- **A delete that reclaims nothing visible is indistinguishable from one that failed**: every delete reports what it freed and names `clean --vacuum`.
- **Reclaiming storage without losing data**: DB rows are bookkeeping and sweep freely; content-addressed blobs are refcounted; **files are opt-in and always go to the OS Trash**, never `rmtree`. One shared reset list, one ownership rule for output dirs.
- **A file another run still references is not this delete's to remove**: `artifact_claims_by_others` is the file-level half of the claim rule the directory helpers already applied; the preview marks it `shared`, names every holder and excludes its bytes.
- **A shared file is a question, not a rule**: `delete_shared_files` is a *second* answer, defaulting to keep — `exptrack rm` prompts (`--shared-files keep|delete`), the dashboard confirms show the list with an unticked box, and `--yes` never answers it. A file whose mtime is newer than the run's end (`file_modified_after_run`) counts as shared too, which is how pre-fix runs with no second row are covered.
- **The claim is editable**: `exptrack unlink-artifact` drops an artifact record without touching the file, `log-artifact` adds one — the manual override for a claim that protects the wrong file or none at all. The dashboard's Artifacts row carries the same action (**unlink**) plus an **also in N runs** badge (`linked_by`), and the delete confirm offers *Unlink and delete this experiment* / *Delete both* rather than a tick-box.
- **Deleted files stay restorable**: `_trash_or_local` is the only way exptrack removes a file.
- **Soft-delete (Trash) with an explicit permanent path**: `deleted_at` marks trashed; every list filters it; single-run lookups deliberately do not. Reachable from the CLI too (`rm --trash`, `trash`, `restore-run`).
- **One confirmation prompt**: `cli/formatting.confirm` — EOF/Ctrl-C is a refusal, `--yes` is the scripted path. An id prefix is user input, so its LIKE wildcards are escaped.

### `docs/design/patterns/sessions.md` — Session Trees
- **Session Trees**: the opt-in exploratory tree — checkpoints, branches, `%%scratch`/`%%setup`, promote/materialize, the git-graph rail, node trash. **Every magic is idempotent under a Run-All** — this is the constraint most changes here break.
- **Per-branch metric attribution**: tag at write time (`metrics.session_node_id`), never infer from timestamps afterwards.
- **A trashed thing that's still reachable must say it's trashed**.
- **Run-All idempotency covers the paths that don't look like cells**: `%%setup`-first branches, promote-then-rerun, and `session end`.
- **A session is active per kernel, not per run**: only metrics of a run the session owns get tagged.

### `docs/design/patterns/dashboard-views.md` — views and selection *(read before touching Compare)*
- **One canvas, one way to take it**: `releaseCanvas()` is the single teardown; every view switcher calls it first. Two views suppress their neighbours with CSS `!important`, so a partial teardown makes a button silently do nothing.
- **A selection belongs to the surface that owns it**: table, matrix and session tree keep separate sets and share only the destination (`compareRuns(ids)`). A selection must not outlive the set it was made in. **Clearing the picks clears the comparison they produced** (`_discardComparison`, token bump included); dismissing a result does *not* clear the picks.
- **Searchable Compare pickers**: one cached run list feeds all three pickers; a partial cache always renders a truncation notice.
- **One way to answer "which runs?"**: `openRunPicker` (js/run_picker.js) is the shared picker for Compare and the matrix's analysed set — rows carry each run's parameters and the search matches them, so a run is reachable without knowing its name. It reads the Compare cache, so no two surfaces can search different sets.
- **A run list must be narrowable without knowing what to type**: the picker's facet chips (`_rpFacetGroups`) are values the runs actually hold — OR inside a group, AND across groups, each count saying what clicking it would leave. `_rpFiltered` is the single answer to "what is listed"; picks and filters clear separately.
- **Leaving a view is as reachable as entering it**: Compare's Back returns to its `_compareOrigin`; `_pushViewHash`/`_onPopView` (js/sidebar.js) give `#matrix` and `#compare=` a history position so the browser's Back steps back a view instead of leaving the page; and **Compare n here** renders the comparison inside the matrix so the common case needs no navigation.
- **Pairing two runs' images is a claim**: `_assign_image_groups` decides it server-side — an exact shared filename wins, else a digit-normalized family, and never a merge that would hide a run's second image; two runs on one path are marked `shared`, because the file has one content.
- **A comparison column must keep the end of a run name**: auto-generated names differ in their tail — every compare surface uses `midEllipsis`, never a head truncation.

### `docs/design/patterns/dashboard-ui.md` — the list and detail view
- **Scannable experiment table at scale**: `param:<key>` columns, empty-column collapse, middle-ellipsis names.
- **Polarity-aware metric deltas**: green means *better*, not bigger.
- **Failures are visible, never a silently blank view**: `_json_list` server-side, `_showApiError` client-side; `api()` can return `null`, so every caller guards.
- **A live run's detail view keeps the view state you set**: the 5s poll must not reset the tab, scroll, chart picker or axis inputs; charts update **in place**.
- **The page scroller clamps when content shrinks**: `_holdMainScroll()` (js/core.js) is the one helper; an image grid inside `#main-content` must reserve its boxes (`aspect-ratio`) or a dropped decode moves the reader to the top.
- **A selection change repaints in place**: a handler that changes what is *selected* must not call the loader. Compare Within (`_cwRepaintSelection`) and the Images tab's compare picks (`_imgCmpRepaint`) both rebuilt their whole tab for a badge, collapsing `#main-content` so the browser clamped the scroll to the top.
- **Export and copy are one answer at two distances**: `copyDiff` puts the same server-rendered markdown `exportDiff` downloads on the clipboard; every Export site has a Copy beside it.
- **Inline editing**: exactly one cell editor open at a time; closing commits; the editor is an anchored panel, not laid out in the cell.
- **A saved command is a template, and the template is never rewritten**: `{{var}}` tokens render editable inputs; substitution happens at render, an unfilled token stays visible, and date-like variables re-default rather than persist.
- **A bulk action counts what it can act on**: `Finish (n)` counts only the *running* runs in the selection and is absent when there are none; the result separates finished / already-done / failed.
- Plus: collapsible groups, filmstrip, date grouping, pagination + debounce, timezone display, auto-named runs.

### `docs/design/patterns/dashboard-render.md` — look and code display
- **Centralized design tokens**: `css/reset.py` is the single source of truth. **Any alias whose value is `var(--other)` must be redeclared in both `:root` and `body.dark`** — this regressed once into white cards on a dark page. No webfont, no CDN.
- **A class the markup uses and no rule matches renders as an OS default**: `.btn-sm`/`.btn-ghost` were styled nowhere; a full-canvas view title must use the shared header shell, not a bare `<h2>` (which inherits the in-view section-heading treatment).
- **Legible Timeline event taxonomy**: one `evMeta` map drives filter bar, chips, tooltips and legend.
- **Shared code rendering**: `_highlightPy` + word-level diff renderer, used by Sessions and the experiment view. Inside a diff, colour means only added/removed.

### `docs/design/patterns/server.md` — HTTP and file serving
- **Concurrent request serving**: `ThreadingHTTPServer` is a *correctness* requirement — one idle pooled socket deadlocked the whole dashboard through a tunnel. Never run a blocking WAL checkpoint on a request path.
- **Table-driven GET dispatch**: ordering hazards become data, not control flow. A **set-valued** request is a POST even when it is a read (`/api/param-study`, `/api/multi-compare`).
- **Typed request bodies + a real error boundary**: use `body_str()`, never `.strip()` a raw body value; the boundary lives in `handle_one_request`.
- **JSON we emit must be JSON anyone can parse**: `core/utils.json_dumps` — `Infinity`/`NaN` are not parseable JSON and break the *whole* document for `JSON.parse`.
- **A stale token degrades the page, never locks it**: `exptrack ui` mints a token per session, so a restart 401s an open tab — the login overlay is dismissible, names the cause, and reloads on success.
- **Response hardening**: three CSP policies; the `/api/file/` sandbox is load-bearing because SVG is a live document.
- **Serving a user file must not cost the size of that file**: stream it, window the text, state the truncation.
- **Keep-alive and the undrained-body hazard**: a response written without draining the body must close the connection.
- **Secrets stay out of the committable config**: `config.json` is documented as safe to commit, so the dashboard token lives in `.exptrack/dashboard_token`.
- Plus: scan-path editing, suggestions, and bounded listing (`readable_project_path` is the one containment rule).

## Database Schema

SQLite WAL mode, 10 tables. Full column-level detail with rationale:
**`docs/design/schema.md`**.

- **`experiments`** — run metadata. Notable: `command` (real launch command),
  `session_node_id`, `deleted_at` (soft delete), `name_is_auto`
- **`params`** — key/value JSON, `source` = auto|manual
- **`metrics`** — value, step, ts, `source`, `session_node_id`
- **`artifacts`** — output files by reference (path + hash), never copied
- **`timeline`** — ordered execution events (seq, event_type, cell_hash, source_diff)
- **`cell_lineage`** — content-addressed cell history (cell_hash PK, parent_hash)
- **`code_baselines`** — position-based cell baselines
- **`code_snapshots`** — content-addressed script source (hash PK), refcounted
- **`sessions`** / **`session_nodes`** — Session Trees, both soft-deletable

Indexed on: metrics(exp_id, key), params(exp_id), artifacts(exp_id),
timeline(exp_id, seq), experiments(created_at, status), plus the `deleted_at`
indexes.

**Bump `_SCHEMA_VERSION` by +1 with any schema change** (new table/column/index
or migration helper) or existing DBs never see it. New indexes on migrated
columns go in the `_migrate_*` helper, never in `_create_base_schema` — the base
script runs first, and one failed statement aborts the whole script, breaking
every install on upgrade.

## Configuration

`.exptrack/config.json` — defaults and per-key meaning: **`docs/design/config.md`**.

Frequently relevant: `metric_keep_every`, `metric_max_points`,
`metric_commit_interval_ms` (250), `max_git_diff_kb` (256), `snapshot_max_kb`
(512), `snapshot_max_files` (50), `code_change_max_chars` (20000), `var_fingerprint_max_mb` (100),
`primary_metric` / `_by_study`, `reference_run` / `_by_study`,
`warn_duplicate_runs`, `auto_trash_failed`, `auto_capture.*`, `naming.*`.

An unusable value must always degrade to the documented default — a hand-edited
config must never be the reason a run records nothing.

**Before adding a setting, ask whether it's a secret.** `config.json` is
committable.

## Coding Best Practices

- **stdlib only** — every import in the package must come from the standard
  library. (Dev tooling — pytest, ruff, eslint — is exempt.)
- **Keep functions focused.** Past ~40 lines, consider splitting.
- **Reuse existing utilities** before writing new ones: `core/db.py` (`get_db`,
  `_find_exp`), `core/utils.py` (`safe_call`, `debug_log`, `json_dumps`,
  `chunked`, `is_user_param_key`), `cli/formatting.py` (`die`, colours),
  `config.py` (project root, `readable_project_path`).
- **Error boundaries.** Wrap external operations (file I/O, git, plugin calls)
  in try/except — a capture failure must never crash the user's training run.
  Swallowed failures surface via `debug_log` under `EXPTRACK_DEBUG`.
- **Deduplicate on write.** `log_artifact()` dedupes by resolved path; follow
  that check-before-insert pattern for new data types.

### Dashboard rules

- Keep existing JS function signatures stable — other modules call them.
- All API calls go through `api()` (GET) / `postApi()` (POST). Both can return
  `null`; callers must guard.
- Use CSS custom properties from `css/reset.py`, never hardcoded colours.
- **Escaping in inline handlers**: use **`escJsAttr(value)`** (= `esc(escJs(x))`)
  for any user-controlled value inside an inline `on*="…('…')"` handler. Plain
  `esc()` alone there is a stored-XSS bug. Enforced by
  `tests/test_dashboard_js_integrity.py`, which also checks every
  inline-handler function is defined.

## Rules for Changes

### 1. Documentation — only what the change actually invalidates

**Most changes need no `CLAUDE.md` edit at all.** This file is an index; edit it
when the index is *wrong*, not on principle. Work outward from what changed:

| What you did | What to update |
|---|---|
| Fixed a bug *within* an existing pattern's rules | Usually nothing. If the bug revealed a constraint worth recording, add it to the pattern's detail file. |
| Changed how a documented pattern behaves | That pattern's detail file. Touch the index only if its one-line rule is now inaccurate. |
| Added or removed a pattern | Detail file **and** the index one-liner (and the routing table). |
| Added/moved/renamed a module, route or table | The index's map; `docs/design/architecture.md` too if the *why* matters. |
| Added a config key | `docs/design/config.md`; the index only if it's one people hit often. |

The index must never state a rule its detail file contradicts — that is the one
hard constraint. When unsure, prefer editing the **detail** file: it is read
only when relevant, so it is the cheap place to be thorough. The index is read
every session, so it stays terse.

### 2. Changelog and version

Every user-visible change (feature, bug fix, behaviour change) also updates:

1. **`CHANGELOG.md`** — an entry under the current unreleased version,
   [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) format, using
   `### Added` / `### Changed` / `### Fixed` / `### Removed`. Lead each bullet
   with a bolded short title, then one sentence on what changed and why a user
   should care.
2. **`pyproject.toml`** — bump `version`. Patch for fixes, minor for features or
   schema migrations, major for breaking API changes. `__version__` reads from
   package metadata, so this is the single source of truth.

**Internal-only refactors** (moving a helper, renaming a private function) may
skip the changelog and version bump, but still update this file if the
structural map changes.

**Cosmetic dashboard tweaks** — purely presentational CSS/JS with no new module,
route, schema column, config key, or behaviour contract (a hover affordance, a
sticky bar, a colour tweak) — update **`CHANGELOG.md` + `pyproject.toml` (patch)**
only. Don't rewrite pattern detail for these; the pattern is unchanged, only its
surface. Touching a route, manager function, DB column, or documented behaviour
is **not** cosmetic.

### Writing pattern detail

When you add to `docs/design/patterns/*.md`, write the **rule first**, then the
failure it prevents. The history is the point — "this used to do X, which
silently did Y" is what stops the next change reintroducing it. Don't compress
that away; it is why these files exist and why they are not loaded eagerly.
