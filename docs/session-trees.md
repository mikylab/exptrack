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
%%pin "label"                            # cell magic — runs, snapshots cell + output as artifact
%exptrack promote    "label"             # link active experiment to current node
%exptrack session end                    # close — open branches → abandoned
```

## Timing — before or after a change?

This is the most important part to get right.

| Magic | Run it… | Mental model |
|---|---|---|
| `session start` | **once, at the top of your exploration** | "I'm about to poke around — record the shape of it" |
| `checkpoint` | **after** a change that worked, that you might want to return to | "Save point. If the next thing breaks, I can come back here." Snapshots a per-checkpoint git diff (vs. the previous checkpoint commit, falling back to `git diff HEAD`). |
| `branch` | **before** you start diverging | "I'm about to try X instead of Y. Here's why." Attaches under the most recent checkpoint. |
| `%%scratch` | **on the first line** of a throwaway cell | "This is a typo fix / sanity check / quick print — don't pollute the timeline." |
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

```python
%load_ext exptrack
%exptrack session start "threshold sensitivity"

# ── normal cells ──
import pandas as pd
df = pd.read_csv("data.csv")
df = df.dropna()

%exptrack checkpoint "after preprocessing clean"
# (snapshots the preprocessing diff)

%exptrack branch "try threshold 0.7"
# ── try the higher threshold ──
threshold = 0.7
results = run_pipeline(df, threshold=threshold)

%%scratch
# typo fix that has nothing to do with the experiment
print(len(df))   # this cell is never logged

%exptrack checkpoint "threshold 0.7 works"
# Now run the actual experiment...
# (start a regular Experiment via your usual exptrack flow)

%exptrack promote "0.7 outperformed baseline"
# (links that Experiment to this node)

%exptrack session end
```

Reading the resulting tree (CLI: `exptrack session show "threshold sensitivity"`):

```
session: threshold sensitivity
started: 2026-05-07 09:12  •  notebook: explore.ipynb

○ session start: threshold sensitivity
●── checkpoint: after preprocessing clean       [09:14]  [diff: +12 −3]
    └──○── branch: try threshold 0.7            [09:18]
           └──●── checkpoint: threshold 0.7 works  [09:31]  [diff: +1 −1]  → exp 1a2b3c4d
```

## CLI

```bash
exptrack sessions                       # list sessions
exptrack session show <id|name>         # ASCII tree (above)
exptrack session nodes <id|name>        # flat node list (for scripting)
exptrack session note <node_id> "..."   # annotate after the fact
exptrack session rm <id|name>           # delete session; linked exps preserved
```

In the dashboard, every session card in the `☰ Sessions` tab has a `×`
button in its header that does the same thing (with a confirmation prompt).

Session ids accept prefix matches (e.g. `1a2b`); names accept exact match.

## Dashboard

Click `☰ Sessions` in the header. The left pane lists sessions; clicking one
renders the tree as a vertical, indented node graph:

- **Filled circles** = checkpoints
- **Open circles** = branches
- **Dashed/dimmed** = abandoned branches
- **`→ exp <id>` badge** = a promoted experiment (click to jump to it)

Click a node to inspect its label, time, cell source, diff, and note. Notes are
editable inline.

## What gets attached to each node

A node stores three things you can use to see what was tried on that path:

- **`cell_source`** — every non-`%%scratch`, non-`%%pin`, non-`%exptrack`
  cell that runs **while this node is the active node** is appended live to
  its `cell_source`. The dashboard splits them back out and shows each as
  its own block; the count appears as a "N cells" badge on the node row.
  Re-running the same cell back-to-back doesn't double-record.

  Practically: cells run *after* `%exptrack branch "X"` show up under branch
  X immediately; cells run *after* `%exptrack checkpoint "Y"` show up under
  Y. You don't have to make a follow-up node for them to materialize.
- **`git_diff`** — `git diff` between the previous checkpoint's commit and the
  current one. Falls back to `git diff HEAD` (working-tree changes) when the
  notebook isn't being committed between checkpoints. Useful when the work
  spans `.py` files outside the notebook.
- **`note`** — annotation you (or `%exptrack promote`) added.

`%%scratch` cells and the `%exptrack ...` magics themselves are intentionally
*not* recorded into `cell_source` — they'd just be noise.

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

## Storage cost

Session Trees are cheap. Per session, you spend roughly:

| Thing | Typical size |
|---|---|
| `sessions` row (metadata) | ~120 bytes |
| `session_nodes` row (no cells, no diff) | ~150 bytes |
| `cell_source` per node | sum of cell source bytes between nodes (a few KB for typical exploration) |
| `git_diff` per checkpoint | size of `git diff` output (zero if nothing's committed/changed) |

A whole afternoon of exploration with ~10 checkpoints typically sits well
under 100 KB. Run `exptrack storage` to see the breakdown — there's a
**Sessions** row in the database breakdown plus per-column sizes
(`session_nodes.cell_source`, `session_nodes.git_diff`) under storage
hotspots.

To reclaim: `exptrack session rm <id>` deletes a whole session (linked
experiments are preserved with their `session_node_id` cleared). There's no
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
   git_diff, git_commit, seq, created_at)` — `node_type` is `'root'`,
   `'checkpoint'`, `'branch'`, or `'abandoned'`
- `experiments.session_node_id` — nullable FK; only set by `%exptrack promote`

`exptrack upgrade` is idempotent — running it on an existing project just adds
the new schema, no data is touched.
