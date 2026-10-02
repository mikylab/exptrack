# CLAUDE.md

Guidance for Claude Code working in this repository.

**This file is the index, not the manual.** It is loaded on every session, so it
carries only the map, the rules, and the constraints most often broken. The
reasoning — what was tried, what broke, why the code is shaped this way — lives
in `docs/design/` and is read on demand. **Before changing a subsystem, read its
pattern file** (table below).

## Project

**exptrack** is a local-first, zero-friction Python experiment tracker for ML.
It captures params, metrics and git state by monkey-patching argparse and
IPython hooks — no code changes in user scripts. SQLite (WAL), **stdlib only**.

## Install, test, lint

```bash
pip install -e ".[dev,integrations]"     # integrations = matplotlib/numpy/pandas;
                                         # capture tests SKIP without them, CI fails on skips
python -m pytest tests/ -x -q            # the suite
python tests/run_all.py                  # legacy per-file runner (needs `pip install -e .`)
ruff check .                             # enforced in CI
npx eslint exptrack/dashboard/static/js  # enforced in CI
python tests/smoke.py                    # 30 s end-to-end sanity check
```

CI (6 Python versions + both linters + an integration-skip guard) is the gate.
`python tests/release_check.py` guards a release; solo-maintainer notes are in
`MAINTENANCE.md`.

## Running

```bash
exptrack init [name]                      # .exptrack/, patches .gitignore
exptrack run train.py --lr 0.01           # wrap any script
eval $(exptrack run-start --lr 0.01)      # shell/SLURM: then run-finish / run-fail
%load_ext exptrack                        # notebooks; Session Trees via %exptrack session start
exptrack ui start                         # dashboard, port 7331
```

Full command and magic reference: `docs/design/usage.md`. The authoritative
command list is `cli/main.py:_DISPATCH` — **never quote a command count in docs**.
User-facing docs: `docs/cli-reference.md`, `docs/session-trees.md`.

## Map

Module-by-module detail with rationale: `docs/design/architecture.md`.

```
exptrack/
  _console.py      harden_stdio: an unencodable glyph degrades to ASCII (leaf, stdlib only)
  __main__.py      `exptrack run`: runpy wrapper, publishes the adoptable run, auto-resume
  config.py        config.json, project root, gitignore rules, dashboard token, user_dir(),
                   thread-scoped project override (activate/active/reset_project, project_scope)
  projects.py      known projects: registry, worktree discovery, read-only schema probe
  notebook.py      %load_ext magics + explicit API
  core/            experiment (lifecycle), db (schema, migrations, blob refcounts), queries
                   (read side), export_render (text/HTML/comparison), diff_view, utils,
                   reference, param_study, leaderboard, primary_metric, metric_alias,
                   naming, hashing, dataset, environment, script_snapshot, storage, trash, git
  capture/         argparse / matplotlib / tensorboard patches, notebook_hooks,
                   session_hooks, cell_lineage, variables (+ back-compat shims)
  cli/             main.py (_build_parser + _DISPATCH), pipeline/inspect/mutate/admin/
                   tunnel/project/session/help _cmds, formatting.py (die, colours)
  sessions/        _shared, manager (+ back-compat facade), lifecycle, materialize, tree
  plugins/         Plugin base + registry, github_sync
  examples/        bundled examples served by `exptrack examples`
  dashboard/       app.py (ThreadingHTTPServer), daemon.py (detached lifecycle), handler.py
                   (table-driven GET dispatch, headers), static.py (bundles),
                   static/{js,css}/ (THE CONTENT), static_parts/ (loader shims + html.py),
                   vendor/ (Chart.js), routes/read_routes.py, routes/write_routes/ (POST)
```

**Dashboard JS/CSS lives in real files** under `dashboard/static/{js,css}/`
(29 JS, 18 CSS). `static_parts/{js,css}/*.py` are ~3-line shims — **edit the
`.js`/`.css`, never the shim**. A new JS file needs a shim, an entry in
`static_parts/js/__init__.py` (import, `get_all_js()` order, `__all__`) and in
`static_parts/scripts.py`.

**A new `write_routes` endpoint** goes in its submodule **and** `__all__`
(`tests/test_dashboard_routing.py` enforces it). Imports there are absolute and
mostly function-local, so a wrong path fails at call time, not import time.

## Pattern files — read before editing

| Editing | Read first (`docs/design/patterns/`) |
|---|---|
| `core/experiment.py`, `__main__.py`, `core/script_snapshot.py` | `run-loop.md` |
| `core/param_study.py`, `leaderboard.py`, `primary_metric.py`, `reference.py`, `metric_alias.py` | `analysis.md` |
| `capture/*`, `notebook.py` | `capture.md` |
| metric logging, `get_metrics_series`, `js/charts.js` | `metrics.md` |
| `core/storage.py`, `core/trash.py`, delete/clean paths | `storage.md` |
| `sessions/*`, `capture/session_hooks.py`, `js/sessions.js` | `sessions.md` |
| `js/sidebar.js` view switching, URL hashes, anything feeding Compare | `dashboard-views.md` |
| `js/table.js`, `experiments.js`, `detail.js`, `inline_edit.js`, `notes.js` | `dashboard-ui.md` |
| `css/reset.css`, `js/highlight.js`, `js/timeline.js` | `dashboard-render.md` |
| `dashboard/handler.py`, `app.py`, `routes/*`, `daemon.py`, `projects.py`, `cli/tunnel_cmds.py`, `cli/project_cmds.py` | `server.md` |
| `core/db.py` schema | `docs/design/schema.md` + bump `_SCHEMA_VERSION` |

### Constraints most often broken

**Run loop** (`run-loop.md`)
- `_BASELINE_WHERE` is the one rule for what can be a baseline: trashed, `running` and `_arg_error` runs excluded, other `failed` kept. An explicit `variant_of` beats chronology.
- Only a *bare* `Experiment()` adopts the `exptrack run` wrapper, and only once. `_maybe_snapshot_script` is the one snapshot entry point.
- Every ending is an outcome: Ctrl-C is `failed` + `_interrupted`, never left `running`. A run's `script` is its identity and must not vary with inputs.
- Once a run's output folder exists, every writer uses the recorded `_output_dir`.

**Analysis** (`analysis.md`)
- `leaderboard` is only views over `param_study.build_matrix` — no ranking surface may disagree with the matrix.
- A configured primary metric is **never silently substituted**; every answer states its `source`. Confounded parameters are not charted.
- The dashboard sets it through one picker (`openPrimaryMetricPicker` → `/api/primary-metric`) at a level the reader names, via the CLI's own setters.
- Identical rerun / same params + different code / same params + different data are three different answers, never one flag.

**Capture** (`capture.md`) — a capture failure must never crash the user's run; swallow and `debug_log`.

**Metrics** (`metrics.md`)
- Thin by counting points, **never** `step % N`. Never wrap metric writes in `with get_db()` (it commits on exit and defeats batching).

**Storage** (`storage.md`)
- `_trash_or_local` is the only way exptrack removes a file (OS Trash, never `rmtree`, refuses Python environments). DB rows sweep freely; blobs are refcounted.
- A file another run references is not this delete's to remove (`artifact_claims_by_others`); `--yes` never answers the shared-files question.
- `deleted_at` marks trash; every list filters it, single-run lookups do not. Every SUM in a byte total is COALESCEd.
- `_console.harden_stdio()` runs at every entry point — CLI `main()`, `python -m exptrack`, `Experiment()` and `exptrack.notebook` — so a cp1252 console never kills output.

**Sessions** (`sessions.md`) — **every magic is idempotent under Run-All**. Metrics are attributed to a node at write time (`metrics.session_node_id`), never inferred afterwards.

**Dashboard views** (`dashboard-views.md`)
- `releaseCanvas()` is the single teardown; every view switcher calls it first.
- Every full-canvas view has a hash (`#run=`, `#compare=`, `#matrix`, `#sessions[=id]`, `#trash`); `_pushViewHash` is the one writer, `_restoreViewFromHash` the one parser. Moving inside a view replaces; entering pushes.
- A selection belongs to the surface that owns it; clearing the picks clears the comparison they produced. `openRunPicker` is the one run picker.
- A bare run id means the current project; a qualified id is `<project-id>:<run-id>`, never a path.
- Compare columns are headed by the settings that tell runs apart (`_cmpRunLabel` → `_multiSeriesLabel`); the name is the fallback.

**Dashboard UI** (`dashboard-ui.md`)
- One inline editor open at a time, and closing commits. A selection change repaints in place, never via the loader.
- `api()`/`postApi()` can return `null`; every caller guards. Failures are shown, never a blank view.
- Every Export has a Copy beside it. Copies go through `copyRich(text, html)` with server-rendered HTML; readable must not drop data.
- Notes are markdown stored exactly as typed. `js/notes.js` renders for display only; exports render the same text server-side.
- Green means *better*, not bigger (polarity-aware deltas).

**Render** (`dashboard-render.md`) — `css/reset.css` holds the tokens; any alias whose value is `var(--other)` must be redeclared in both `:root` and `body.dark`. No webfont, no CDN.

**Server** (`server.md`)
- `ThreadingHTTPServer` is a correctness requirement. Never run a blocking WAL checkpoint on a request path.
- JSON goes out through `core/utils.json_dumps` (no `NaN`/`Infinity`). A set-valued read is a POST.
- A thread's project is bound per request and reset in `handle_one_request`'s `finally`. An unknown project id is a 400 and never falls back to the default project.
- Discovery probes a schema with `mode=ro` and never migrates (`get_db()` migrates in either direction).
- The dashboard token lives in `.exptrack/dashboard_token`, never in the committable `config.json`.
- On Windows the daemon is spawned `CREATE_NO_WINDOW`, not `DETACHED_PROCESS` — otherwise every `git` it runs opens a console window.

## Database

SQLite WAL, 10 tables (`experiments`, `params`, `metrics`, `artifacts`,
`timeline`, `cell_lineage`, `code_baselines`, `code_snapshots`, `sessions`,
`session_nodes`). Columns and rationale: `docs/design/schema.md`.

**Bump `_SCHEMA_VERSION` by +1 with any schema change** or existing DBs never see
it. Indexes on migrated columns go in the `_migrate_*` helper, never in
`_create_base_schema` — one failed statement there aborts the script and breaks
every install on upgrade.

## Configuration

`.exptrack/config.json`, documented in `docs/design/config.md`. An unusable value
must degrade to the documented default. **Before adding a setting, ask whether
it's a secret** — `config.json` is committable.

## Coding rules

- **stdlib only** in the package (pytest, ruff, eslint are dev-only).
- Functions past ~40 lines: consider splitting. Reuse `core/db.py` (`get_db`,
  `_find_exp`), `core/utils.py` (`safe_call`, `debug_log`, `json_dumps`,
  `chunked`, `is_user_param_key`), `cli/formatting.py` (`die`, colours),
  `config.py` (project root, `readable_project_path`).
- Wrap external operations (file I/O, git, plugins) in try/except; surface
  swallowed failures via `debug_log` under `EXPTRACK_DEBUG`.
- Deduplicate on write (check before insert), as `log_artifact()` does.

Dashboard:
- Keep existing JS function signatures stable — other modules call them.
- All API calls go through `api()` (GET) / `postApi()` (POST).
- CSS custom properties from `css/reset.css`, never hardcoded colours.
- **Any user-controlled value inside an inline `on*="…('…')"` handler uses
  `escJsAttr(value)`**; plain `esc()` there is stored XSS.
  `tests/test_dashboard_js_integrity.py` enforces it and checks every inline
  handler's function exists.

## Rules for changes

**Docs — only what the change invalidates.** Most changes need no CLAUDE.md edit.

| You did | Update |
|---|---|
| Fixed a bug within a pattern's rules | Usually nothing; a new constraint goes in the pattern file |
| Changed how a pattern behaves | Its pattern file; this index only if a line here is now wrong |
| Added/removed a pattern | Pattern file, and a line here if it is a constraint people break |
| Added/moved/renamed a module, route or table | The map above; `architecture.md` if the *why* matters |
| Added a config key | `docs/design/config.md` |

This index must never state a rule its pattern file contradicts. When unsure,
write it in the pattern file: rule first, then the failure it prevents — "this
used to do X, which silently did Y" is what stops the next change reintroducing
it.

**Changelog and version.** Every user-visible change adds a `CHANGELOG.md` entry
under the current unreleased version ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
`### Added/Changed/Fixed/Removed`; a bolded short title, then what changed and
why a user should care) and bumps `pyproject.toml` `version` (patch for fixes,
minor for features or schema migrations, major for breaking API). An unreleased
version is amended, not bumped again. Internal refactors may skip both. Cosmetic
dashboard tweaks (no new module, route, column, config key or behaviour
contract) get a changelog line and a patch bump only.
