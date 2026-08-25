# 1.4 planning — bug hunt and gap analysis

Working document for the 1.4 release. Assembled from a full audit of the 1.3.0
codebase (run loop, capture, analysis/compare, notebooks/sessions, dashboard,
CLI/storage), focused on the journey 1.2–1.3 built toward: **running and
comparing different models, from scripts and from notebooks**.

Status: **shipped in 1.4.0** (2026-08-09). Five subsystem audits produced ~55
verified findings; all of them are fixed, along with the feature themes in the
scope section at the bottom. The suite and both linters passed on 1.3.0 HEAD, so
none of these were caught by existing gates — every fix landed with a regression
test, in `tests/test_analysis_honesty.py`, `tests/test_run_loop_capture.py`,
`tests/test_cli_safety.py`, `tests/test_notebook_parity.py`,
`tests/test_model_comparison.py`, `tests/test_cli_dispatch.py` and additions to
`tests/test_dashboard_js_integrity.py`.

One audit claim did **not** hold up and no code changed for it: "duplicate
detection is blind to notebook code" (the notebook↔script parity hole below).
The audit traced `_maybe_snapshot_script` skipping `.ipynb` but missed
`queries._run_source_identity`'s cell-hash fallback — verified end-to-end, two
notebook runs with identical cells classify as `identical` with `code: same`.

Severity tags below are as first recorded: CRITICAL/HIGH/MED/LOW; "verified"
means reproduced by executing the real code path, "code-verified" means traced
end-to-end in source only.

## Confirmed documentation drift

- **`docs/design/usage.md` is no longer the "full command surface" it claims to
  be.** It is missing 14 commands present in `cli/main.py:_DISPATCH` (`backup`,
  `compact`, `create`, `delete-study`, `examples`, `link-dir`, `log-artifact`,
  `log-metric`, `log-output`, `log-result`, `source`, `studies`, `ui-stop`,
  `watch`), and still documents bare `exptrack primary-metric` as "clear (back
  to the heuristic)" — the 1.2 change made the bare form *show* the setting;
  clearing takes `--clear`. `docs/cli-reference.md` is correct on both counts.
  **FIXED**: the hand-transcribed command list is gone (it pointed at
  `exptrack --help` / `_DISPATCH` instead, per the CLAUDE.md rule about command
  counts), the header no longer claims to be the full surface, and
  `primary-metric`'s bare/`--clear` forms are documented correctly.

## Bugs and logic errors (audit findings)

### Analysis / comparison layer (verified end-to-end against a fresh DB)

1. **[HIGH] Detail view reports the *first* logged value as "last" for
   step-less metrics.** `queries.py:230-232` (`get_experiment_detail`) and the
   copy at `queries.py:1368-1370` (`get_metrics_summary`) order the `last_v`
   subquery by `COALESCE(step,0) DESC` with no ts/rowid tie-break — with all
   steps NULL (the plain `log_metric(k, v)` case) every row ties and SQLite
   returns insert order. Logging `acc` 0.1 → 0.5 → 0.9 makes `exptrack show`
   and the run-detail Overview say **0.1** while the experiment table says
   0.9. Also uses `COALESCE(step,0)` where every other resolver uses `-1`.
   Fix: `ORDER BY COALESCE(step,-1) DESC, ts DESC, rowid DESC` in both (or
   route through `_latest_metric_rows`).

2. **[MED] `diff_runs`, `leaderboard._param_changes` and `cmd_compare` compare
   raw param values, not normalized ones.** `queries.py:885-899`,
   `leaderboard.py:204-224`, `inspect_cmds.py:402`. The same `lr=0.01` captured
   via argparse (float) and the pipeline CLI (string) — one configuration by
   `param_study._norm`'s own rule — shows as a spurious change
   (`from: '0.01'` → `to: '"0.01"'`, raw JSON in the display), and
   `best_so_far` attributes a record improvement to a **non-edit**. Fix:
   compare via `param_study._norm`; decode before display in `diff_runs`.

3. **[MED] `exptrack compare` colours metric deltas green-when-bigger;
   `watch` hardcodes the opposite.** `inspect_cmds.py:423-426` and `:719-724`.
   A loss improving 0.9 → 0.5 renders red in `compare`; neither surface
   consults `primary_metric.goal_for_key` (which exists for exactly this —
   "green means better, not bigger"). Equal values render a red `<0` marker.
   Fix: colour by `goal_for_key(k)` in both; suppress the marker on `d == 0`.

4. **[MED] Duplicate detection ignores script identity — two different models
   with the same params are flagged "already run".** `param_study.py:846-849`
   groups by param fingerprint only; `find_equivalent_runs` (`:891-895`) drops
   its script filter when `script` is empty, so a script-less run matches
   *every* script. `model_a.py --lr 0.01` and `model_b.py --lr 0.01` group as
   one duplicate. Fix: include script/source identity in the grouping key (or
   add a `script_differs` verdict); require script equality even when empty.

5. **[MED-LOW] `_value_rows` "best" resolves to NULL under `goal=min` when a
   NULL-valued metric row exists.** `primary_metric.py:299-315` — NULL sorts
   first under `value ASC`, so a min-goal run with real values reports
   `best: None` and drops out of best-basis rankings and Pareto. Asymmetric
   (max-goal is fine). Fix: `AND value IS NOT NULL` in the inner SELECT.

6. **[LOW] `exptrack ls` crashes on a NULL metric value.**
   `inspect_cmds.py:92` formats `None` with `:.4g` → `TypeError`, whole
   command dies. `_fmt_g` (same file, line 22) exists for exactly this but
   `cmd_ls` bypasses it. Fix: use `_fmt_g`.

7. **[LOW] An ambiguous id prefix 500s all six param-study/leaderboard
   endpoints.** `write_routes/param_study.py:57` — `AmbiguousPrefixError`
   escapes `_resolve_ids`, contradicting the route's own "unknown ids are
   reported" contract. Fix: catch it per-item and report under
   `unknown_ids`/`ambiguous_ids`.

8. **[LOW] `api_pareto` documents a `basis` body field it ignores.**
   `write_routes/param_study.py:177-201` — docstring says `basis`, code reads
   `rank_by`; a curl user posting `{"basis": "best"}` silently gets the
   final-value frontier. Fix: accept `basis` with `rank_by` fallback.

9. **[LOW] `get_all_latest_metrics` drops all step-less metrics — and has no
   callers.** `queries.py:1383-1394` (`step = MAX(step)` never matches NULL;
   docstring's "used by ls" is stale). Fix: delete it.

10. **[NOTE] A still-`running` run can be pinned as the reference**
    (`reference.py:156-160`) — a target whose metrics are still moving, which
    the baseline rules elsewhere exclude. Decide: refuse, or surface the
    status on the vs-reference strip.

11. **[Known/deferred, confirm for 1.4]** The legacy un-prefixed `error` param
    still leaks through the surfaces that spell the `_`-prefix rule inline
    instead of using `is_user_param_key` (`queries.py:892`, `:1736`, `:2079`,
    `inspect_cmds.py:398`) — a failed run's error message shows as a "param
    change" against every other failed run. Migrate them onto the shared
    predicate.

### Run loop / script-side capture (verified by executing real code paths; suite passes on HEAD, so all are latent)

1. **[CRITICAL — FIXED in 1.4.0] `run-finish` broken** — same `dest="cmd"` collision as
   CLI finding 1 below; independently confirmed by this audit (introduced in
   `fd9c3d3`). Both audits converge on the fix: non-colliding dest + a
   parser-level regression test that goes through `_build_parser()` for every
   pipeline subcommand (the suite calls `cmd_run_finish(SimpleNamespace(...))`
   directly, which is why this shipped).

2. **[HIGH] Ctrl-C under `exptrack run` leaves the run stuck `running` with
   nothing captured.** `__main__.py:197,225` catches `SystemExit`/`Exception`
   but not `KeyboardInterrupt` — verified: SIGINT → `status='running'`, no
   duration, no error, log files unclosed; the run vanishes from every
   baseline (`_BASELINE_WHERE` excludes `running`) until `stale` (24 h).
   Interrupting training is one of the most common ways a run ends; the
   context-manager path records it correctly. Fix: `except BaseException` →
   restore streams, `exp.fail("KeyboardInterrupt")`, exit 130.

3. **[MED-HIGH] `_auto_detect_outputs` attributes other runs' files to the
   finishing run.** `__main__.py:377` — the finish-time `os.walk('.')` filters
   only by mtime and this run's own paths; `outputs/` isn't in `_SKIP_DIRS`.
   Verified with two concurrent runs: model A registered model B's weights
   *and* B's stdout/stderr logs as its own artifacts. Any parallel launch
   (SLURM arrays, two terminals) cross-contaminates. Fix: skip files under
   other experiments' output dirs / already-registered paths.

4. **[MED] The phantom-wrapper trash is defeated by the same scan.**
   `__main__.py:307` vs `:377` — a sweep script under `exptrack run` leaves
   the wrapper untrashed because the scan swept the children's model files
   onto it as artifacts, so "no data of its own" never fires. Fixing 3
   restores it.

5. **[MED] Shell-pipeline `_code_snapshot` is clobbered and double-encoded.**
   `pipeline_cmds.py:344-348` — `json.loads` on an already-native list raises,
   the `kind:"script"` entry is dropped, and the remainder is double-encoded.
   Verified end-to-end: after editing `train.sh` between two pipeline runs,
   `compare_run_code` says "no code change" and `exptrack source` says "No
   source captured"; `--resume` duplicates the shellscript entry per resume.
   Fix: treat the existing value as decoded; pass the native list to
   `log_param`.

6. **[MED-LOW] Every pipeline run gets `name_is_auto = False`.**
   `pipeline_cmds.py:236` always passes a truthy `name`, so generated names
   register as user-chosen — the "auto" badge, bulk-rename filter and
   un-renamed count all skip pipeline runs. Fix: pass `name=args.name` (or a
   `name_is_auto` constructor arg).

7. **[MED-LOW] Direct `run-start` embeds param values in the pseudo-`script`
   identity.** `pipeline_cmds.py:300-301` — `script='exptrack run-start --lr
   0.5'` vs `'--lr 0.9'`: two runs of the same pipeline never share a script,
   so vs-previous, "What changed", `--resume latest` and duplicate detection
   silently never fire for interactively-launched pipeline runs. Fix: stable
   identity (the `--script` hint or plain `exptrack run-start`); keep the full
   invocation in `command`.

8. **[MED-LOW] `exptrack log-artifact` violates the dedup/resolve/hash
   contract.** `pipeline_cmds.py:609-616` — three invocations → three rows,
   relative paths, NULL hash/size; breaks `verify` and the CLAUDE.md
   check-before-insert rule (`link-dir`/`log-output` do dedupe). Fix: resolve,
   dedupe, hash via the shared helper.

9. **[LOW-MED] `--resume` with no previous run records an unrunnable Reproduce
   command** (`__main__.py:264` — no interpreter, embeds `--resume`). Fix:
   thread `run_command` into the fallback constructor.

10. **[LOW] Raw-argv capture never refreshes the run name** —
    non-argparse scripts lose the param fingerprint in names
    (`argparse_patch.py:124-155`; `Aug09_t__f61df63a` with `lr` captured but
    absent from the name — two different-model runs indistinguishable by
    name). Fix: same guarded `_rename` the namespace path does.

11. **[LOW] `run-finish --params`/`run-fail` use `INSERT OR REPLACE INTO
    params`** (`pipeline_cmds.py:486,537`), resetting a dashboard-edited
    `manual` source back to `auto` — the exact hazard
    `Experiment._write_params`' docstring documents. Fix: same upsert.

12. **[LOW] No writer ever emits `source='pipeline'` for metrics**
    (`pipeline_cmds.py:482,583` omit the column → default `'auto'`), though
    capture.md promises it and the dashboard styles a `pipeline` badge. Fix:
    pass the source (or retire the tag in docs).

13. **[LOW] A repo with no commits records `git_diff = "[capture-failed]"` on
    every run** (`git.py:83-95` — unborn HEAD; common right after `exptrack
    init`). Fix: detect unborn HEAD, record a distinct "no commits yet".

14. **[LOW] `/proc/<pid>/stat` parsed with bare `split()`**
    (`pipeline_cmds.py:126-130`) — a comm with spaces (`tmux: server`) shifts
    the ppid field and aborts calling-script detection. Fix: `rsplit(')', 1)`.

15. **[LOW] Dual argv+argparse capture stores one HP under two keys** when
    `dest=` differs from the flag (`lr` + `learning_rate`), polluting the
    "what varies" analysis with duplicate axes. Fix: drop argv keys shadowed
    by a namespace capture.

    Also flagged (unverified): `_save`'s `INSERT OR REPLACE` column list
    (`experiment.py:488-502`) omits `duration_s`/`deleted_at`/`studies`/
    `stage`/`session_node_id` — any re-save would silently NULL them; a plain
    `INSERT` would make the class impossible. And the savefig patch resolves
    paths outside its try/except (`matplotlib_patch.py:72-91`), a latent
    violation of "every patch guards its own capture".

### Dashboard Compare (verified by code trace; suites + eslint pass clean, so none are caught by current gates)

1. **[MED-HIGH] Pair Compare silently does nothing for runs outside the picker
   cache.** `detail.js:12-23,130-147` + `compare.js:221-223` — `_openPairCompare`
   assigns `sel.value = id` against options built from `_cmpExps` (first page,
   1000 most recent). An older run (easy via "Load all runs" or the filmstrip)
   yields `value = ''` and `doCompare` returns silently — the "button that does
   nothing" failure class `dashboard-views.md` documents. Fix: inject missing
   ids as options before assigning; make `doCompare` say "select two runs"
   instead of returning.

2. **[MED] Multi Compare tints the WORST run green on lower-is-better
   metrics.** `compare.js:464-489` + `compare.css:41-42` — highlight is raw
   max=green/min=red; for `loss`/`latency` that's inverted. Violates the
   project's own "green means better, not bigger" rule, and
   `metricGoodDirection` (`core.js:151`, sync-tested against the server list)
   exists precisely for this — the pair view's Delta column already uses it.
   Fix: tint best/worst via `metricGoodDirection`.

3. **[MED] Chart canvas-id collision throws and silently drops all remaining
   charts.** `compare.js:317,390,496,534` — canvas ids sanitize the metric key
   (`val/acc` and `val_acc` collide); in Multi Compare keys are the union
   across runs (exactly the different-models case), the second `new Chart`
   throws (verified against vendored Chart.js 4.4.9), and the unhandled
   rejection kills every later chart while the table looks healthy. Fix: id by
   key index, not sanitized key.

4. **[MED-LOW] Multi table can print two identical values, one tinted green
   one red.** `compare.js:476-486` — mn/mx tint compares full-precision floats
   with no epsilon while cells render `.toFixed(4)`. The pair view already
   solved this (`fmtMetricPair` + `metricMoved`); the multi view uses neither.
   Fix: apply the epsilon and precision escalation.

5. **[MED-LOW] Multi Compare silently drops unresolvable picks.**
   `queries.py:1397-1403` (`if not exp: continue`) + `compare.js:451-456`
   (never compares counts). Pick 4, render 3, nothing says so — the exact
   honesty rule branch-compare and the matrix both implement. Fix: return
   `unknown_ids` from the endpoint and render a missing-picks notice.

6. **[LOW-MED] No staleness guard on `doCompare`/`doMultiCompare`.**
   `compare.js:218-241,443-451` — two rapid clicks interleave; the older
   result can land last (and leak the loser's Chart instances). Contrast
   `refreshDetail`'s `currentDetailId` re-check. Fix: request token, bail
   before DOM writes if superseded.

7. **[LOW-MED] Code-changes panel direction can flip relative to the columns.**
   `queries.py:1003-1012` reorders the pair older→newer; the tables above keep
   pick order; the working-tree fallback branch (`compare.js:190`) uses pick
   order — so the panel can read opposite to the tables *and* disagree with
   its own fallback. Fix: label each code block with the run names in diffed
   order (or reorder the whole payload chronologically and say so).

8. **[LOW] Bulk Export/Copy don't guard a failed `postApi`.**
   `table.js:55-89,180-200` — a 500 downloads a `.csv` containing
   `{"error":...}` plus a success toast. Violates the documented
   "callers must guard" rule. Fix: check `data.error`/shape before the blob.

9. **[LOW] Compare image grids slice to 60 silently and drop the server's
   `truncated` flag.** `compare.js:341-371` — header says `(200)`, grid shows
   60. Fix: "showing 60 of N" strip.

10. **[LOW] Variables compared after 60-char truncation.** `compare.js:274-276`
    — two long reprs differing past char 60 show equal and vanish under "Show
    only differences". Fix: compute `differs` on full strings, truncate only
    for display.

11. **[LOW] `/api/multi-compare` passes the id set in a GET query string.**
    `handler.py:130` — the param-study routes' own docstring explains why
    set-endpoints must POST; ~5000 selected runs exceeds http.server's 64 KiB
    request line → generic 414. Fix: convert to POST sharing `_resolve_ids`
    (also fixes finding 5's `unknown_ids` for free).

12. **[INFO] Duplicate metric keys (multi-source) collapse arbitrarily in
    Compare** (`queries.py:226-234` groups by key+source;
    `latestMetricsMap`'s `Object.fromEntries` keeps whichever sorts last).

13. **[INFO] Raw NUL byte in `highlight.js`** (offset ~17746) makes
    grep/ripgrep treat the file as binary and silently stop mid-file — a trap
    for any future grep-based integrity test. Fix: spell it `'\u0000'`.

14. **[Known gap, mitigated] Sessions `_compareNodes` not pruned on tree
    reload** (`sessions.js:10,753-759`) — already named in
    `dashboard-views.md`; `runCompare`'s missing-picks notice catches it at
    compare time.

### CLI / config / DB / storage (findings 1–13 reproduced by running the real CLI; suite passes 105/105, so all escape it)

1. **[CRITICAL — FIXED in 1.4.0] `exptrack run-finish` is completely broken —
   prints help, exits 0, run stays `running`.** `cli/main.py:125`
   (`add_subparsers(dest="cmd")`) collides with the `--cmd` option on
   `run-finish`/`run-start` (`main.py:149`, `:101`): the subparser's `--cmd`
   default `""` overwrites `args.cmd = "run-finish"`, so `main()` prints help
   and returns 0. **Re-verified independently end-to-end**: the documented
   SLURM pipeline (`eval $(exptrack run-start …)` … `run-finish $EXP_ID`)
   silently never ingests results; a later `exptrack stale` then falsely fails
   the run. With `--cmd "…"` passed it's a `KeyError` traceback instead. The
   suite misses it because pipeline tests call `cmd_run_finish(...)` directly.
   Fix: rename the subparsers dest (e.g. `dest="subcommand"`) or give both
   `--cmd` flags an explicit non-colliding dest; add a through-argv regression
   test.

2. **[CRITICAL] Auto-migration can stamp a legacy DB current while columns are
   still missing — then every run crashes forever.** `core/db.py:405-445` +
   `:787-803` + `admin_cmds.py:191-209`. The six legacy columns (`command`,
   `hostname`, `python_ver`, `duration_s`, `notes`, `tags`) have **no
   `_migrate_*` helper** (violating CLAUDE.md's own rule), and the
   stamp-only-on-success guard is defeated on the *second* open: pass 1 adds
   `params.source` then fails its backfill (no `hostname`), no stamp; pass 2
   skips the already-done ALTER, everything "succeeds", `user_version`
   stamped — with columns still absent. `run-start` then dies
   `no column named command` and no connection ever retries; only manual
   `exptrack upgrade` recovers. Fix: put the legacy columns in an idempotent
   `_migrate_*` helper; gate each helper's success on its backfill
   independently of whether its ALTER ran this pass.

3. **[HIGH] `clean` flag combinations silently drop the requested action.**
   `mutate_cmds.py:346-402` dispatches on the first matching flag only:
   `clean --older-than 30d --vacuum` runs **only** VACUUM, exit 0, no warning
   — the retention delete never happens. Fix: mutually-exclusive group, or run
   `--vacuum` after the selected mode.

4. **[HIGH] `backup`/`restore` failures exit 0.** `admin_cmds.py:738-741,
   749-751, 761-764, 792-794` — "Backup file not found", "Restore failed:",
   refuse-to-overwrite all `print; return`. A cron backup can fail silently
   forever. Fix: `die()` on every error path.

5. **[HIGH] Config coercion only covers numeric keys — a bad string-typed key
   crashes every command.** `config.py:105-120`, `:286-318`. `"db": 123` →
   `TypeError` from `get_db` on every invocation, violating the documented
   "unusable value degrades to default" invariant. Fix: type-check every key
   against its default's type at load, same stderr note.

6. **[HIGH] `rename_output_folder` rewrites artifact paths by bare
   `startswith`.** `db.py:1846` — renaming run `run1` → `run2` also rewrites
   artifacts under `outputs/run1_extra/` to a nonexistent path (dangling row,
   file invisible to `verify`/delete). Fix: boundary match
   (`== old` or `startswith(old + os.sep)`), as `db.py:1535` already does.

7. **[MED] Destructive confirmation prompts crash with a raw `EOFError`
   traceback non-interactively — inconsistently guarded.**
   `mutate_cmds.py:335, 287, 375, 395, 441, 515, 646, 779` use bare `input()`
   while `_confirm_prune` and `cmd_restore` catch EOF/Ctrl-C cleanly. Fix: one
   shared `confirm()` helper (EOF → cancelled, exit 1); add `--yes` to
   `rm`/`clean`.

8. **[MED] `stale` mutates trashed runs.** `admin_cmds.py:157-160` — no
   `deleted_at IS NULL`, so a trashed running run is flipped to `failed` with
   an injected `error` param while in the Trash; Restore then resurrects
   mutated state. Same gap in `_print_storage_health` (`:1236`). Fix: add the
   filter.

9. **[MED] `clean --reset` early-returns "Database is already empty" while
   sessions/nodes/snapshots remain.** `mutate_cmds.py:407-427` — emptiness
   check and preview count only the five experiment tables, re-introducing the
   stranded-sessions failure `_RESET_TABLES` fixed. Fix: count the session and
   snapshot tables in both.

10. **[MED] `compact` inconsistencies.** `admin_cmds.py:456-463`: invalid
    `--older-than` prints an error but exits 0, and accepts bare `30`/`30dd`
    where `clean` correctly dies; `:447-452`: typo'd/ambiguous id prefixes go
    through raw `LIKE` with no report ("No matching experiments.", exit 0).
    Also (`:430-436`) the real-run summary claims it compacted the whole
    selection while dry-run correctly reports "Would compact 1 of 5". Fix:
    share `clean`'s age validation, resolve ids via `find_experiment`,
    aggregate affected sets like the dry-run branch.

11. **[MED] The documented fallback path for `run-start` rejects user params.**
    `main.py:85-93` — `exptrack --no-color run-start --lr 0.5` →
    `unrecognized arguments: --lr` (REMAINDER only captures after a
    positional). Fix: route to the mini-parser whenever `run-start` leads, or
    `parse_known_args` for this subcommand.

12. **[LOW] `exptrack restore <id>` foot-gun** — `restore` means
    DB-from-backup; pointing it at a run id prints "Backup file not found",
    exit 0 (compounds finding 4). No CLI way to restore a trashed experiment
    exists at all (see gaps).

13. **[LOW] `ui --clear-token`/`--token` also launch the dashboard**
    (`admin_cmds.py:91-105`), and the legacy-token cleanup rewrites
    `config.json` with all defaults inlined (`:94-97`), freezing defaults into
    a committable file.

14. **[LOW, code-verified] `rm`/`compact` id prefixes are unescaped in `LIKE`**
    (`mutate_cmds.py:311` — `exptrack rm %` matches every run); `prune
    --max-points N` can retain N+3 (protected points; help overpromises);
    `compact` default selection includes trashed runs (`deleted_at` unfiltered)
    so a trashed run's diff is stripped without appearing in any list.

    Refcounting/blob audit: clean — no leak or premature delete found.

### Notebooks / Session Trees (findings 1–7, 12 reproduced end-to-end — real IPython 9.16 for hook tests; 8–11 code-verified; suite green at 1302 passed, so all escape it)

1. **[HIGH] A branch whose first replayed cell is `%%setup` forks a duplicate
   branch on every Run-All.** `sessions/manager.py:324` vs `:904,917` — the
   collision baseline is armed from tracked-cell source only, so the setup
   cell's source never matches and every pass creates `tryA (2)`, `tryA (3)`…
   with duplicated cells and re-attached metrics. Fix: arm a parallel
   `baseline_setup_first` and compare setup source against it.

2. **[HIGH] Promoting a branch to a checkpoint breaks `branch` idempotency.**
   `manager.py:899-900` — the existing-node lookup excludes type
   `checkpoint`, so after `promote_to_checkpoint` a Run-All creates a second
   node with the same label beside the promoted one. Fix: include
   `"checkpoint"` in the lookup's type tuple.

3. **[MED-HIGH] `%exp_log`/`log_last` finds nothing when notebook detection
   returns a relative path.** `notebook.py:146-148` searches for the raw
   detected name while runs store the resolved absolute path
   (`experiment.py:276-279`; exact-match query `queries.py:341-349`). In
   common JupyterLab deployments the post-hoc logging feature's primary use
   case silently fails ("no previous run found"). Fix: normalize the path the
   same way `Experiment.__init__` does before lookup.

4. **[MED] Auto HP capture renames a run the user explicitly named.**
   `notebook_hooks.py:608-610` calls `exp._rename(make_run_name(...))`
   unconditionally — `%exp_start my-named-baseline` + `lr = 0.01` in a cell →
   the explicit name is replaced by an auto name with `name_is_auto` still
   False. Fix: guard with `if exp.name_is_auto:`.

5. **[MED] Session-node metric tagging leaks onto unrelated experiments, and
   materialize then copies foreign numbers onto branch runs.**
   `experiment.py:109-130` tags *any* metric logged while a session is active
   in the kernel, whoever owns the run; `materialize.py:293-307` then copies
   those tagged rows onto the graduated run — cross-attribution re-entered
   through the very tag meant to prevent it. Fix: tag only when the run
   belongs to the session (`_active_session_node(exp)`).

6. **[MED] A notebook containing `%exptrack session end` duplicates the whole
   session tree on every Run-All.** `manager.py:661-666` re-adopts only
   `active` sessions; the natural start-at-top/end-at-bottom notebook shape
   produced three full duplicate trees in three passes. Fix: re-adopt (and
   re-open) the most recent *ended* same-name+notebook session this kernel
   ended, or at least say a new session is being created.

7. **[LOW] `%exp_note` is not idempotent under Run-All** —
   `notebook.py:464-466`: notes double per pass; `%exp_tag` and `promote`
   both dedup. Fix: skip when the identical line exists.

8. **[LOW] `%exptrack promote` violates the 1:1 node↔run invariant**
   (`manager.py:1130-1134` skips the `_detach_experiments` the dashboard's
   link path does) → arbitrary `→ exp` badge, double-counted checkpoint sums.
   Fix: detach before the UPDATE.

9. **[LOW] `record_image` writes onto trashed nodes** (`manager.py:528` lacks
   the `deleted_at IS NULL` guard + re-anchor recovery every other per-cell
   write has). Fix: add both.

10. **[LOW] `_nb_state["setup_count"]` never resets between runs**
    (`notebook_hooks.py:55`; both attach paths reset every other key). Second
    run in one kernel gets `setup_3`, `setup_4`… Fix: reset in both.

11. **[LOW] `exptrack session nodes` lists trashed nodes with no marker**
    (`session_cmds.py:66-69`), violating the documented "a trashed thing that
    is reachable must say it's trashed". Fix: filter or mark.

12. **[LOW, embedded shells only] Out-dict fallback can attribute the previous
    cell's value to a no-output cell** (`notebook_hooks.py:351-360` uses
    `ip.execution_count`; safe in real kernels, wrong under
    `InteractiveShell.run_cell`). Fix: use `result.execution_count`.

    Also noted (working as coded, likely to mislead): two kernels can silently
    interleave into one session when notebook detection fails
    (`manager.py:667-672` lenient re-adopt); a session ended from the
    dashboard keeps silently accepting cells from the kernel; `%%scratch`
    variable mutations get attributed to the next tracked cell; `%exp_tag`
    before the first cell raises a raw traceback; `%reload_ext exptrack`
    mid-run silently finishes the live run.

### Notebook↔script parity holes (both MED, code-verified)

- **Duplicate detection is blind to notebook code.** `_maybe_snapshot_script`
  skips `.ipynb` (`experiment.py:539`) and the git diff excludes `*.ipynb` by
  default, so "same params + different code" — one arm of the three-answer
  taxonomy — is unreachable for notebooks even though cell lineage holds
  exactly that information. Direction: fold a cell-lineage digest into
  `code_fingerprint` for notebook runs.
- **Materialized runs are second-class.** `materialize.py:151-159` writes no
  `script` and copies no params — so graduated branch runs never join
  baseline chains or the "What changed" card, and a param study over a
  finalized session shows *nothing varying* (the HP that distinguished the
  branches lives only in `_var/` keys). Direction: copy the node's HP-shaped
  `_var/` values as real params and set `script` at materialize time.

## Missing features: comparing/running different models

### From the analysis layer

- **No metric-key aliasing across models.** Model A logs `val_acc`, model B
  logs `accuracy` → `diff_runs`/Compare/the reference strip show *no* metric
  overlap, and consensus ranking excludes one model wholesale. A per-project
  alias map (`val_acc ≡ accuracy`) consulted wherever keys are matched would
  make cross-model compare/rank/Pareto work.
- **No per-script scoping in the analysis views.** `build_matrix` over a
  mixed-script set fuses both models' param namespaces: a shared `lr` column
  mixes semantically different knobs and each model's exclusive params render
  as MISSING "variations" on the other's rows. No `group_by=script`, no
  per-script sub-matrix.
- **Duplicate detection has no model dimension** (bug 4 is the failure half;
  the feature half is a script/source agreement dimension in the verdict
  ladder).
- **No cross-metric ranking mode.** When a set legitimately splits across
  primary metrics, a 1-vs-1 split resolves by lexical tie-break (`loss`
  silently beats `val_acc` as the set's axis); there is no
  rank-by-each-run's-own-primary or normalized-score option.
- **CLI compare is pairwise and polarity-blind** (bug 3). No N-way CLI
  compare, and no "all runs vs the pinned reference" table on either surface —
  the shape cross-model evaluation usually wants.
- _(Unverified, minor)_ `reference.configured_ids` collapses badge labels when
  one run is both project and study reference (`reference.py:184-189`).

### From the run loop / launch modes

- **Bare `python train.py` gets no zero-friction param capture at all** — the
  patches install only under `exptrack run` and notebooks, so switching a
  script between launchers floods the "What changed" card with every param as
  a spurious change.
- **No "interrupted" outcome distinct from `failed`** — a deliberate Ctrl-C
  and a crash are different facts; the loop treats "it broke" baselines
  specially.
- **TensorBoard writers created before the experiment aren't buffered** — the
  savefig patch buffers pre-experiment artifacts and flushes on creation; the
  TB patch just drops them. Asymmetric.
- **No stable "pipeline identity" for direct `run-start`** (run-loop bug 7's
  feature half) — a stable `script` identity would restore vs-previous and
  duplicate detection for shell workflows.
- **`duration_s` means different things by finish path** — `Experiment.finish`
  records the final session's wall time on resume; `run-finish` records total
  elapsed since creation. Pick one definition.

### From the dashboard Compare experience

- **Metric-key aliasing again** — `train/loss` vs `train_loss` vs `loss` are
  three unrelated rows on every compare surface (and trigger the canvas-id
  collision, bug D3, when both spellings coexist).
- **Pair charts render shared keys only** (`sharedMKeys`) — a metric logged by
  one run is never charted, not even as a single curve, and nothing states
  which metrics were skipped. Two runs with disjoint keys → a table of `--`
  and zero charts, silently.
- **No N-run metric-curve overlay.** Multi Compare bar-charts only the latest
  value; overlaying training curves for 3+ runs — the most-asked question of a
  sweep — doesn't exist anywhere (the pair overlay is capped at 2).
- **No comparison export** — the computed comparison (param diff, deltas, code
  diff, multi table) can't be downloaded or copied in any format.
- **Multi Compare shows no params at all** — the "what config produced these
  numbers" half lives only in the matrix, which isn't linked from Compare.
- **No rank-basis choice in Multi Compare** (always last-per-key; the matrix's
  final/best switch has no counterpart, and the basis isn't stated).
- **No compare deep-link/URL state** — a comparison can't be shared or
  restored; combined with bug D1 there is no path to compare two specific old
  runs by id at all.
- **No polarity-override control on compare surfaces** — `setMetricPolarity`
  exists (localStorage) but only Pareto's goal selects expose it.

### From notebooks / Session Trees

- **No metric-level branch comparison inside a session** — `runCompare` shows
  type/cell-count/diff columns but not the per-node tagged metrics that
  already exist in the DB; comparing `val_acc` across branches requires
  materializing every branch first.
- **Materialized runs lack params + script** (parity hole above) — so
  leaderboard/param-study/Pareto over a finalized session's runs are mostly
  empty.
- **Cross-notebook model comparison relies entirely on manual `variant-of`** —
  model_a.ipynb vs model_b.ipynb never share a script, so no automatic
  baseline/delta exists; no "compare latest run of each notebook" affordance.
- **Session studies are name-keyed** — two sessions named "explore" in
  different notebooks merge their runs into one study.
- **`%%pin` accumulates a new artifact per Run-All pass** — documented, but it
  is the one magic exempt from the idempotency rule; users comparing variants
  via pins see duplicates.

### From the CLI

- **`ls` can't filter by script/model** — only `-n/--tag/--status/--study/
  --json`; no `--script`, no `param:<key>` filter, no date range. The
  "compare runs of different models" loop has no CLI entry besides tags.
- **The ranking layer is dashboard-only.** `leaderboard.py` (top_runs /
  best_so_far / pareto_front) and `param_study` have zero CLI surface — a
  terminal/SSH user (the SLURM audience) can't ask "best run by primary
  metric".
- **`compare` takes exactly 2 ids** — no N-way, no by-study compare.
- **The Trash is unreachable from the CLI for experiments**: `rm` is permanent
  and always takes output files (no `--keep-files`), there's no trash listing
  and no restore for experiments (sessions have all three). Trashed runs are
  also excluded from `clean --older-than`, so CLI-only users accumulate trash
  forever.
- **`rm`/`clean` have no `--yes`** — combined with the `EOFError` prompt bug,
  bulk deletion cannot be scripted at all.

## What shipped against this scope

Everything in the sections below landed in 1.4.0, including the feature themes.
For the record, the two places the delivered work deliberately differs from what
this document proposed:

- **"Interrupted" is a `failed` run carrying `_interrupted`, not a fourth
  status.** A new status value would have to be understood by every filter,
  baseline rule, cleanup path and glyph map (~50 call sites reference `failed`)
  to express something only the *reason* line needs to say.
- **The notebook duplicate-detection parity hole was not real** — see the note
  at the top of this file.

Two items were judged out of scope for a release focused on comparison and were
left as-is, with the reasoning recorded here rather than silently dropped:

- **A cross-metric ranking mode** (rank each run by *its own* primary metric, or
  by a normalized score). `consensus_metric` already refuses to rank runs judged
  by different keys and *says so*, which is honest; normalizing across metrics
  invents a common scale, which is the kind of claim `parameter_effects` is
  careful never to make. It wants a design pass, not an implementation.
- **`%%pin` accumulating an artifact per Run-All.** It is the one magic
  deliberately exempt from the idempotency rule — a pin is a timestamped trail
  of "this is what it looked like at this moment", and deduping it would lose
  the history it exists to keep.

## Proposed 1.4 scope

Five audits (run loop/capture, analysis, notebooks/sessions, dashboard, CLI/
storage) → ~55 verified findings. The whole suite is green on HEAD (1302
passed) and eslint is clean, so **none of these are caught by current gates**
— every fix below should land with a regression test. Suggested shape:

### 0. Ship-now patch candidates — all shipped in 1.4.0

The two silent-data-loss criticals plus the two cheapest severe traps. All four
are fixed; there was no separate 1.3.1 cut in the end, since the rest of the
scope landed in the same pass.

1. ~~`run-finish` argparse dest collision (CLI 1 / run-loop 1)~~ — **FIXED**
   (1.4.0): subparsers dest is now `_subcmd`, and `tests/test_cli_dispatch.py`
   parses every subcommand through `_build_parser()`, asserting no option can
   shadow the subcommand dest. `tests/smoke.py` now also drives the shell
   pipeline end-to-end (`run-start` → `run-finish --metrics` → `show`).
2. Migration stamping with columns still missing (CLI 2) — legacy DBs brick
   until a manual `upgrade`.
3. Ctrl-C leaves runs stuck `running` (run-loop 2).
4. `backup`/`restore` failures exit 0 (CLI 4) — silent forever-failing cron
   backups.

### 1. Trustworthy comparisons (bug-fix theme)

Every compare surface tells the truth, whichever models are being compared:

- Polarity: CLI `compare`/`watch` via `goal_for_key` (analysis 3); Multi
  Compare best/worst tint + epsilon (dashboard 2, 4).
- Honesty: step-less "last" value (analysis 1 — HIGH); normalized param
  comparison in `diff_runs`/`best_so_far`/`cmd_compare` (analysis 2); Multi
  Compare missing picks + POST conversion (dashboard 5, 11); pair-compare
  silent no-op (dashboard 1); canvas-id collision (dashboard 3); skipped-
  metrics notice; code-panel direction labels (dashboard 7).
- NULL/edge guards: `ls` crash (analysis 6), `_value_rows` min-goal NULL
  (analysis 5), ambiguous-prefix 500s (analysis 7), `api_pareto` basis
  (analysis 8), delete dead `get_all_latest_metrics` (analysis 9), `error`
  param onto `is_user_param_key` (analysis 11).

### 2. Different models are first-class (feature theme — the headline)

- **Script/model identity everywhere**: `script_differs` dimension in
  duplicate detection (fixes analysis 4); `ls --script` + a script filter in
  the dashboard; per-script grouping (or at least a script column) in the
  parameter matrix; stable pipeline identity for `run-start` (run-loop 7).
- **Metric-key aliasing**: a per-project alias map (`val_acc ≡ accuracy ≡
  train/acc`) consulted wherever metric keys are matched — compare, diff,
  consensus ranking, Pareto, charts. Unblocks cross-model comparison for
  models that name their metrics differently; also removes the canvas-
  collision trigger.
- **Compare view upgrades**: N-run metric-curve overlay (the most-asked sweep
  question, currently impossible); params in Multi Compare; rank-basis
  (final/best) switch; comparison export; compare deep-link/URL state.
- **CLI analysis surface**: `exptrack top` (leaderboard over primary metric)
  and N-way `compare` — the SLURM/SSH audience currently has no ranking
  entry point at all.

### 3. Notebook parity and Session Tree idempotency

- Run-All idempotency: `%%setup`-first branch forking (notebook 1),
  promote-then-rerun duplication (notebook 2), `session end` re-adopt
  (notebook 6), `%exp_note` dedup (notebook 7).
- Parity: `%exp_log` relative-path fix (notebook 3); HP-capture rename guard
  (notebook 4); metric-tag ownership (notebook 5); materialized runs get
  `script` + real params (parity hole — makes "compare graduated branches"
  actually work with param study/leaderboard); cell-lineage digest in the
  duplicate-detection code fingerprint so "same params + different code" is
  reachable for notebooks.
- Metric-level branch comparison in the Sessions compare view (the data is
  already tagged per node).

### 4. CLI safety and scripting

- One shared `confirm()` (EOF/Ctrl-C → clean cancel) + `--yes` on `rm`/
  `clean`; `clean` flag-combination fix; `compact` exit codes/id resolution/
  summary; config type coercion for non-numeric keys; `stale` + `deleted_at`;
  `clean --reset` counting session tables; `rename_output_folder` boundary
  match; experiment Trash from the CLI (`rm` soft-by-default or `trash`/
  `restore-run` commands + trash listing).

### 5. Smaller hardening (as time allows)

Run-loop 3/4 (output-scan cross-contamination + phantom trash), 5 (pipeline
code snapshot), 6, 8–15; notebook 8–12; dashboard 6, 8–10, 13; CLI 12–14;
reference-pinned-while-running policy (analysis 10); docs drift (top of this
file).

### Versioning

Shipped as **1.4.0** (minor: features + behaviour changes). `_SCHEMA_VERSION`
went 5 → 6: the migration fix adds the six legacy columns through a real
`_migrate_*` helper and reorders the helpers, which changes the stored DDL, so
existing databases must re-run the pass. `tests/test_db.py`'s schema fingerprint
was updated in the same commit.
