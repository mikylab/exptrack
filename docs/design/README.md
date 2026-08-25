# Design notes

**Audience: people changing exptrack's code** (human or agent). These are not
user documentation — for that, start at [`../../README.md`](../../README.md) and
the guides in [`../`](../) (`cli-reference.md`, `python-api.md`,
`session-trees.md`, `configuration.md`, `troubleshooting.md`, `faq.md`).

## What these are

Each entry states a rule and then the failure it prevents — usually a bug that
actually shipped. That history is the point. "The baseline excludes `running`
runs" is a rule you might reasonably undo; "the baseline excludes `running` runs
because their metrics are still moving, so a delta against one doesn't reproduce
a minute later and a parallel sweep compared every run against a half-finished
sibling" is one you won't.

So these files are deliberately long-form and deliberately *not* summarized.
They are also deliberately not loaded by default: [`../../CLAUDE.md`](../../CLAUDE.md)
carries a one-line index of every rule here, and this is what it points at.

**Read the relevant file before changing a subsystem.** `CLAUDE.md` has a table
mapping code paths to the file covering them.

## Layout

| File | Covers |
|---|---|
| `architecture.md` | Module-by-module map with the reasoning for each boundary |
| `schema.md` | Every table and column, and why the nullable ones are nullable |
| `config.md` | Every `.exptrack/config.json` key, its default and its failure mode |
| `usage.md` | Full command + notebook-magic reference |
| `patterns/run-loop.md` | Baselines, code-change capture, run adoption, per-run deltas |
| `patterns/analysis.md` | Parameter matrix, rankings, effects, duplicates, primary metric, reference run |
| `patterns/capture.md` | argparse/savefig/TensorBoard/notebook capture |
| `patterns/metrics.md` | Thinning, commit batching, chart rendering |
| `patterns/storage.md` | Byte accounting, refcounted blobs, prune, Trash, delete |
| `patterns/sessions.md` | Session Trees |
| `patterns/dashboard-views.md` | Canvas ownership and selection ownership |
| `patterns/dashboard-ui.md` | Experiment list, detail view, inline editing |
| `patterns/dashboard-render.md` | Design tokens, Timeline taxonomy, code rendering |
| `patterns/server.md` | Concurrency, routing, request/response handling, file serving |

## Adding to these

Write the **rule first**, then the failure it prevents. Don't compress the
history away — it is why these files exist, and why they are cheap to keep
(nothing reads them until it needs them).

If a change makes an index one-liner in `CLAUDE.md` inaccurate, fix it there
too. The index must never state a rule these files contradict; that is the only
hard constraint between them.
