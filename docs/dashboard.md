# The dashboard

```bash
exptrack ui                  # http://127.0.0.1:7331
exptrack ui --port 8080      # somewhere else
exptrack ui --no-auth        # skip the token (local only)
exptrack ui --no-browser     # don't open a browser tab (ui start takes it too)
exptrack ui-stop             # kill whatever is holding the port
```

Local-first and dependency-free: a stdlib HTTP server, a vendored Chart.js, no
CDN and no webfont. Nothing leaves your machine.

The pages below are the ones people ask about. Everything here reads the same
`.exptrack/experiments.db` the CLI does, so the two can never disagree.

---

## Several projects, one dashboard

One dashboard serves every project it knows about, so three checkouts do not
mean three servers on three ports with three tokens. Run `exptrack ui start`
in the second one and it starts nothing: it registers that project, tells you
which checkout the running dashboard came from, and prints a URL that opens
*this* project.

The project rides in the page URL (`/?project=<id>`), which makes it a
property of the **tab**, not of the browser. Two worktrees can sit in two
windows and neither moves the other. The picker beside the page title
switches this tab; the sibling links under the sidebar's picker are ordinary
links, so ctrl/cmd-click opens a worktree in a new tab — that is how you get
two projects side by side.

Worktrees of one repository are grouped under one heading and labelled by
branch, because three checkouts of one repo usually share a directory name.
The grouping is presentation only: each project keeps its own database and
nothing is merged. Compare is the one view that can hold runs from two
projects at once.

The switcher lists what discovery can see — the projects you have run
`exptrack init` or `exptrack ui start` in (remembered in
`~/.exptrack/projects.json`) plus other worktrees of this repository that
already have an `.exptrack/`. A project whose database cannot be read stays on
the list with the reason and is not selectable; one whose directory is gone is
dropped and forgotten, because it cannot come back on its own. The gear beside
the picker forgets a project by hand — registry only, nothing on disk.

### More than one dashboard

Usually you want one: the shared dashboard above already reaches every project,
and a second server buys you a second port and a second token for nothing. When
you do want a separate one, the rules are:

| You want | Run | What you get |
|---|---|---|
| Every checkout on one server (default) | `exptrack ui start` in each checkout | One background server; each checkout gets a `?project=` URL for it |
| Two projects side by side | Open both `?project=` URLs in two tabs or windows | One server; each tab keeps its own project |
| A throwaway second server | `exptrack ui --port 8080` (foreground) | An independent server with *that* checkout's token; Ctrl+C stops it |
| A dashboard on another machine | `exptrack tunnel add gpu --host you@gpu-box --dir ~/proj --local-port 7332`, then `exptrack tunnel gpu` | The remote's dashboard at `http://127.0.0.1:7332`, token included |

- **Only one *background* dashboard is tracked.** `exptrack ui start --port 8000`
  while one is running on 7331 is refused, naming the running one — the record
  in `~/.exptrack/dashboard.json` holds one slot, and a second detached server
  would become untracked (unreachable through `ui status` / `ui stop`, and on
  Windows unreachable from the CLI at all). Stop the first
  (`exptrack ui stop`) or use the foreground form.
- **A foreground dashboard is yours to stop.** `exptrack ui --port 8080` is not
  recorded, so `ui status` and `ui stop` do not see it; stop it with Ctrl+C in
  its terminal. It still shows the full project switcher.
- **Give each tunnel its own local port.** Two remotes both default to local
  port 7331 — which is also where your local dashboard lives. Set
  `--local-port` per remote so a local dashboard and several remote ones can
  be open at once.
- **Tokens follow the server, not the project.** A shared dashboard uses the
  token of the checkout that started it; `exptrack ui status` from any
  checkout prints the URL with the right one.

---

## Saved commands and templates (`>_ Cmds`)

The panel behind the **`>_ Cmds`** button in the header holds the commands you
re-run — and any `{{variable}}` in one becomes an editable field, so you change
the value instead of retyping the line.

Save a command containing placeholders:

```
exptrack run train.py --lr {{lr}} --dropout {{dropout}} --epochs {{epochs}}
```

The panel renders one input per unique `{{name}}`. Typing in it substitutes
live into the displayed command, and **Copy** copies the *filled* version. The
template itself is never rewritten, so the placeholders survive every edit.

- **Values persist** per command, so the panel reopens with what you last used.
- **Date-like variables** (`date`, `today`, anything ending `_date`) default to
  today and are deliberately *not* persisted — they re-default on every reload
  rather than going stale.
- **An unfilled variable stays visible** as `{{name}}` in the command, so you
  can't copy a half-built line without noticing.
- Commands carry tags and studies, and the panel filters on both.

Saved commands live in `.exptrack/config.json` under `commands`, so they are
committable and shared with whoever clones the project.

## The experiment list

- **`param:<key>` columns** — add any captured parameter as a sortable column.
- **Selection bar** — appears when you tick runs. Compare, Hide, Add to Study,
  Export/Copy in five formats, Compact, Delete, and **Finish**.
- **Finish (n)** marks the *running* runs in your selection as done. It counts
  only the runs it can act on, so a selection of 20 runs with 3 running reads
  `Finish (3)`, and the button is absent when nothing selected is running. Use
  it when a launcher died and left a batch stuck `running` — a SLURM array, a
  killed sweep. The CLI equivalents are `exptrack finish <id>` for one run and
  `exptrack stale --hours N` for an age rule.
- **Metric deltas are coloured by whether they are better, not bigger** — a
  falling loss is green.

## Compare

One view, any number of runs. **Choose runs…** opens the searchable picker;
the runs you stage appear as chips you can remove individually, and **Clear**
drops the staged set together with the comparison it produced. For any set:

- a **Configuration** table — the script each run used plus only the parameters
  that *differ*, so you can see what produced the numbers;
- a **comparison table** with the best and worst value tinted per metric row.
  Click a metric's name to flip which direction counts as better (stored per
  browser — it is a reading preference, not a property of the project);
- **training curves** overlaid across every run;
- **Rank by** *final value* or *best value* — a run that overfits late scores
  very differently under each;
- **Export CSV** and **Copy link**. The link is a `#compare=` fragment, so it
  never reaches the server and can be pasted to anyone with the same project.

- a **colour key** above the charts: swatch, run name, id and the settings that
  distinguish it, each row a link to the run. Chart.js builds its legend from
  the series label, and a label can be ambiguous (two runs sharing `lr=0.0001`
  get one entry each, identical); the key never is.

Pick **exactly two** runs and it adds the panels that only mean something for a
pair — these used to be a separate *Pair Compare* tab, which meant a three-run
comparison could not reach them at all:

- **All parameters**, both runs, differences marked, with *Show only differences*;
- a **Delta** column on the metric table (a delta between three runs is "against
  which?", so the column exists only for a pair);
- **Code changes** between the two attempts — the run/run/compare loop's payoff,
  including the case where the runs' own source is identical but a file they
  import changed;
- **Variables**, the final variable state from each notebook run's timeline;
- **Overlay two images** — pick one image from each run and swipe or superimpose.

If some selected runs could not be loaded, the view says so rather than
rendering a smaller comparison silently.

## Parameter matrix

Select runs and open the matrix for one row per run, one column per varying
parameter, the primary metric pinned and the best row marked. Beneath it:

- **Top runs**, **Progress over the search**, **Trade-off between two metrics**
  (a Pareto front), and **What each value was worth**.
- **Colour by → script (model)** groups the effect scatter by model, which is
  what a mixed-script set usually wants: a shared `lr` column across two models
  mixes semantically different knobs.
- Effect summaries are **descriptive only** and say so — the runs were not
  randomized, so this is not a measure of importance. Confounded parameters are
  not charted at all, and unscored runs are counted separately rather than
  quietly dropped.

## Comparing different models

Two models rarely agree on what to call a number. If one logs `accuracy` and
another `val_acc`, tell the project they are the same measurement:

```json
{ "metric_aliases": { "val_acc": ["accuracy", "val/acc"] } }
```

Every surface — the table, Compare, the curves, the matrix, ranking — then
treats them as one metric, and says which spellings it merged. Nothing is
rewritten in storage: each run keeps the key it logged, and removing the alias
gives the original names back.

## Sessions

The **Sessions** tab renders Session Trees: checkpoints, branches, the git-graph
rail, per-branch metrics, and promote/materialize into standalone experiments.
See [Session Trees](session-trees.md).

## Trash

Settings → Database → **Open Trash**. Deleting from the dashboard defaults to
*Move to Trash*; permanent deletion is a separate tab, and removing files is an
opt-in checkbox that sends them to the OS Trash — never `rm -rf`. From the
terminal: `exptrack rm <id> --trash`, `exptrack trash`, `exptrack restore-run`.

## Access and security

A token is generated on first launch and stored in `.exptrack/dashboard_token`
(mode 600, gitignored) — deliberately *not* in `config.json`, which is
documented as safe to commit. `--no-auth` disables it for local use.

The server binds `127.0.0.1` by default. To reach it from another machine,
prefer an SSH tunnel over binding a public interface:

```bash
ssh -N -L 7331:127.0.0.1:7331 you@gpu-box
```
