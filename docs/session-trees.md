# Session Trees

Session Trees are an **opt-in** layer for exploratory notebook work. They record
the *shape* of your thinking — checkpoints, branches, and dead ends — as a
navigable tree, on top of standard `%load_ext exptrack` tracking.

> **Nothing changes unless you ask for it.** Without `%exptrack session start`,
> every other session magic is a silent no-op and your existing notebook
> tracking is unaffected.

## When to reach for it

Reach for Session Trees when you find yourself:

- Trying many small variations and losing track of which one was promising
- Wanting a per-checkpoint git diff (not just an end-of-run blob)
- Wishing your future self knew *why* you went down a path, not just what ran

If you're running one training script start-to-finish, you probably don't need
this — `%load_ext exptrack` alone is enough.

## The magics

```python
%load_ext exptrack                       # required — normal tracking
%exptrack session start "name"           # required — turns Session Trees on
%exptrack checkpoint "label"             # snapshot a stable point
%exptrack branch     "label"             # declare intent before diverging
%%scratch                                # cell magic — runs but is never logged
%%setup                                  # cell magic — runs, recorded as demoted prep (not in lineage)
%%pin "label"                            # cell magic — runs, snapshots cell + output as artifact
%exptrack promote    "label"             # link active experiment to current node
%exptrack session end                    # close — open branches → abandoned
```

### Three tiers of cell

Most cells in an exploratory notebook aren't the experiment itself. exptrack
gives you three levels so the timeline shows the *story*, not every keystroke:

| Cell | Logged? | Use for |
|---|---|---|
| normal cell | **fully** (lineage, variable diffs, timeline) | the actual model / train / eval code — the story |
| `%%setup` | **demoted** — recorded on a side store, kept out of lineage/diffs | prep you reference later (load data, build a transform) but that isn't the experiment |
| `%%scratch` | **never** | throwaway pokes — `df.head()`, a sanity print, a debug shape check |

Reaching for `%%scratch` aggressively (it's most of your cells) and `%%setup`
for prep is the single biggest lever for an uncluttered, traceable timeline.

## Timing — before or after a change?

This is the most important part to get right.

| Magic | Run it… | Mental model |
|---|---|---|
| `session start` | **once, at the top of your exploration** | "I'm about to poke around — record the shape of it" |
| `checkpoint` | **after** a change that worked, that you might want to return to | "Save point. If the next thing breaks, I can come back here." Snapshots a per-checkpoint git diff (vs. the previous checkpoint commit, falling back to `git diff HEAD`). |
| `branch` | **before** you start diverging | "I'm about to try X instead of Y. Here's why." Attaches under the most recent checkpoint. |
| `%%scratch` | **on the first line** of a throwaway cell | "This is a typo fix / sanity check / quick print — don't pollute the timeline." |
| `%%setup` | **on the first line** of a prep cell | "This builds something I'll use later (a `df`, a transform), but it isn't the experiment." Recorded on the active node's *demoted* setup store + a muted `setup` event on the run — kept out of cell lineage, variable tracking, and git diffs. **Scoping is positional**: a `%%setup` cell lands on whatever node is active when it runs. Run it *on the shared checkpoint, before branching*, for prep common to every branch. ⚠️ But note `materialize_experiment`/promote replay only a node's **own** setup cells, not an ancestor's — so if you want a promoted branch to be self-contained, run its `%%setup` *inside the branch*. |
| `%%pin "label"` | **on the first line** of a cell whose output you want frozen | "This is the moment I want to remember." Runs the cell, captures stdout + the trailing expression's repr, and saves `pin_<timestamp>_<label>.md` as an artifact on the active experiment. Also annotates the current session node if one is active. |
| `promote` | **after** a run completes (an `Experiment` is active) | "This branch is worth a real experiment record." Sets `experiments.session_node_id` and adds a `→ exp <id>` badge to the node in the dashboard. |
| `session end` | **when you're done** | "Close the book." Any branch with no descendant checkpoint flips to *abandoned* — still visible in the tree, just dashed and dimmed. |

### Why the order matters

`checkpoint` snapshots state. If you run it *before* the change, the diff is
empty. Run it *after* the change is stable.

`branch` declares intent for what comes *next*. If you run it after diverging,
the cells that already ran were attached to the previous node. Run it
*before* you start the experiment so the tree reads naturally.

## A complete example

This is fully self-contained — copy it into a notebook cell-by-cell and run it
as-is. It fabricates its own data (no `data.csv` needed), defines a trivial
`run_pipeline`, logs real metrics, and saves a plot per branch (so the
dashboard's **Compare branches** view has something to show), so nothing
external is required.

```python
%load_ext exptrack
%exptrack session start "threshold sensitivity"
```

```python
# ── normal cells: make some data instead of reading a file ──
import random
import matplotlib.pyplot as plt
from exptrack.notebook import metric, note   # log into the %load_ext-started run

def make_data(n=500):
    random.seed(0)
    return [random.random() for _ in range(n)]

def run_pipeline(data, threshold):
    kept = [x for x in data if x >= threshold]
    # toy "accuracy": closer to keeping half the points scores higher
    accuracy = 1 - abs(len(kept) / len(data) - 0.5)
    return {"kept": len(kept), "rate": len(kept) / len(data), "accuracy": accuracy}

def plot_kept(data, threshold, path):
    plt.figure()
    plt.hist(data, bins=20)
    plt.axvline(threshold, color="crimson", label=f"threshold={threshold}")
    plt.legend(); plt.title(path)
    plt.savefig(path)        # ← captured onto the active branch node (by reference)
    plt.close()
```

```python
%exptrack checkpoint "after preprocessing clean"
# (snapshots the preprocessing diff)
```

```python
%%setup
# Demoted prep: builds `data`, which every branch below reuses. Recorded on the
# checkpoint's setup store + a muted `setup` event — kept out of the timeline's
# cell lineage so the two branches stay the story. Run it here (on the shared
# checkpoint, before branching) so all branches inherit it.
data = make_data()
data[:3]
```

```python
%exptrack branch "try threshold 0.7"
# ── first branch: the higher threshold ──
threshold = 0.7
results = run_pipeline(data, threshold)
metric("accuracy", results["accuracy"], step=1)
note(f"threshold={threshold} → accuracy={results['accuracy']:.3f}")
plot_kept(data, threshold, "kept_0.7.png")   # distinct filename per branch
results
```

```python
%%scratch
# typo fix that has nothing to do with the experiment
print(len(data))   # this cell is never logged
```

```python
%exptrack branch "try threshold 0.5"
# ── second branch: a sibling under the same checkpoint ──
threshold = 0.5
results = run_pipeline(data, threshold)
metric("accuracy", results["accuracy"], step=2)
note(f"threshold={threshold} → accuracy={results['accuracy']:.3f}")
plot_kept(data, threshold, "kept_0.5.png")   # ← distinct filename; reusing
results                                       #   "kept_0.7.png" would overwrite it
```

```python
%exptrack checkpoint "0.5 kept closest to half"
# The active experiment (auto-started by %load_ext exptrack) now holds the
# metrics from both branches — nothing else to start.
```

```python
%exptrack promote "0.5 had the higher accuracy"
# (links the active experiment to this node — adds the → exp <id> badge)
```

```python
%exptrack session end
```

Reading the resulting tree (CLI: `exptrack session show "threshold sensitivity"`):

```
session: threshold sensitivity
started: 2026-05-07 09:12  •  notebook: explore.ipynb

○ session start: threshold sensitivity
●── checkpoint: after preprocessing clean       [09:14]  [diff: +12 −3]
    ├──○── branch: try threshold 0.7            [09:18]   🖼 1
    └──○── branch: try threshold 0.5            [09:24]   🖼 1
           └──●── checkpoint: 0.5 kept closest to half  [09:31]  [diff: +1 −1]  → exp 1a2b3c4d
```

### Comparing plots across branches

The two branches above each called `plot_kept(...)` while they were the active
node, so each figure is attached to its branch **by reference** (no copy) — note
the `🖼 1` on both branch rows in the tree. The one rule: give each branch a
**distinct filename** (`kept_0.7.png` vs. `kept_0.5.png`). Because the capture is
by reference, reusing the same filename would overwrite the earlier branch's plot
on disk and both nodes would point at the same image.

Now open the dashboard → **☰ Sessions** → **⇄ Compare branches**, pick the two
branches, and **Compare** — each column shows the branch's captured result and
its histogram, so "which threshold kept closest to half" is a glance, not a guess.

## CLI

```bash
exptrack sessions                       # list sessions
exptrack session show <id|name>         # ASCII tree (above)
exptrack session nodes <id|name>        # flat node list (for scripting)
exptrack session note <node_id> "..."   # annotate after the fact
exptrack session rename-node <n> "..."  # rename a node's label
exptrack session rm <id|name>           # delete session (hard); linked exps preserved

# Per-node trash (soft delete) and recovery
exptrack session rm-node <node_id>      # → Trash (cascades to descendants)
exptrack session trash <id|name>        # list this session's trashed nodes
exptrack session restore-node <node_id> # bring a trashed subtree back
exptrack session purge-node <node_id>   # delete a trashed node FOR GOOD (no undo)
exptrack session empty-trash <id|name>  # delete ALL trashed nodes FOR GOOD (no undo)
```

In the dashboard, every session card in the `☰ Sessions` tab has a `×`
button in its header that deletes the whole session (with a confirmation
prompt).

### Where deleted things go

- **Deleting a whole session** (`session rm`, or the `×` on a session card)
  is a **hard delete** — gone immediately, no trash.
- **Deleting a node/branch** (`rm-node`, or the hover-`×` on a tree node) is a
  **soft delete** → the per-session **Trash**. Restore it, or `purge-node` /
  `empty-trash` to remove it permanently. `purge`/`empty-trash` refuse
  anything not already trashed, so true removal is always a deliberate
  two-step. Either way, linked experiments are preserved.
- **Attached plot files** follow the same two-step. Soft delete leaves them on
  disk (so Restore brings the node back intact); **permanent** removal
  (`purge-node` / `empty-trash`) moves the node's by-reference plot files to
  your **OS Trash** (recoverable — never `rm -rf`) and tells you how many were
  moved. Whole-session `rm` leaves plot files untouched, the same way it keeps
  linked experiments.

Session ids accept prefix matches (e.g. `1a2b`); names accept exact match.

## Dashboard

Click `☰ Sessions` in the header. The left pane lists sessions; clicking one
renders the tree as a vertical, indented node graph:

- **Filled circles** = checkpoints
- **Open circles** = branches
- **Dashed/dimmed** = abandoned branches
- **`→ exp <id>` badge** = a promoted experiment (click to jump to it)

Click a node to inspect its label, time, cell source, **latest result**,
diff, and note. Notes are editable inline.

**Comparing branches.** Click `⇄ Compare branches` in the session header,
then click the checkpoints/branches you want to line up — each shows a blue
accent bar as you pick it. Hit **Compare N** to render them as side-by-side
columns, each with its cell count, `+N −M` diff summary, promoted-experiment
link, and captured **Result**. This is the fast way to answer "which of these
threshold tries actually won". Toggle the button off (or **Clear**) to return
to normal single-node inspection.

**Managing trash.** The `🗑 Trash (N)` button expands the per-session trash
panel: each trashed node has **Restore** and **Delete forever**, plus an
**Empty trash (N)** button to purge the lot. Permanent deletes ask for
confirmation and cannot be undone.

## What gets attached to each node

A node stores four things you can use to see what was tried on that path:

- **`cell_source`** — every non-`%%scratch`, non-`%%setup`, non-`%%pin`,
  non-`%exptrack`
  cell that runs **while this node is the active node** is appended live to
  its `cell_source`. The dashboard splits them back out and shows each as
  its own block; the count appears as a "N cells" badge on the node row.
  Re-running the same cell back-to-back doesn't double-record.

  Practically: cells run *after* `%exptrack branch "X"` show up under branch
  X immediately; cells run *after* `%exptrack checkpoint "Y"` show up under
  Y. You don't have to make a follow-up node for them to materialize.
- **`cell_outputs`** — the **result** each of those cells produced. Both
  `print(...)` output *and* the trailing-expression value are captured,
  mirroring what you saw in the notebook (prints first, then the returned
  value) — so a cell ending in a bare expression (`results`, `df.describe()`,
  `{"acc": 0.81}`) and a cell that just `print()`s its metrics are both
  recorded, kept aligned one-output-per-cell. This is what lets you fire off a
  branch and *see what it produced* without promoting it to a full
  experiment first. The dashboard shows it three ways: a one-line `⤷ result`
  preview right on the tree node, a **Latest result** block in the node
  detail, and an `Out` panel under each cell. Re-running the last cell
  refreshes its captured output instead of duplicating the cell.

  Output is capped at 4000 chars per cell so a chatty training loop can't
  bloat the database; past that the blob ends in `… (output truncated)`. For
  a full, permanent record of a cell's stdout, use `%%pin` to freeze it as an
  artifact.
- **`git_diff`** — `git diff` between the previous checkpoint's commit and the
  current one. Falls back to `git diff HEAD` (working-tree changes) when the
  notebook isn't being committed between checkpoints. Useful when the work
  spans `.py` files outside the notebook.
- **plots** — any figure you `plt.savefig(...)` while the node is active is
  recorded **by reference** (the path, not a copy). The dashboard shows the
  plots as thumbnails in the node detail (**Plots (N)**), side-by-side in the
  branch **Compare** view, and as a `🖼 N` count on the tree node — so you can
  run `threshold = 0.7` / `threshold = 0.5` branches that each save a
  train/test curve and eyeball them next to each other.

  Caveat: because plots are tracked *by reference*, saving every branch to the
  **same filename** (`roc.png`) overwrites the earlier branch's plot on disk —
  give each branch a distinct filename (`roc_0.7.png`, `roc_0.5.png`) if you
  want to compare them later. A plot that's since been moved or overwritten
  shows a "⚠ image missing on disk" placeholder.
- **setup cells** — `%%setup` prep is recorded on a *separate*, byte-budgeted
  store (`setup_source` / `setup_outputs`) so a big prep block can't evict real
  recorded cells. It shows dimmed under a collapsed **Setup / prep** section in
  the node detail plus a `🛠 N` count on the node, and travels with a
  branch→checkpoint promote — but it never enters cell lineage, variable
  tracking, or git diffs. Use it for prep you reference later (a `df`, a
  transform) that isn't the experiment itself.
- **`note`** — annotation you (or `%exptrack promote`) added.

`%%scratch` cells and the `%exptrack ...` magics themselves are intentionally
*not* recorded into `cell_source` — they'd just be noise. `%%setup` cells go to
the demoted setup store above, not `cell_source`.

If you want fine-grained per-cell capture (variable diffs, fingerprints,
artifacts) for a path that turned promising, that's what regular
`%load_ext exptrack` tracking on the active `Experiment` is for. Use
`%exptrack promote` to link the experiment to the session node.

## Idempotent re-runs

Re-running a cell that contains `%exptrack checkpoint "X"` or
`%exptrack branch "Y"` is safe — it reuses the existing node with that
label instead of creating a duplicate. Cells run after the re-run continue
to append to the same node, so you can iterate on a branch without
fragmenting the tree.

If a branch was previously closed by `%exptrack session end` (and flipped
to *abandoned*), re-declaring it with the same label revives it back to a
live branch. The cells you accumulated before the end are preserved.

### Same label, *different* code — the auto-suffix guard

Re-runs are detected by code, not just by label. If you reuse a branch label
under the same checkpoint but the first cell you run is **different** from
what that branch already holds (the classic "copy a branch cell, tweak the
threshold, forget to rename" slip), exptrack assumes it's a new idea rather
than a re-run: it forks a fresh node labelled `try 0.7 (2)`, records your new
cells there, and prints a notice:

```
[exptrack] branch 'try 0.7' already had different code under this checkpoint —
recording under 'try 0.7 (2)' (331d157a) instead. Rename it in the dashboard
(double-click the node label) if you like.
```

So the two explorations stay distinct instead of silently merging. Rename the
fork to something meaningful via the dashboard (double-click the node label),
`exptrack session rename-node <id> "label"`, or just leave the `(2)` suffix.
A genuine Run-All — where you replay the *same* first cell — still merges into
the original node as before.

## Pinning results — `%%pin "label"`

When "pinning" means *"freeze this cell's output as a result I want to come
back to"*, use the `%%pin` cell magic:

```python
%%pin "before/after preprocessing"
df.describe()
```

What happens:

1. The cell body runs. Stdout and the trailing expression's `repr()` are
   captured (and still echoed back to you so the cell behaves normally).
2. A markdown file `pin_<timestamp>_<label>.md` is written into the active
   experiment's output directory and registered as an artifact. It contains
   the cell source, the captured stdout, and the result repr — so it shows
   up in the experiment's Artifacts tab and in exports.
3. If a session is active, the current node's `note` gets a
   `pinned: <label> → <filename>` line so the tree shows it too.

`%%pin` requires an active `Experiment` (i.e. you've loaded `%load_ext
exptrack`). It does **not** require a session — you can pin in any tracked
notebook.

For matplotlib figures, the existing `plt.savefig()` patch already attaches
saved figures to the active experiment as artifacts, so combine that with
`%%pin` if you want both the code and a saved plot.

### Pinning whole experiments

If you want to mark an *experiment* (e.g. one you `%exptrack promote`d) as
canonical so it sorts to the top of the table, use the existing experiment
pin (the yellow star on the experiments table). Session Trees deliberately
don't add a separate concept here — promoted experiments inherit the same
pin behavior.

## Running a notebook without exptrack (portability)

The session magics (`%%scratch`, `%%setup`, `%%pin`, `%exptrack`) only exist
after `%load_ext exptrack` registers them. On a machine where exptrack **isn't
installed**, IPython treats them as unknown magics and raises a `UsageError` —
and for a *cell* magic that means the **whole cell body is skipped**, so prep
silently doesn't run. Three ways to keep a notebook portable:

**1. The guard cell (recommended).** Run `exptrack notebook-guard` and paste its
output at the very top of your notebook:

```bash
exptrack notebook-guard
```

```python
# ── exptrack guard ──────────────────────────────────────────────────────────
try:
    get_ipython().run_line_magic("load_ext", "exptrack")
except Exception:
    _ip = get_ipython()
    def _exptrack_passthrough(line, cell):
        _ip.run_cell(cell)            # run the body, ignore the magic label
    def _exptrack_noop(line):
        pass
    for _name in ("scratch", "setup", "pin"):
        _ip.register_magic_function(
            _exptrack_passthrough, magic_kind="cell", magic_name=_name)
    _ip.register_magic_function(
        _exptrack_noop, magic_kind="line", magic_name="exptrack")
    print("[exptrack-guard] exptrack not loaded — session magics are no-ops, "
          "cells still run.")
```

When exptrack is installed it loads normally (full tracking). When it isn't, the
four magics degrade to no-ops that **still run the cell body**, so the notebook
runs end-to-end for a collaborator who doesn't have exptrack. You never have to
strip the magics again.

**2. Keep exptrack loaded, but turn auto-tracking off.** If exptrack *is*
installed but you don't want it creating runs, set in `.exptrack/config.json`:

```json
"auto_capture": { "notebook": false }
```

The magics stay registered and valid (so nothing breaks), but no experiment is
auto-created — `%%scratch`/`%%setup` just execute the cell body and the session
magics are no-ops unless you explicitly `%exptrack session start`.

**3. Strip them.** Every magic lives on its own isolated line — `%%scratch` /
`%%setup` / `%%pin` are always *line 1 of a cell* and `%exptrack ...` is always a
whole line — so a one-pass find/replace (`^%%(scratch|setup|pin).*\n` and
`^%exptrack .*\n`) removes them with zero effect on your actual code. The cell
bodies run identically as plain cells; you only lose the tier labels.

## Storage cost

Session Trees are cheap. Per session, you spend roughly:

| Thing | Typical size |
|---|---|
| `sessions` row (metadata) | ~120 bytes |
| `session_nodes` row (no cells, no diff) | ~150 bytes |
| `cell_source` per node | sum of cell source bytes between nodes (a few KB for typical exploration) |
| `cell_outputs` per node | sum of each cell's result `repr` (usually small — a dict or number; large frames/arrays repr-truncate) |
| `git_diff` per checkpoint | size of `git diff` output (zero if nothing's committed/changed) |

A whole afternoon of exploration with ~10 checkpoints typically sits well
under 100 KB. Run `exptrack storage` to see the breakdown — there's a
**Sessions** row in the database breakdown plus per-column sizes
(`session_nodes.cell_source`, `session_nodes.git_diff`) under storage
hotspots.

To reclaim: `exptrack session rm <id>` deletes a whole session (linked
experiments are preserved with their `session_node_id` cleared), or
`exptrack session empty-trash <id>` clears just the trashed nodes. There's no
need for `compact` here — even an active project's session data is tiny next
to artifacts and notebook snapshots.

## What Session Trees do **not** do

- They don't serialize or restore kernel state. Retracing a path means re-running
  the cells you want; the tree is the map, not a time machine.
- They don't change anything about regular `%load_ext exptrack` capture.
- They don't add dependencies — stdlib only, like the rest of exptrack.
- They don't auto-create sessions. Always explicit.

## Schema (for the curious)

Two new tables, one new nullable column on `experiments`:

- `sessions(id, name, notebook, status, git_branch, git_commit, created_at, ended_at)`
- `session_nodes(id, session_id, parent_id, node_type, label, note, cell_source,
   cell_outputs, setup_source, setup_outputs, images, git_diff, git_commit, seq,
   created_at, deleted_at)` —
   `node_type` is `'root'`, `'checkpoint'`, `'branch'`, or `'abandoned'`;
   `cell_outputs` mirrors `cell_source` (one result per cell); `setup_source` /
   `setup_outputs` (nullable) hold the demoted `%%setup` prep cells on their own
   byte budget; `images`
   (nullable JSON) lists plots saved by reference while the node was active;
   `deleted_at` (nullable) marks a node as soft-deleted (Trash)
- `experiments.session_node_id` — nullable FK; only set by `%exptrack promote`

`exptrack upgrade` is idempotent — running it on an existing project just adds
the new schema, no data is touched.
