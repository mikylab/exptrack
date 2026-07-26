# exptrack Audit — "What did I run, what changed, and how do I go back?"

Audit of exptrack v1.38.1 against one core user job, stated by the project owner:

> I run a lot of experiments where I'm tweaking one or two lines at a time. I need to be
> able to go back later and answer "what did I actually run, and what changed between run N
> and run N+1?" Reverting to a prior state or figuring out what changed is painful today.
> I also need much better tracking of Jupyter notebook runs specifically — most of my
> iteration happens in notebooks, not scripts.

This document is a **handoff spec for an implementing agent with zero prior context**.
**Read Part 0 (background), then implement the LOOP-FIRST PLAN below — it is the whole
near-term scope.** Parts 1–5 are the audit findings (reference material: consult them for
file:line detail on each item you implement); Part 6 is the long-range phase map — do NOT
start Part 6 work that isn't listed in the loop-first plan without the owner asking.
Every finding carries file:line references checked against v1.38.1 (re-verify line numbers
before editing — the tree moves).

---

## START HERE — the loop-first plan

The owner's actual workflow, verbatim:

> change something → breaks the run → manually delete it (if I recall) → update code →
> rerun → see results/code changes, repeat. In a notebook: run, run, try/compare and see
> what is the best.

The goal is a **simple tool**: ease of use and data repeatability. Six items, in order,
each removing one manual step from that loop. Everything else in this document waits.

### L1 — Broken runs clean up after themselves (kills the "manually delete" step) · S
Scripts already mark crashed runs `failed` with a traceback. Notebooks never do (Part 2
gap: hooks ignore `error_in_exec`; atexit always finishes `done`) — fix that first.
Then: the dashboard experiment list and sidebar **hide failed runs by default** (a
"show failed (N)" toggle, persisted), and add `exptrack clean --failed` plus an optional
config `auto_trash_failed: true` that soft-trashes a failed run at finish (Trash is
already recoverable, so this is safe). Result: a broken run never needs remembering.

### L2 — Every run ends by telling you what changed (the core of the loop) · M
When a run finishes, compare it to the **previous run of the same script/notebook**
(one query: next-older `created_at`, same `script`) and emit a compact delta:
`vs run a3f2c1 (12 min ago): lr 0.01→0.02 · train.py +2/−1 lines · acc 0.84→0.87`.
Surface it twice: (a) printed to stderr at `finish()`/crash for script runs, (b) a
"vs previous" strip at the top of the dashboard detail view, expandable to the full
word-level diff (reuse `js/highlight.py` renderers). Code delta = compose the two runs'
`(commit, git_diff)` pairs for scripts, and the ordered cell records for notebooks —
script and notebook sections rendered separately (never notebook JSON; Design
constraint 1). This is finding-F-A/F-B scoped down to *adjacent runs only* — no general
N×N compare UI is needed for the loop.

### L3 — Every run can actually be rerun (repeatability) · S–M
Two fixes: (a) **the real command** — in pipeline mode the stored command is the
exptrack wrapper's own argv, never the `python train.py …` line (Part 1.4); add
`--cmd` to `run-start`/`run-finish` and snapshot the detected calling shell script's
content (content-addressed, tiny). (b) **the code** — store the run script's full
source in a content-addressed `code_snapshots` table (deduped: ten unchanged re-runs
store one copy; never `.ipynb`). The Reproduce box then shows a command that works and
code that exists.

### L4 — A notebook attempt = a run, with zero ceremony · S
Kernel restart already starts a new run. Add: detection of an in-kernel fresh start
(IPython `execution_count` reset — one integer compare per cell) and an explicit
`%exp_new` / `start(new=True)` fallback, so "run, run, run" in one kernel produces
comparable runs instead of one blob. No other magics required anywhere in this plan.

### L5 — "See what is best" is one click · S
Metric sort in the experiment table (the sort switch currently has no metric case) +
highlight the best value per metric column. Combined with L4, the notebook loop becomes:
run attempts → sort by accuracy → click the best one.

### L6 — Compare two attempts shows the cell edit · M
In the existing Compare view, add the run-vs-run **cell diff** for notebook runs
(align cells by lineage parent link, then by order; render with the existing diff
renderers) and stop stripping the code delta for script runs. Prerequisite for honest
output: the cell-lineage cross-notebook fix (Part 5.3) and the "git failure looks like
a clean tree" fix (Part 5.6) — do those two fidelity items as part of L6, skip the rest
of Part 5 for now.

**Explicitly deferred** (do not build now): Session Trees changes of any kind,
`exptrack checkout`/patch export, param history, environment capture, dataset-manifest
diffs, stderr/rich-output capture, manuscript export (revisit after L1–L6 are in daily
use). Resume-path fixes (Part 5.1) only matter if the owner starts using `--resume` —
defer unless asked.

**Acceptance for the loop-first plan:** break a script run → it's marked failed and
absent from the default list with nothing to delete; fix and rerun → the terminal and
detail view say exactly what changed and how the metric moved; `exptrack run-start` in
a bash script records the real python command; run three notebook attempts in one
kernel → three runs, sortable by metric, and Compare shows the one edited cell between
any two. Storage growth across unchanged re-runs ~zero; per-cell overhead unchanged;
zero required magics.

**This is a product-gap audit, not a code-quality audit.** The previous audit
(`AUDIT_IMPLEMENTATION_PLAN.md`, remediated in v1.36.x–1.38.x) covered crashes, XSS,
exit codes, and dead code. Nothing here duplicates it. Findings below are limited to things
that block the diff/revert/notebook job.

---

## Ground rules for the implementing agent

- **Branch:** develop on `claude/exptrack-audit-diff-revert-2uygzf`. Commit per phase,
  push with `git push -u origin claude/exptrack-audit-diff-revert-2uygzf`.
- **Tests:** `python -m pytest tests/ -x -q`. Keep the suite green after every phase.
- **stdlib only.** No new runtime dependencies (this includes `nbformat` — notebooks are
  JSON; parse them with `json` if needed).
- **Repo rules (CLAUDE.md):** every user-visible change updates (1) `CLAUDE.md` where
  documented behavior changes, (2) `CHANGELOG.md` (Keep-a-Changelog, bold short title per
  bullet), (3) `pyproject.toml` version. Schema changes require bumping `_SCHEMA_VERSION`
  in `core/db.py` (+1) or existing DBs never migrate.
- **Never let capture failure crash a user's run** — wrap new capture code in the existing
  `safe_call`/`debug_log` helpers (`core/utils.py`).
- Python floor is 3.8 (`pyproject.toml` `target-version = "py38"`); a 3.9-only syntax
  crash already shipped once (CHANGELOG 1.38.1) — don't use `X | Y` annotations without
  `from __future__ import annotations`.

## Design constraints (from the project owner — these override any conflicting finding below)

1. **Never reintroduce raw `.ipynb` content into `git_diff`.** The
   `git_diff_exclude: ["*.ipynb"]` default is a *deliberate* noise-control decision:
   raw notebook JSON diffs (base64 outputs, execution counts, metadata churn) bloat the
   record and drown the five-line script change the user actually needs to see. Notebook
   change tracking must come from the **cell layer** (already captured), rendered through
   better UI — not from whole-document JSON diffs. Any feature below that touches the
   notebook document must strip outputs/metadata and must never mix into the git diff
   view.
2. **Storage stays minimal.** Prefer *reconstruction from data already captured* over
   storing new copies. Anything new must be content-addressed + deduped (unchanged
   re-runs store ~nothing), output-stripped, and size-capped. The existing `git_diffs`
   dedup table (`resolve_git_diff`, `db.py`) is the pattern to follow.
3. **Notebook capture overhead must stay negligible per cell.** Long notebook sessions
   already pay per-cell hooks; new capture work may not add subprocess/git calls or
   heavy hashing per cell (the existing branch-diff throttle and lineage pruning are the
   precedent). Anything expensive runs at run boundaries, not per cell.
4. **No magic-every-other-line.** The Session Trees ritual (`%exptrack checkpoint`,
   `%exptrack branch`, quoted labels, magics per structural event) is too heavy.
   Structure should be **detected automatically** (edited re-run → implicit branch;
   kernel restart / Run-All → run boundary) with dashboard actions to name/curate after
   the fact. Magics remain as optional power-user overrides, never the required path.

---

## Part 0 — Background: what exptrack is and what it captures today

exptrack is a local-first, stdlib-only Python experiment tracker (SQLite WAL DB in
`.exptrack/experiments.db`). Three entry modes:

1. **Script runs** — `exptrack run train.py --lr 0.01` (`exptrack/__main__.py`) wraps the
   script via runpy; argparse/argv are monkey-patched to capture params.
2. **Notebook runs** — `%load_ext exptrack` (`exptrack/notebook.py`) installs IPython
   pre/post-cell hooks (`capture/notebook_hooks.py`); one experiment is auto-created on the
   first real cell and everything in the kernel session appends to it.
3. **Shell pipelines** — `exptrack run-start` / `run-finish` (`cli/pipeline_cmds.py`).

Per run, the `experiments` row stores `git_branch`, `git_commit` (short hash), and
`git_diff` = `git diff HEAD` at run start (`core/experiment.py:124-133`, `core/git.py:67-72`).
Scripts additionally get `_script_hash` (md5 of source) and `_code_changes` (a stripped,
1000-char-capped summary of changed lines) (`capture/script_tracking.py:17-68`). Notebook
cells get content-addressed lineage: full cell source in the `cell_lineage` table keyed by
`md5(source)[:12]`, a fuzzy parent link (≥30% SequenceMatcher similarity), per-cell
`cell_exec` timeline events with a 200-char source preview and a diff-vs-parent, plus
variable fingerprints (`capture/cell_lineage.py`, `capture/notebook_hooks.py`,
`capture/variables.py`). **Session Trees** (`exptrack/sessions/`) are an opt-in notebook
layer: explicit `%exptrack checkpoint/branch` magics record an exploration tree with cell
blobs and git diffs per node.

Diff/compare surfaces: CLI `exptrack diff <id>` (shows that one run's stored git diff),
`exptrack compare <id1> <id2>` (params/variables/metrics — no code), `exptrack history
<notebook>` (per-notebook cell history); dashboard detail view (per-run Code Changes +
Uncommitted Changes panels), Compare view (params/metrics/images — no code), Timeline
(per-cell view-source with diff-vs-parent), Sessions tab (tree + per-node diff).

**The one-sentence verdict:** exptrack records *each run against git HEAD at that moment*,
but has **no run-vs-run code diff anywhere, no snapshot sufficient to reconstruct what ran
in the common dirty/untracked/notebook cases, and no revert operation of any kind.** For
notebooks specifically, the run's `git_diff` column is empty by design (`*.ipynb` is
excluded by default), and the notebook document itself is never snapshotted.

---

## Part 1 — Gaps for the core use case

### 1.1 There is no run-vs-run code diff, anywhere

The user's central question — "what changed between run N and N+1" — has no supporting
surface:

- CLI `diff` takes a **single** id (`cli/main.py:228-229`); it shows that run's stored
  working-tree-vs-HEAD diff, nothing cross-run (`cli/inspect_cmds.py:300-322`).
- CLI `compare <id1> <id2>` compares params, final variables, and metrics only
  (`inspect_cmds.py:325-381`). It never reads `git_diff`, and it *silently drops* the
  `_code_changes` param because `_`-prefixed keys are skipped (`inspect_cmds.py:352-353`).
- Dashboard Compare explicitly filters code out: `isUserParam` strips `_code_change*`,
  `_script_hash`, `_var/` (`dashboard/static/js/compare.js:119`), and renders no diff even
  though both experiments' `git_diff` are in the fetched payload.
- Multi-compare (`core/queries.py:567-591`) doesn't even query params or diffs.

Each run's stored `git_diff` is relative to *that run's own HEAD*, so even manually
eyeballing two runs' diffs answers "what was dirty at each moment," not "what changed
between them." Computing A→B requires combining `(commit_A, diff_A)` and
`(commit_B, diff_B)` — data that exists in the DB but is never composed.

### 1.2 The per-run snapshot cannot reconstruct "exactly what ran"

`commit + git_diff` is the whole snapshot, and it breaks in the most common iteration
modes:

- **Untracked files are invisible.** `git diff HEAD` omits new files. A brand-new script,
  module, or config the run used is absent from the record, with no warning
  (`core/git.py:71`).
- **Script source is never stored.** `exptrack run train.py` stores only a 12-char md5
  (`capture/script_tracking.py:33-34`). If the script is untracked or the project isn't a
  git repo, the code that ran is unrecorded except that hash. (Notebook cells, by
  contrast, get full source in `cell_lineage` — the asymmetry favors notebooks here.)
- **Non-git projects get nothing.** `project_root()` accepts a bare `.exptrack/` dir
  (`config.py:57-68`); every git call then returns `""` (`git.py:45-48`), stored as
  empty — indistinguishable from a clean tree (see 5.6).
- **`*.ipynb` is excluded from `git_diff` by default** (`config.py:19`) — this is
  *deliberate and must stay* (Design constraint 1: raw notebook JSON diffs drown real
  script changes). The consequence to fix is not the exclusion itself but that nothing
  else fills the gap: a notebook run's code record must come from the cell layer, and
  today no surface composes the cell records into a run-level "what ran / what changed"
  view (see Part 2).
- **>256 KB diffs are truncated mid-hunk** with an inline marker
  (`experiment.py:130-132`) — flagged, but no longer an applicable patch.
- **The commit is a short hash and nothing pins it.** exptrack never creates a commit,
  stash, tag, or ref; a later rebase/gc can orphan the recorded commit, and
  `commit + diff` stops being reconstructable.
- **Config files, pip environment, and seeds are not captured.** Only `python_ver` and a
  best-effort `_gpu` param (`experiment.py:136-145`). A YAML/JSON config the script reads
  appears only if it happens to be a tracked, modified file.

The dataset manifest (`core/dataset.py`) partially covers data inputs, but only on
successful `finish()` (failed runs get none, `experiment.py:524-525`), only for
param-shaped paths, with directories fingerprinted by name+size only (in-place content
changes invisible) — and there is no manifest-vs-manifest diff between runs.

### 1.3 There is no revert path at all

Grep for `git apply|git stash|git checkout|git reset|format-patch` across `exptrack/`
finds nothing. Concretely:

- The dashboard Reproduce box emits only the stored command line
  (`dashboard/static/js/detail.js:527`) — no `git checkout <commit>`, no patch
  application.
- "Export Diff" downloads **markdown**, not an applyable `.patch`
  (`dashboard/static/js/mutations.js:97-107`, `routes/write_routes.py:478-493`).
- Session Trees are explicitly "the map, not a time machine"
  (`docs/session-trees.md:513-516`); `promote_to_checkpoint` only relabels a node
  (`sessions/lifecycle.py:449-476`).
- The only "restore" verbs in the codebase are Trash-undelete (DB rows), never code.

Reverting today means: find the run, read its short commit hash off the screen, manually
`git checkout` it, then hand-reapply the stored diff (if it wasn't truncated, excluded, or
compacted away).

### 1.4 The recorded command is the wrapper's argv, not what actually ran

`experiments.command` is filled by `Experiment._build_command()` = the **exptrack
process's own `sys.argv`** (`core/experiment.py:205-214`, stored at `_save`,
`experiment.py:254`). This is correct for `exptrack run train.py --lr 0.01`, but in the
shell/SLURM pipeline mode it is structurally wrong: `eval $(exptrack run-start --lr
0.01)` stores the command as `exptrack run-start --lr 0.01` — **the actual `python
train.py ...` invocation that runs afterward is never seen by exptrack and is absent
from the record.** `_detect_calling_script` (`cli/pipeline_cmds.py:78-136`) walks the
process tree and stores the invoking *shell script's path* as `script`, but never
captures its content or the python line(s) inside it. So for bash-script runs the
Reproduce box and `command` column show only the exptrack bookkeeping call — the python
part is "cut off" because it was never captured. (`run-finish` captures nothing about
the command either.) Fix in Phase 2 (F-N): let `run-start`/`run-finish` accept the real
command explicitly, and snapshot the detected calling script's content
(content-addressed — shell scripts are tiny) so the full pipeline is reconstructable.

### 1.5 "Which run was N−1?" has no answer either

The only latest-run lookup in the codebase (`__main__.py:210-227`) exists solely to power
`--resume`. No CLI command or dashboard button expresses "diff/compare this run against
the previous run of the same script/notebook." The experiment table can't even sort or
filter by metric (`dashboard/static/js/table.js:250-282` — sort switch has no metric
case; search doesn't match metrics), so "find the best run, then see how its code differs
from mine" is unsupported end to end.

---

## Part 2 — Jupyter notebook tracking

### 2.1 What exists today (and it's a real foundation)

Per executed cell (`capture/notebook_hooks.py:462-547,670-712`):
full source stored content-addressed in `cell_lineage` (with fuzzy parent link + diff),
a `cell_exec` timeline event (seq, exec-order position, 200-char preview, diff-vs-parent
capped at 20 KB, output preview capped at 4 KB), variable-change events with
fingerprints, `_var/<name>` params, HP auto-promotion for regex-matched scalar names, and
`plt.savefig` artifact capture. The ordered list of *executed* cell sources for one run
**is** reconstructable (join timeline → cell_lineage; `cli/inspect_cmds.py:507-559` does
this for `history`).

### 2.2 Where it falls short of scripts (parity gaps)

| Dimension | Script run | Notebook run |
|---|---|---|
| Params | Structured argparse/argv capture | Regex-guessed scalar vars only; `cfg` dicts become one opaque `_var/` blob |
| git diff | Full uncommitted `.py` diff vs HEAD | **Empty by default** — `git_diff_exclude = ["*.ipynb"]` (`config.py:19`) strips the notebook's own changes |
| Whole-document snapshot | (none either — see 1.2) | `.ipynb` never parsed or snapshotted; no `nbformat`-equivalent code exists |
| Failure status | `fail()` + traceback via crash handler | **Never marked failed** — hooks ignore `result.error_in_exec` (`notebook_hooks.py:274-313,715-762`); atexit always finishes `done` (`notebook.py:111-118,344-346`) |
| Run boundary | One process = one run | One **kernel session** = one run; re-running all cells without restart stays the same experiment, so "yesterday vs today" is often not even two runs |
| Command/reproduce | Real argv command stored | `script="notebook"`, no runnable command |
| Resume | `--resume` aggregates | No cross-kernel resume |
| Output capture | stdout/stderr tee'd to log files | stdout + trailing-expr repr only; **stderr, `display()`, rich reprs, inline images not captured** (`notebook_hooks.py:101-151`) |

### 2.3 Notebook-specific record-fidelity problems

- **`notebook_history` snapshots are dead by default.** The rich per-execution JSON
  snapshot writer early-returns because `notebook_history` defaults to `False`
  (`config.py:47`, `notebook_hooks.py:780-782`) — yet `cmd_history`, delete-preview,
  cleanup, and compaction code all still operate on the (empty) directory. Either turn it
  on, or fold its value into the DB path and delete it.
- **Cell layout is not captured.** `cell_pos` is a tracked-execution counter, not the
  notebook's spatial position (`notebook_hooks.py:676-677`). Reordering and out-of-order
  execution are invisible; markdown and unexecuted cells are never seen.
- **Lineage is keyed by best-effort notebook *name*.** `_detect_nb_name` is a 6-strategy
  heuristic that often returns `""` → default `"notebook"` (`notebook.py:157-277,363`), so
  undetected notebooks share one lineage namespace and cross-contaminate parent matching.
  Worse, the content-addressed cache ignores the notebook entirely (see 5.3).
- **Fuzzy lineage drops heavy edits.** A cell edited >70% falls below the 0.30 similarity
  threshold and is recorded as brand-new (`cell_lineage.py:40,132`), losing exactly the
  "what changed" link for big rewrites; shared boilerplate can grab false parents.
- **>50 KB cells are stored truncated but hashed untruncated**
  (`cell_lineage.py:151-163`) — the stored source no longer matches its identity hash.
- **Docs claim SHA-256 cell hashing; the code uses md5[:12]**
  (`docs/how-it-works.md:16,62` vs `cell_lineage.py:14-16`). Fix the docs (or the hash —
  see Phase 2).

### 2.4 What parity-or-better looks like (within the design constraints)

**Do NOT snapshot the `.ipynb` document.** Raw notebook JSON is exactly the bloat the
owner removed from git diffs (Design constraint 1), and full-document snapshots violate
the storage constraint. The right observation is that **exptrack already stores, at zero
additional cost, everything needed to reconstruct "what ran": the ordered, full-source,
executed-cell sequence per run** (timeline `cell_exec` events → `cell_lineage.source`;
`_history_from_db` at `cli/inspect_cmds.py:507-559` already does the join). What's
missing is not capture — it's composition and UI.

So the parity target is:
(a) a **run manuscript view** — one page/command that renders a run's executed cells in
order, with outputs, as "this is what ran" — plus **export as `.py` or a clean
output-stripped `.ipynb`** so the run can be *repeated* (this is the show/repeat UI; new
storage: zero);
(b) **automatic run boundaries** — kernel restart already starts a new run; add cheap
detection of an in-kernel fresh start (see Phase 2) with an explicit `%exp_new`/UI
fallback — no per-cell cost;
(c) **failure status with traceback** (capture fix, one hook read);
(d) **structured params** from plain variables and config dicts (extends the existing
single-pass variable capture — no new per-cell passes);
(e) a **run-vs-run cell diff view** ("run 12 vs 13: cell 4 changed
`threshold=0.7 → 0.5`"), rendered from cell records, never from notebook JSON.

Everything above reuses captured data; only (c) and the boundary marker touch the
capture hot path, and both are O(1) per cell.

---

## Part 3 — Usability friction (data exists, but the loop is manual)

1. **The captured code data is unreachable from every comparison surface.**
   `git_diff` renders only in single-run views; `_code_changes` renders only in the
   single-run detail panel and is filtered out of both CLI and dashboard compare
   (`inspect_cmds.py:352-353`, `compare.js:119`). The user must open two runs in two
   tabs and mentally diff two HEAD-relative diffs.
2. **No "previous run" affordance.** No compare-with-previous button on the detail view,
   no `exptrack diff <id> --against prev`, no adjacency concept (Part 1.4).
3. **Cell sources are behind hashes.** Full source is reachable only via the per-run
   timeline "view source" button per cell (`/api/cell-source/<hash>`); there is no
   "show me all of run X's cells" page, and no way to pick run A's cell vs run B's cell.
4. **No metric sort/search** in the experiment table (`table.js:250-282`) — finding the
   known-good run is a visual scan.
5. **The CLI `compare` delta coloring hard-codes "lower is better"**
   (`inspect_cmds.py:378-379` — green when `d < 0`), actively mis-signaling accuracy/F1
   comparisons.
6. **Session Trees demand a heavy ritual** (quoted label magics for every structural
   event; branch requires a prior checkpoint) and give no automatic
   checkpoint/divergence detection — the user who forgot the ritual before a breaking
   change has no known-good node (`capture/session_hooks.py:38-143`,
   `docs/session-trees.md:519`).
7. **Session branch comparison shows no code.** `runCompare` renders `+N/−M` counts,
   result reprs, and thumbnails per column (`sessions.js:847-884`) — the captured
   `cell_source` blobs are never diffed against each other, and the per-node
   "defining change" is a one-line heuristic guess (`sessions.js:651-671`).
8. **`exptrack diff`'s empty state lies.** "No uncommitted changes were captured … (All
   changes were committed)" (`inspect_cmds.py:308-310`) prints identically for a genuinely
   clean tree, a git failure, and a non-git project.
9. **Docs never answer the two core questions.** No page in `docs/` covers "how do I see
   what changed between two runs" or "how do I get back to a prior state" (grep for
   revert/"what changed" across docs/ returns nothing).
10. **Compaction destroys the only code record.** `cmd_compact`/`_compact_git_diffs`
    overwrite `git_diff` with a `[compacted — see git commit X]` marker
    (`cli/admin_cmds.py:366`, `routes/write_routes.py:385`) assuming the changes were
    committed — exptrack never commits them, so compacting uncommitted-diff runs deletes
    the record; the recovery hint `git diff {commit}~1 {commit}`
    (`inspect_cmds.py:314`) points at the wrong delta.

---

## Part 4 — Feature candidates, ranked by leverage vs effort

Ranked for the core job. Effort: S (<1 day), M (1–3 days), L (multi-day).
Items marked ★ are in the execution phases (Part 6); the rest are follow-ups.

| # | Feature | Leverage | Effort | Why |
|---|---|---|---|---|
| ★F-A | **Run-vs-run code diff** — `exptrack diff A B` + a Code section in dashboard Compare. Reconstruct each run's code state (commit + stored diff, per-file), then diff the two states; for notebook runs, diff the ordered **cell records** (align by lineage parent links, then by position) — never raw notebook JSON. Script and notebook diffs render as separate sections so a notebook can never drown a 5-line script change. | Very high — *is* the core question | M | Data already captured; pure composition + rendering (reuse `_renderUnifiedDiff`/word-diff in `js/highlight.py`). New storage: zero |
| ★F-B | **"Compare with previous run"** — adjacency (previous run of same script/notebook) exposed as a detail-view button and `exptrack diff <id> --prev`; auto-open the code diff | Very high — removes the find-N−1 step | S | One query (`ORDER BY created_at DESC` per script) + wiring |
| ★F-C | **Per-run script/untracked-file snapshot** — store the run script's full source + untracked `.py`/config files, size-capped, **content-addressed + deduped** in a new `code_snapshots` table so an unchanged re-run stores nothing new. **Scripts and small text files only — never `.ipynb` documents** (notebook state is already fully covered by cell records; snapshotting the JSON would duplicate it as bloat). | Very high — makes reconstruction possible in the dirty/untracked/non-git cases where git_diff fails today | M | Prerequisite for trustworthy F-A/F-D. Storage: one copy per *distinct* script version, typically KBs |
| ★F-N | **Capture the real command in pipeline runs** — `run-start --cmd "python train.py ..."` / `run-finish --cmd`, plus auto-snapshot of the detected calling shell script's content (content-addressed via F-C's table; shell scripts are tiny) so the `python ...` line is never lost (fix for gap 1.4) | High — the record currently omits what actually ran in every bash/SLURM pipeline | S | `_detect_calling_script` already finds the file; store its content + accept an explicit command |
| ★F-D | **Revert affordances** — `exptrack checkout <id>` (restore snapshot to working tree with safety checks, or emit exact git commands), patch export as applyable `.patch`, copyable `git checkout <commit>` in the Reproduce box; notebook side restores via the F-O manuscript export (writes `<name>.exptrack-restore.ipynb`, never touches the live notebook) | Very high — the stated pain | M | Builds on F-C/F-O; the "emit commands + .patch" half is S |
| ★F-O | **Run manuscript view + repeat export** — one dashboard page / `exptrack manuscript <id>` that renders a run's executed cells in order with outputs ("this is what ran"), exportable as `.py` or a clean output-stripped `.ipynb` to re-run | Very high for notebooks — the show/repeat UI the owner asked for | S–M | Pure composition of timeline + cell_lineage (join already exists in `_history_from_db`). New storage: zero |
| ★F-E | **Notebook run boundaries + failure status** — auto-boundary on kernel restart (exists) + cheap in-kernel fresh-start detection with `%exp_new`/UI fallback; mark runs failed from `error_in_exec` with traceback | High — without run boundaries, notebook run-vs-run diffing has nothing to bite on | S–M | Capture-side, O(1) per cell |
| ★F-H | **No-magic session structure** — auto-branch when a previously-run cell is re-executed with edits (lineage already computes `is_rerun`/`code_changed` per cell — zero added per-cell cost); auto-labels from the defining change; name/curate/checkpoint from the dashboard afterward. Magics become optional overrides. | High — directly removes the magic-every-other-line ritual | M | Elevates Session Trees from opt-in ritual to ambient record |
| ★F-F | **Structured notebook params** — capture config-dict fields (`config = {...}` → `config.lr` params) and drop the regex gate for simple scalar assignments, so notebook HPs diff as cleanly as argparse ones | High | M | Extends the existing single-pass variable capture; no new per-cell passes |
| F-G | **Metric sort/filter in the table** + "best run" jump | Medium-high | S | Unblocks "find known-good" |
| F-I | **Session sibling cell-diff** — in `runCompare`, diff the two branches' `cell_source` blobs cell-by-cell | Medium | S | Data captured; renderer exists |
| F-J | **Environment capture** — installed-package list (via `importlib.metadata`, stdlib) + seeds param convention, captured once per run at start (not per cell); diff in compare view | Medium | S | Cheap, closes "same code, different result" holes |
| F-K | **Param history table** — append-only param log so resume/re-log keeps prior values (see 5.2) | Medium | M | Fidelity for resumed runs |
| F-L | **Dataset manifest diff** in compare ("data changed: train.csv hash differs") | Medium | S | Manifests exist; compare doesn't read them |
| F-M | **Stderr + rich-output capture for notebook cells** | Low-medium | M | Completes the record; not diff-critical. Respect output caps — storage constraint |

---

## Part 5 — Bugs/debt that directly block the core job

Only fidelity/diff/revert-relevant items. Each phase in Part 6 assigns them.

### 5.1 Resume freezes a stale code record (CRITICAL)
`Experiment.resume()` copies `git_branch/git_commit/git_diff` from the stored row and
never re-runs `git_info()` (`core/experiment.py:162-202`; capture happens only in
`__init__:124-133`). Resume a run after editing code and the record points at the *old*
commit and diff — the exact misleading record this tool exists to prevent. The pipeline
path is worse: `run-start --resume` re-captures nothing at all, not even the script hash
(`cli/pipeline_cmds.py:192-212`), while `__main__.py:114` at least re-runs
`capture_script_snapshot`. **Fix:** on resume, re-capture git state; don't overwrite —
append (log a `resume` timeline event carrying the fresh `{branch, commit, diff}`; if
code differs from the stored snapshot, also update the row and keep the original in the
timeline event so both states survive). Untested today: `tests/test_resume.py` never
asserts git fields after resume.

### 5.2 Param overwrites destroy history
`_write_params` upserts in place (`experiment.py:300-324`); a resumed run or re-run
notebook cell that changes `lr` clobbers the old value (warning only, suppressed for
`_`-keys — so `capture_script_snapshot` on resume silently replaces the original run's
`_script_hash`/`_code_changes`, `script_tracking.py:34,60`). Metrics are append-only with
no resume marker, so overlapping steps interleave two attempts' points
(`experiment.py:409-455`). **Fix:** minimum viable — before overwriting a param with a
different value, log a `param_change` timeline event with `{key, from, to}` (timeline
already has `prev_value`); full fix is F-K.

### 5.3 Cell lineage cache ignores the notebook → phantom parents
`cell_lineage.cell_hash` is the PK with content-only md5 (`db.py:293-299`,
`cell_lineage.py:14-16`), and `lookup_stored_parent` queries by hash with **no notebook
filter** (`cell_lineage.py:43-66`; trusted at `notebook_hooks.py:352-354`). An identical
cell in notebook B inherits notebook A's parent link — B's timeline shows a phantom
"edited from" diff. **Fix:** key lineage by `(notebook, cell_hash)` (schema migration +
`_SCHEMA_VERSION` bump) or add the notebook filter to the lookup; add a two-notebook test
(none exists — `tests/test_cell_lineage.py` uses a single name throughout).

### 5.4 Notebook runs can never fail (and the run boundary is the kernel)
See 2.2/2.3 — no `error_in_exec` handling, atexit always `done`, and re-running without
restart never creates a new run. Both halves are Phase 2.

### 5.5 Session Trees fidelity holes
(a) In the no-commit loop every checkpoint stores the same cumulative `git diff HEAD`,
not the per-attempt delta (`sessions/manager.py:474-483`); (b) checkpoint diffs never
refresh while cells accumulate on them — only branches refresh
(`manager.py:284-294`); (c) Run-All on a colliding branch re-appends its cells — dedup
only checks the last segment (`manager.py:250,563-586`) — inflating the record until the
256 KB budget silently elides the *earliest* cells (`_shared.py:21`,
`manager.py:264-269`), which are exactly the setup cells promotion needs; (d) window
metric attribution breaks under interleaved branch work
(`sessions/materialize.py:249-287` — upper bound is the next node *created anywhere in
the session*). Fix (a)–(c) in Phase 4; (d) document the limitation or bound by
node-switch events.

### 5.6 Git failure masquerades as a clean tree
`_git()` returns `""` on any error (`git.py:45-48`); empty diff renders as "All changes
were committed" (`inspect_cmds.py:308-310`). **Fix:** distinguish "no changes" from
"capture failed" — store a sentinel (e.g. `git_diff = "[capture-failed: <reason>]"` or a
`git_state` column: `clean|dirty|no-git|error`) and render honestly.

### 5.7 Compaction can destroy uncommitted-diff records
See friction #10. **Fix:** refuse to compact a run whose `git_diff` is nonempty unless
its content is reachable from the recorded commit (or simply: only compact when the diff
is empty/whitespace; otherwise require `--force` with a red warning), and fix the
recovery hint.

### 5.8 Minor but real
- >50 KB cell source truncated but hashed untruncated (`cell_lineage.py:151-163`) —
  store a `truncated` flag and hash what's stored, or raise the cap.
- `_snapshot_hash` dedup is advertised but never read (`experiment.py:153-154,219`) —
  delete or implement; misleading either way.
- `id()`-based variable fingerprints churn (Tensors over cap, big lists/dicts,
  unreprable objects → false "changed" every cell; `variables.py:209,217,224,231`) —
  extend `_stable_sig` fallbacks.
- `batched_writes` commits partial batches on mid-body exception and burns seq numbers
  (`experiment.py:278-298,589,605`) — acceptable, but stop committing when the body
  raised.
- CLI compare's inverted delta color (`inspect_cmds.py:378-379`) — color by
  higher/lower neutrally, or use the result-type direction list the dashboard has.
- Docs say SHA-256; code is md5 (`docs/how-it-works.md:16,62`).
- `code_baselines` is written on every cell but read by no live diff path
  (`cell_lineage.py:190-222`, `notebook_hooks.py:379-381`) — retire after Phase 2 lands.

---

## Part 6 — Execution sequence

Implement in order; each phase is independently shippable and keeps the suite green.
Version bumps: Phase 1 = patch; Phases 2–5 = minor each (schema/feature changes).

### Phase 1 — Make the existing record trustworthy (fixes: 5.1, 5.2-min, 5.3, 5.6, 5.7, CLI color, docs-hash)
The diff features in later phases are worthless if the underlying record lies.
1. Re-capture git state on `Experiment.resume()` and in `run-start --resume` (also call
   `capture_script_snapshot` there); append the fresh state to the timeline `resume`
   event, update the row, keep the original in the event payload. Tests: resume after
   editing a tracked file → row's `git_diff` reflects the edit AND the resume timeline
   event carries both states.
2. `param_change` timeline event on any param overwrite with a different value
   (including `_`-keys). Test: resume + re-log `lr` → old value recoverable from
   timeline.
3. Key `lookup_stored_parent` by notebook (schema: composite key or filter; bump
   `_SCHEMA_VERSION` if schema changes). Test: identical cell in two notebooks → no
   cross-notebook parent.
4. `git_state` honesty: sentinel for capture failure vs clean; update `cmd_diff` and the
   dashboard empty-state copy. Test: non-git project → diff view says "not a git repo /
   capture failed," not "all committed."
5. Compaction guard (5.7) + fix the `~1` recovery hint.
6. CLI compare delta color neutrality; docs md5 correction.

### Phase 2 — Capture what actually ran (F-C, F-N, F-E, F-F, F-O; fixes 1.4, 2.3 items, 5.8 cell-truncation)

Storage rule for everything in this phase: content-addressed + deduped; an unchanged
re-run stores ~nothing. Perf rule: nothing here adds work inside the per-cell hooks
except O(1) flag reads.

1. **`code_snapshots` table** (content-addressed: `hash` PK, `path`, `content`, `kind`
   `script|untracked|shellscript`, `created_at`; runs reference snapshots via a join
   table or a `_code_snapshot` param listing hashes). On script runs: store the script's
   full source + any untracked `.py`/small config files under a size cap (config
   `snapshot_max_kb`). **Explicitly excluded: `.ipynb` files** (Design constraint 1 —
   notebook state comes from cell records; the JSON document is bloat). Dedup by hash;
   snapshot at run start (a boundary, not per cell). Bump `_SCHEMA_VERSION`.
2. **Real command for pipeline runs (F-N, fixes 1.4):** add `--cmd "python train.py …"`
   to `run-start` and `run-finish` (last writer wins) so the actual training command
   lands in `experiments.command` instead of the exptrack wrapper argv; when
   `_detect_calling_script` finds the invoking shell script, snapshot its content into
   `code_snapshots` (kind `shellscript`) so the full pipeline is reconstructable even
   without `--cmd`. Update the pipeline docs/examples to show `--cmd`. Tests: run-start
   inside a fake bash parent → command column contains the python line; shell script
   content retrievable.
3. **Notebook failure status:** read `result.error_in_exec` / `error_before_exec` in
   `_post_run_cell`; record an `error` timeline event with the formatted traceback; a
   run with an unhandled final error finishes `failed` (atexit checks a
   last-cell-errored flag; an explicit `done()` still wins). Tests with the existing
   mock-IPython fixtures.
4. **Notebook run boundaries:** add `%exp_new` (and `start(new=True)`) that finishes the
   current run and starts a fresh one *without* kernel restart; also detect the cheap
   automatic case — IPython's `execution_count` regressing or restarting at 1 signals a
   fresh kernel/Run-All context (one integer compare per cell, no heuristics beyond
   that). Document "Run All → new run" as the recommended loop.
5. **Structured notebook params:** in `_capture_variables`, flatten small dicts named
   like configs (`config`, `cfg`, `params`, `args`, `hparams`) into dotted params
   (`config.lr`), and promote simple top-level scalar assignments (int/float/bool/short
   str) to params without the `_HP_RE` gate (keep `_var/` for the rest). Cap count.
   This extends the existing single fingerprint pass — no additional per-cell pass.
6. **Run manuscript + repeat export (F-O):** `exptrack manuscript <id>` and a dashboard
   "What ran" tab rendering the run's executed cells in order (join timeline →
   cell_lineage, as `_history_from_db` already does) with outputs; export buttons write
   `.py` (cells concatenated with `# %% cell N` markers) or a minimal output-stripped
   `.ipynb` built with `json` (nbformat v4 skeleton — stdlib only). Zero new storage.
7. Fix the >50 KB cell hash/truncation mismatch (5.8).

### Phase 3 — The diff surfaces (F-A, F-B, F-G, F-L)
1. **`exptrack diff <id1> <id2>`** (and `--prev`): reconstruct each run's per-file code
   state (Phase 2 snapshots when present; else commit+diff composition via
   `git show <commit>:<path>` + apply stored diff in-memory), then unified-diff A→B
   per file. For notebook runs: align cells by lineage parent chain then by order; emit
   per-cell diffs. Also print param/metric deltas (superset of today's `compare`).
2. **Dashboard:** "Code" section in Compare (reuse `_renderUnifiedDiff` + word-level
   pills from `js/highlight.py`); "⇄ vs previous run" button on the detail header; new
   endpoint `GET /api/code-diff?a=<id>&b=<id>` in `read_routes.py` doing the same
   composition server-side.
3. **Adjacency:** `previous_run_id` resolved at query time (same script/notebook,
   next-older `created_at`), exposed in `get_experiment_detail`.
4. Metric sort in the table + dataset-manifest row in Compare ("data unchanged ✓ /
   train.csv changed").

### Phase 4 — Revert (F-D) + no-magic sessions (F-H) + Session Trees fidelity (5.5, F-I)
1. **Patch export:** `exptrack export-patch <id>` and a dashboard button — write the
   stored diff as a real `.patch` (refuse politely when truncated/compacted, saying
   why). Reproduce box gains copyable `git checkout <commit>` (+ `git apply` line when a
   patch exists).
2. **`exptrack checkout <id>`:** with a clean working tree (else refuse, suggest stash):
   `git checkout <commit>`, apply the stored patch, restore any Phase-2 script/untracked
   snapshots, and for notebook runs write the F-O manuscript to
   `<name>.exptrack-restore.ipynb` (never overwrite the user's live notebook). Print
   exactly what was done and how to undo it. This is the "go back to run N" verb.
3. **No-magic session structure (F-H):** the per-cell lineage already computes
   `is_rerun`/`code_changed`/`parent_hash` — when a cell that previously ran is
   re-executed *edited*, auto-open a branch node under the last implicit checkpoint
   (auto-label from the first changed line, reusing the `_definingChange` idea
   server-side); kernel-restart/`%exp_new` boundaries create implicit checkpoints.
   Zero new per-cell computation (it keys off flags the hook already has). Dashboard
   gains rename/curate/promote actions so structure is named *after the fact*; the
   existing magics keep working as overrides. Gate with a config key
   (`sessions.auto: true` default off initially) so behavior is opt-out-able.
4. Session Trees fidelity: per-attempt checkpoint deltas (diff the node's cell/code
   state against the *previous checkpoint node's* recorded state, not HEAD), refresh
   checkpoint diffs on record_cell like branches (respect the existing throttle),
   fix Run-All duplicate-append (dedup against the full existing segment list, not just
   the last), and cell-level sibling diff in `runCompare` (F-I).

### Phase 5 — Docs + guardrails
1. New doc `docs/comparing-runs.md`: "what changed between two runs" (CLI + dashboard
   walkthrough) and "reverting to a prior run" (checkout/patch flow, what's restorable
   vs not — kernel state is not).
2. Tests locking the core loop: git-diff truncation behavior; resume-git recapture;
   two-notebook lineage; notebook failure status; run-vs-run diff golden outputs;
   checkout round-trip in a tmp git repo.
3. Update `docs/how-it-works.md` (hash claim), `docs/session-trees.md` (new diff
   behavior), CLAUDE.md architecture map, CHANGELOG, version bumps per phase.

### Acceptance for the whole effort
From a fresh project: run a script twice with a one-line edit → `exptrack diff --prev`
shows exactly that line; do the same in a notebook (two runs, boundary via restart or
`%exp_new`) → per-cell diff shows the edited cell, and a mixed script+notebook change
renders as separate sections (the notebook never drowns the script's five lines);
`exptrack run-start` inside a bash script records the real `python …` command;
`exptrack manuscript <id>` exports a re-runnable record of a notebook run;
`exptrack checkout` of run 1 restores its code; resume run 2 after another edit → the
record shows the new state with the old preserved in the timeline. Constraint checks:
no `.ipynb` content in any `git_diff`; DB growth across ten unchanged re-runs is ~rows
only (snapshots dedup to zero); per-cell hook time is unchanged within noise; the whole
notebook flow above requires zero magics except the optional `%exp_new`. Test suite
green throughout.
