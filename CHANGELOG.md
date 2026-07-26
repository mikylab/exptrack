# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.52.1] - 2026-07-26

### Fixed
- **The typed-body fix now covers every endpoint** — the 1.52.0 sweep replaced `body.get("k", "").strip()` but missed nine sites spelled `(body.get("k") or "").strip()`, which fails identically on a JSON number (`5 or ""` is `5`). Param add/edit/rename, the todo and command endpoints, and export filenames were still affected. A test now scans the route sources so the rule is checked rather than remembered.
- **`exptrack storage` reads each large table once again** — the 1.52.0 split turned single multi-aggregate queries into one query per statistic, which meant four full scans of `session_nodes` where there had been one, three of `cell_lineage` where there had been two, and two of `git_diffs` where there had been one. Those are exactly the tables holding the big TEXT blobs the report exists to measure, and `SUM(LENGTH(col))` cannot use an index, so each extra query was a full re-read.
- **One byte formatter, for real this time** — 1.52.0 claimed to have deduplicated it but left a fourth MB-capped copy inside the compaction routes, so compaction output still reported a 3 GB total as "3072.0 MB". `fmt_bytes` now lives in `core/utils.py` (layer-neutral, since both the CLI and the dashboard need it) and the test asserts no module defines its own, rather than asserting a particular alias exists.

### Changed
- **Dashboard route order is no longer load-bearing** — the prefixed route table is matched in two passes, specific routes before generic ones, so a new sub-action can be added anywhere in the table instead of having to sit above the generic route sharing its prefix. The guard test now reverses the table and asserts dispatch is unchanged.
- **The 500 boundary covers every HTTP verb** — it moved from per-verb wrappers on `do_GET`/`do_POST` to `handle_one_request`, the single point every request passes through, so a verb added later cannot silently revert to dropping the connection.

## [1.52.0] - 2026-07-26

### Fixed
- **A JSON number in a request body no longer kills the connection** — every mutation endpoint read body fields with `body.get("value", "").strip()`, which assumes a string because the dashboard's own JS only ever sends strings. Any other client sending correct JSON types (`{"value": 0.8}` instead of `{"value": "0.8"}`) hit `.strip()` on a float and raised. All 46 such reads now go through a shared `body_str()` that behaves identically for strings and coerces anything else.
- **A route bug is now a 500 you can read** — an unhandled exception in any endpoint escaped `do_GET`/`do_POST`, and the server closed the connection without writing a response at all. The caller saw a dropped socket, which neither the dashboard's error bar nor `curl` can report usefully. Exceptions are now caught, logged to the console you started `exptrack ui` from, and returned as a 500.

### Changed
- **`exptrack storage` is testable** — the command was one 212-line function with 48 branches and no test coverage, because none of the numbers it computed were reachable without capturing stdout. It is now `collect_storage_stats()` (a plain dict, one helper per area) plus four render functions; largest remaining function is 8 branches. Output is byte-identical. Along the way `_fmt_bytes` existed in three copies that had already diverged — only one handled GB, so a 3 GB outputs directory reported as "3072.0 MB" from one call site and "3.00 GB" from another. There is now one implementation.
- **`write_routes.py` is a package** — 1940 lines and 79 public functions split into 10 submodules grouped the way the request dispatcher already groups them (experiments, params, metrics, studies, settings, compact, bulk, admin, toolbox, sessions). Purely structural: every function body is unchanged, the full surface is re-exported, and no import anywhere else needed to change. New tests fail if the dispatcher references an endpoint the package doesn't export.

## [1.51.0] - 2026-07-26

### Fixed
- **A hostile SVG artifact can no longer steal your dashboard token** — `.svg` counts as an image, so SVG artifacts appear in the Images tab with their thumbnails linking to the full file, and that link carries the auth token in the query string (`?token=…`). An SVG is a live document, not a picture: opening one served as `image/svg+xml` from the dashboard's own origin ran any script it contained, with the token sitting in `location.search`. Since artifacts are user-supplied files a project can pick up from a cloned repo or a shared dataset, that was a real path to token disclosure. Files served from `/api/file/` are now sandboxed (`Content-Security-Policy: … sandbox`), which disables scripting and puts the response in an opaque origin. Ordinary images, plot SVGs with inline `<style>`, and log/CSV viewing are unaffected.

### Added
- **Security headers on every dashboard response** — `X-Content-Type-Options: nosniff` (so a served `.log` or `.txt` can't be re-typed as HTML), `Referrer-Policy: no-referrer` (the token is in the URL, so without this every outbound link leaked it in the `Referer` header), and a Content-Security-Policy. The page policy blocks all external origins, framing, and `<base>`/`<object>`/`<form>` hijacking; it deliberately still allows inline scripts, since the UI is built on inline `on*` handlers, so it is a containment layer rather than an XSS backstop. Headers are attached in `end_headers`, so error responses carry them too.
- **CI runs the tests that cover the monkey-patching** — the capture tests for matplotlib, TensorBoard histograms, and pandas/ndarray fingerprinting skip when those libraries are absent, which is exactly how CI ran them, leaving exptrack's headline feature unverified on every commit. A new `integrations` extra (`pip install exptrack[integrations]`) and a matching CI job install them, and the job fails if those tests skip rather than passing green with the coverage silently gone.
- **CI enforces lint** — `ruff` and `eslint` now run as a CI job. Both are clean.

### Changed
- **Python 3.8 is no longer claimed as supported** — the package advertised `>=3.8` and a 3.8 classifier while CI only ever tested 3.9+. 3.8 is end-of-life; `requires-python` is now `>=3.9`. Python 3.14 was already in the classifiers and is now actually tested.
- **Dashboard GET routing is a table instead of a 47-branch if/elif chain** — routes with a fully known path live in a dict, where nothing can shadow anything; only genuinely prefix-matched routes stay in an ordered list. Previously a route like `/api/experiment/<id>/delete-preview` was reachable only because it happened to be written above the generic `/api/experiment/<id>` entry, and getting that order wrong fails silently — the specific route becomes dead code and the request resolves to the generic handler with the action name as the experiment id. Two tests now pin the invariant, including one that fails if a new suffixed route is appended below its bare-prefix sibling.

## [1.50.2] - 2026-07-26

### Changed
- **Cleanup is cheaper and its preview now matches what it does** — the reference-counted blob tables (`code_snapshots`, `git_diffs`) are no longer scanned on every `exptrack` command exit: they can only go stale after a delete, which reclaims them inline, so the per-exit sweep was paying two full table scans for a guaranteed-zero result. Bulk deletes reclaim once for the batch instead of once per run (a 200-run delete was 200 full scans), and `exptrack clean --orphans --dry-run` now lists the blobs it would remove — previously they were discovered *after* the dry-run and the confirm, so the preview described a different set than the run performed, and a project whose only orphans were blobs reported "No orphaned data found" and could never reclaim them.
- **A lost diff is reported consistently everywhere** — the sentinel check now also gates the compaction *previews* (dashboard and `--dry-run`), which promised freed bytes the real compaction then skipped, and `exptrack compact --export-dir`, which wrote the literal marker inside a ```` ```diff ```` fence in the exported lab-notebook file. The three markers and their two classifiers (`is_diff_sentinel`, `diff_sentinel_kind`) now live together in `core/db.py` next to the function that produces them, and the dashboard branches on a `sentinel` field from the server instead of hardcoding marker strings in JS.
- **`exptrack ui --token` guarantees the ignore rule it claims** — the token path and writer moved to `config.py` (which owns `.exptrack/` layout and the gitignore list), and writing a token now appends the ignore rules first. A project initialized before the token moved out of `config.json` had no rule for it, so the CLI printed "gitignored" for a file that wasn't. The duplicate "token is in config.json" warning is gone — it's reported once, at startup.

## [1.50.1] - 2026-07-26

### Fixed
- **A lost diff no longer reads as "no changes"** — git diffs are deduplicated into a shared table and referenced by hash, and when that reference dangled (the body having been compacted away or purged) `resolve_git_diff` handed back the raw `[ref:sha256:…]` pointer. Every consumer then rendered that literal string as though it *were* the diff, and the detail header counted it as one line of uncommitted changes. A dangling reference now resolves to `[diff-unavailable]`, which the CLI, the detail view, and the export path each report as unavailable — a distinct fact from a clean tree, a failed capture, or a deliberate compaction. Compacting skips it instead of stamping a `[compacted — 17 B stripped]` marker over a diff that was already gone.
- **A session in the Trash says so instead of looking live** — a soft-deleted session is hidden from the sessions list but still reachable, because an experiment promoted out of it keeps a "From session …" back-link that opens it directly. Nothing marked it as trashed, and the header still offered Finalize and End session on it. The banner and the session header now show an **in Trash** tag, and the header offers **↺ Restore session** in place of the live-only actions.
- **The Trash explains a node whose session is also trashed** — trashed session nodes are grouped by session in the unified Trash, including sessions that are themselves in the Trash (and listed in the section right above). Restoring such a node appeared to do nothing, since its session stays hidden either way. Those groups are now marked with a link to restore the session first.
- **Files sent to the Linux Trash are always restorable** — the XDG trash record was written *after* moving the file, so a failed write left a file in `~/.local/share/Trash/files` with no matching `.trashinfo` — a blob no file manager will restore. The record is now created first, exclusively (which also makes the name reservation atomic against a concurrent trash), and is removed again if the move fails so a record never points at nothing.

## [1.50.0] - 2026-07-26

### Fixed
- **"Clean database" no longer deletes files you chose to keep** — the button removed orphaned *rows* as advertised, but also `rm -rf`'d every directory under `outputs/` that no run claimed, with no confirmation, no preview, and no Trash copy. The worst case was silent: permanently deleting a run leaves "Also move files to system Trash" **unchecked** by default, so the outputs you deliberately kept became unclaimed — and the next Clean click destroyed them. Anything you had put in `outputs/` by hand went the same way. Row cleanup still runs on click; files are now a separate step that lists each path with its file count and size, asks first, and moves them to the OS Trash (recoverable) instead of deleting them. `exptrack clean --orphans` and `--reset` route through the same recoverable path.
- **"Delete all data" now actually deletes all data** — both reset paths (the dashboard's Reset button and `exptrack clean --reset`) carried separate hardcoded table lists that each omitted `code_snapshots`, `sessions`, and `session_nodes`. After a reset that promised "this cannot be undone", every captured script source and every notebook cell body and output was still sitting in the database. Both now share one list, ordered so foreign keys hold.
- **Permanently deleting a run reclaims its stored source and diff** — a run's script snapshot (`code_snapshots`) and working-tree diff body (`git_diffs`) were never freed on delete, and no sweeper knew those tables existed: `exptrack clean --orphans` and the dashboard's Clean button both reported a clean database while the two largest blob tables grew forever. Since a working-tree diff routinely contains an accidentally-staged `.env` or unpublished code, "permanently delete" was leaving readable data behind. Both tables are now reference-counted: blobs survive a soft delete so Restore stays lossless, are kept while any other run still points at them (content-addressed dedup), and are reclaimed when the last referrer goes.
- **The dashboard token is no longer written to a file you're told to commit** — `exptrack ui --token` saved the auth secret into `.exptrack/config.json`, which `exptrack init` describes as safe to commit and deliberately leaves out of `.gitignore`, putting a live token one `git add -A` from being published. It now goes to `.exptrack/dashboard_token` (gitignored, mode 600). An existing config token keeps working and is flagged on startup with the command to move it. `exptrack init` also now gitignores `.exptrack/trash/`, the local fallback holding deleted artifacts and checkpoints.

## [1.49.3] - 2026-07-26

### Fixed
- **A deleted or still-running run is no longer used as a comparison baseline** — "previous run" is now picked by one shared rule wherever it appears (the detail strip, the "What changed" card, and the finish-time summary). Trashed runs are skipped: they're gone from every list, so a delta against one named a baseline you couldn't open or verify, and deleting a run between two attempts silently changed the numbers with no visible cause — the comparison now walks back to the next surviving run, matching what the list shows. Unfinished runs are skipped too, since their metrics are still moving: a delta against one didn't reproduce a minute later, and a parallel sweep compared each run against a half-finished sibling.
- **Comparing against a failed run says so** — a failed run is deliberately *kept* as a baseline, because "it broke, I fixed it, what changed?" is the loop this comparison exists for and skipping the failure would hide the comparison you wanted. But its metrics stop wherever it crashed, so an unqualified `acc 0.41 → 0.87` read as a measured result. The baseline is now marked **failed** on both the "What changed" header and the "vs previous run" chip, with a note that the metric values are the crash point rather than a finished result — parameter and code changes are exact either way. The one-line finish summary names it too: `vs prev (name, failed)`.

## [1.49.2] - 2026-07-26

### Fixed
- **"Previous run" can no longer resolve to a run that started later** — the baseline was picked by `created_at` alone, so two runs launched inside the same clock tick tied on the timestamp and the winner was whatever order SQLite happened to return. That could point "previous" at the run that started *after* the one you were viewing. The comparison now orders on `(created_at, rowid)` — rowid being insertion order, and therefore launch order — so a chain of same-second runs always resolves backwards in time.
- **The baseline says how much earlier it ran** — timestamps in the dashboard resolve to the minute, so two runs launched seconds apart printed the same time and there was no way to tell which direction the comparison ran (the newest-first list puts the older run *below* the current row, which reads as "the next one"). The "vs previous run" chip and the "What changed" header now say `2 days earlier` / `1 min earlier` / `just before`, with the exact timestamp in the tooltip.

## [1.49.1] - 2026-07-26

### Fixed
- **A delta that reads as zero is no longer reported as a change** — `0.9 + 0.03` and `0.85 + 0.04 * 2` are both 0.93 but differ by 1.1e-16, and that float noise surfaced as a metric change rendering `▼ -0.0000 (-0.0%)`: a row that exists only because something supposedly moved, showing a value that reads as nothing. Metric comparisons now ignore differences at float-noise scale, and a change that *is* real but small no longer rounds away — the delta drops to exponential (`+1.0e-7`), percentages under 0.1% say so, and both the previous and current values are shown with enough precision to actually differ instead of printing `0.5000 → 0.5000`.
- **"code changed" means this run's code, not any file in the repo** — the flag compared the whole working-tree diff, so editing an unrelated tracked file stamped a byte-identical rerun with an amber **code changed** chip while the Code-changes panel right below it correctly reported no change. The chip now fires on the run's own script snapshot or notebook cells — the same source the panel diffs — and the wider repository signal gets its own muted **repo changed elsewhere** chip, which says in its tooltip that this run's code is identical. The same distinction appears in the one-line finish summary.

## [1.49.0] - 2026-07-26

### Added
- **"What changed" can show the code, not just the params** — the card at the top of every run's Overview diffed params and metrics against the previous run of the same script, but the most common edit in the tweak-one-line loop is to the code itself, and seeing it meant opening the full Compare view. A **Show code changes** button now expands the actual diff inline — the script's source snapshot, or the notebook cells that differ — using the same word-level renderer as Compare, so a changed threshold or coefficient is spotlighted in place. It loads on click rather than with the page, since a snapshot can be hundreds of KB.

### Fixed
- **Empty columns are named again** — a column with no data in view collapses to a narrow strip to hand its width to Name and Metrics, but at 44px the header label didn't fit and was replaced by a `·`. The result was four unlabelled dots between STATUS and METRICS that read as a broken table, and a narrow strip you could sort by without knowing what you'd just sorted. Collapsed columns now keep their name, dimmed and lowercase, which also marks them as holding nothing.
- **`_code_snapshot` no longer hijacks "What changed"** — the internal-param filter was a list of known keys rather than the `_`-prefix rule exptrack actually writes by, so `_code_snapshot` (a JSON blob naming the snapshot hash and the script's absolute path) slipped through. Any run whose script had been edited showed that blob as the headline row of "What changed", burying the hyperparameter you actually changed. Internal params are now filtered by prefix everywhere — the card, the Overview's Params table, and the Compare pickers' option labels.
- **The "vs previous run" strip says *when* the previous run was** — it named the baseline run but not its date. Since the run list is newest-first, the run being compared against sits *below* the current row, so "previous" read as "the next one" and left you unsure which direction the comparison ran. The chip now carries the baseline's start time, and the label spells out that it's the last run of this script started before the one you're viewing.

## [1.48.0] - 2026-07-24

### Added
- **Searchable Compare pickers** — the Compare dropdowns listed ~100 runs as `id | name | status | date`, truncating the name at 35 characters. With auto-generated names that cut off the *only* distinguishing part, leaving a hundred visually identical lines and no way to search a native `<select>`. A filter box above both Compare tabs now narrows every picker as you type — by name, id prefix, param value (`lr=0.1`), status or date — and the options themselves show the full name plus the run's first few params, so runs are actually distinguishable. A pick that a later filter excludes stays selected instead of silently resetting. The filter is debounced like the main search box, the run list is fetched once per visit rather than on every tab switch, and if some runs went unfetched the Compare view says so with its own **Load all runs** button — a filter box searching a partial set would otherwise show "no match" for a run that exists.
- **"Showing N of M runs" notice** — the experiment list loads a page at a time, but search, filters and *Sort by metric* only ever saw the loaded rows. Past the page size that made "sort by metric" quietly answer "best of the runs I happen to have" while looking exactly like "best run". The page size is now large enough that most projects load whole in one request, and when a project doesn't, a notice above the table says so and offers **Load all runs**.

### Fixed
- **Clicking a row's tags, studies, stage or notes opens the run again** — those cells started an inline editor on a *single* click and cancelled the row's own click, so clicking most of a row's width silently swallowed "open this run" and popped up an editor you never asked for. Editing is now the double-click it was always documented as, and the hover pencil remains a one-click shortcut, so nothing became slower to reach.
- **No webfont request to fonts.googleapis.com** — the dashboard CSS imported IBM Plex Mono from Google's CDN, which stalls the first paint on an offline or air-gapped machine and sent a third-party request on every load. The font stack now prefers a locally installed IBM Plex Mono and falls back to the platform monospace faces; the dashboard makes no external requests at all.
- **"Sort by metric:" stays with its dropdown** — on a narrow window the controls bar wrapped between the label and the `<select>` it names, leaving the label stranded at the end of one line and an unlabelled dropdown at the start of the next. Each label is now glued to its control, so the bar wraps between groups instead.

### Changed
- **Secondary stats are collapsed by default** — eleven stat cards under two section headings pushed the experiment table itself toward the fold. The four run-status cards (Total / Done / Failed / Running) stay visible; the other seven moved behind a **More stats** toggle that remembers your preference, and the cards are a little tighter. The stats block went from ~205px tall to ~100px, so the table starts a full card-row higher up the page.

## [1.47.0] - 2026-07-24

### Added
- **Param columns in the experiment table** — any hyperparameter can now be a real, sortable column. The ⚙ Columns panel gained a **Params** section listing every param captured on the loaded runs, with the ones whose value *varies* across runs listed first and marked with a dot, plus a one-click **"Show the N varying params"** button. Previously the table's column set was a fixed list, so the thing that actually differs between two runs of the same script — `--lr`, `--threshold` — was invisible in the list and you had to open every run to see it. Param columns render right-aligned in tabular figures (so a column of numbers lines up), sort numerically where the values are numeric, and push runs missing the param to the bottom like metric-sort does.
- **Visible error banner when the dashboard can't reach the server** — a failed API request now raises a dismissable banner naming the failing endpoint, with a **Retry** button. Previously a failed fetch rejected with nothing catching it, so the render that depended on it never ran: the table sat empty with no error, no retry, and no explanation while the stats cards above it still confidently reported a run count.

### Fixed
- **One malformed row no longer blanks the whole experiment list** — a bare string or garbage in an experiment's `tags`/`studies` JSON column (from a hand-edited DB, an older writer, or a third-party script) raised out of `list_experiments` and killed the entire request, so the dashboard showed zero runs with no error at all. Those columns are now parsed tolerantly: a bare string is salvaged as a one-element label list, anything unusable degrades to empty with a stderr warning, and the other 139 runs still load. The same guard covers the detail view and the study/tag mutators.
- **`exptrack ui --no-auth` is usable again** — with auth disabled there is no token, but the dashboard skipped straight to the login overlay and asked for one anyway, making the whole page unreachable. It now probes the server first and proceeds when auth is off.
- **Delta arrows no longer call a rising loss an improvement** — metric deltas coloured purely on the sign of the change, so `train/loss` going 0.221 → 0.275 rendered as a **green ▲** — the run got worse and the UI said it got better. Deltas are now polarity-aware: metrics whose name indicates lower-is-better (`loss`, `error`, `mse`, `rmse`, `mae`, `nll`, `perplexity`, `wer`, `latency`, …) colour green only when they *fall*. The arrow still shows the numeric direction, and the tooltip spells out which way is better. Applies everywhere deltas appear — the "What changed" card, Compare's metrics table, the filmstrip badges, and the "vs previous run" chips (which now colour better/worse instead of staying neutral). An unusual metric can be corrected via a `exptrack-metric-polarity` localStorage override.
- **Filmstrip deltas compare against the actual previous run** — each card's delta used the *next card in the list* as its baseline, which is only the older run under the default newest-first sort. With *Sort by metric* on, or any pinned run reordering the list, the badge silently became a comparison against an arbitrary run while still reading as a chronological delta. The baseline is now resolved by timestamp.

### Changed
- **Table grouping defaults to Script, and is remembered** — the default was *Git Commit*, which is the worst possible grouping for the tweak-one-line-and-rerun loop: every run has its own commit, so you got one "— 1 run" header per run, doubling the row count for zero information. Grouping by script actually clusters a burst of reruns of the same file, and your choice now persists across reloads.
- **Empty columns stop hoarding table width** — with no tags/studies/stages set, three columns rendered as a wall of `--` at full width while Name and Metrics, the two you actually scan, were clipped. A column with no data anywhere in the current view now collapses to a narrow strip (and expands again the moment a value appears), the freed space goes to Name (250px) and Metrics (190px), and the table's header/cell gutters were tightened so a header like "STATUS" no longer needs ~86px just to render its own label — headers such as `STAT…` and `STARTE…` now fit.
- **Run names truncate in the middle, not at the end** — an auto-generated name (`Jul28_ablate__lr0.01__2aac1081`) differs from its neighbours only in its tail, so head-truncation turned a rerun burst into a screen of identical `Jul28_abl…` rows. Names now keep both ends (`Jul28_ablat…_2aac1081`), sized to the actual column width, with the full name in the tooltip. Tag/study chips also break between words instead of mid-word.

## [1.46.1] - 2026-07-23

### Fixed
- **Failed runs now appear when the "Failed" status chip is selected** — clicking the sidebar's **Failed** status chip loaded only failed runs, but the default "hide failed runs" filter then stripped them all back out, so the sidebar (and main table) showed nothing. The hide-failed filter is now skipped when you've explicitly filtered to the Failed status, so the chip works as expected; the *Show failed* toggle still governs the default (unfiltered) view.
- **Filmstrip navigation no longer force-opens the sidebar** — stepping between runs via the detail-view filmstrip (clicking a card, the `‹ ›` buttons, or ←/→) is a lateral move between already-open runs, but it was treated like a fresh entry into the detail view and re-expanded the collapsed sidebar every time. Filmstrip navigation now leaves the sidebar in whatever state you set it.

## [1.46.0] - 2026-07-23

### Added
- **Experiment filmstrip in the detail view** — a horizontal, scrollable strip of mini-cards (one per run in the current filtered + sorted list) is pinned at the top of every run's detail panel so you can flip between runs without going back to the table. The open run is highlighted and auto-centered; each card shows the run's name, a status dot, its primary-metric value, and a coloured delta badge vs. the older neighbour so "what changed" reads at a glance. Click a card, use the `‹ ›` buttons, or press ←/→ to step through runs (arrow keys ignored while typing). The primary metric follows the *Sort by metric* selection when set, else the run's first metric; deltas reuse the shared `metricDelta()` helper so arrows/colours match Compare and the "What changed" card. A `N / M` counter shows your position.

### Changed
- **Group-by bar no longer overflows** — the toolbar row (Group by · Show · toggles · Sort by metric) now wraps to a second line instead of running off the edge on narrower windows, and the seven *Group by* buttons are consolidated into a single compact dropdown to reclaim horizontal space.
- **ID column hidden by default** — the main experiment table no longer shows the internal run-ID (hash) column by default; it stays available (unchecked) in the ⚙ Columns panel for anyone who needs it for CLI/reproduce. Existing users' saved column choices are preserved.

## [1.45.1] - 2026-07-23

### Added
- **Runnable TensorBoard auto-capture demo** — `examples/tensorboard_example.py` shows the zero-code metric path end to end: a plain training script that logs scalars to a normal `SummaryWriter` (no exptrack imports, no `log_metric`) run via `exptrack run` has its `loss`/`acc`/`schedule/lr` mirrored into exptrack's metrics table, while TensorBoard's own `runs/*.tfevents` files are still written (the patch is a tee, not a replacement). Needs `pip install tensorboardX` (or torch).

## [1.45.0] - 2026-07-23

### Fixed
- **No more leftover empty wrapper row from an explicit-args sweep under `exptrack run`** — the 1.44.0 adoption fix deliberately does *not* merge a script that constructs its own `Experiment(name=…, params=…)` per iteration (a param sweep) into the `exptrack run` wrapper, because adopting would silently drop each run's distinct name/params. That left the correct behavior for the sweep runs but a downside: the wrapper itself was left with the code snapshot and *no metrics of its own* — a phantom row that cluttered the experiment list and re-introduced the same `None→value` flood when the next run compared against it. Now, when the wrapper sees a script build its own run(s) and logs no metrics itself, it is **moved to Trash** at finish (soft-delete — fully recoverable, no files touched), so only the real sweep runs remain in the list. A hybrid wrapper that logged its own metrics is kept, and a resumed run (`--resume`) is never trashed. Plain `python`, cooperative `__exptrack__` scripts, single self-tracking scripts (which adopt the wrapper), and notebooks are all unaffected.

## [1.44.0] - 2026-07-23

### Fixed
- **`exptrack run` no longer creates a phantom metrics-less duplicate run** — running a script that creates its *own* `Experiment()` (one written for plain `python script.py`, e.g. `examples/manual_tracking.py`, with `with Experiment() as exp:`) under `exptrack run` used to produce **two** experiments for one script: the wrapper `exptrack run` starts (it gets the code snapshot + argparse params but *no* metrics, because the script logs onto its own object) and the script's own run (which gets the metrics). That metrics-less wrapper was the confusing "first run with no metrics — just a snapshot." The wrapper is now published so the script's first bare `Experiment()` **adopts** it instead of inserting a second row — one run, snapshot + params + metrics together. Adoption is deliberately narrow and safe: only a bare `Experiment()` (no arguments) adopts, and only the first one, so a script that passes its own `name`/`params` (a sweep) is never silently merged and keeps its own rows; plain `python script.py`, cooperative scripts that use the injected `__exptrack__` global, and notebooks are all unaffected. `python -m exptrack` also makes its post-run finish tolerant of a run the script already finished, so an adopted `with`-block (success or failure) never triggers a double-finish error.
- **Run comparison no longer floods with bogus `None→value` changes** — the finish-time "vs previous" summary (`diff_runs`) and the dashboard "What changed" card reported every metric present in only *one* of the two runs as a change (`acc None→0.87`, with a null delta), because the comparison filled the missing side with `None`/`undefined` and treated `None != 0.87` as a real move. A metric the baseline run never logged isn't a value change — it was simply not measured — so it's now skipped. This kills the flood when comparing against a metrics-less run (the phantom above) *and* the legitimate case of comparing a new run against an older one made before you added metric logging. A genuine value move (both sides present) is still reported.

## [1.43.1] - 2026-07-23

### Fixed
- **`exptrack run` now records a real, runnable Reproduce command** — a run launched with `exptrack run ../examples/basic_script.py --lr 0.01` recorded only the bare script basename (`basic_script.py`) in its `command` column, so the dashboard Reproduce box showed something with no interpreter and no path — not runnable. The `--cmd` capture added in 1.43.0 only covered the shell-pipeline path (`run-start`/`run-finish`), never the `runpy` wrapper. Root cause: `cmd_run` rebuilt `sys.argv` so the script became `argv[0]`, then `_build_command()` basenamed it (that basename step was meant for the *interpreter* path, not the script). `__main__.main` now captures the real invocation as `python <absolute-script-path> <args>` *before* mutating argv and threads it into the experiment (new `command=` param on `Experiment`), so the Reproduce box shows a command you can actually paste and run.

### Added
- **Reproduce-box form toggle (`python` ⇄ `exptrack run`)** — the dashboard Reproduce box now has a small toggle to flip the shown command between the plain `python <abs-path> <args>` form (default, runs the script directly) and the tracked `exptrack run <abs-path> <args>` form (re-runs with exptrack capture). The two differ only by the interpreter prefix, so the conversion is lossless; the preference is remembered in localStorage (`exptrack-reproduce-tracked`) and Copy / Save-to-Commands / inline-edit all follow the displayed form.

## [1.43.0] - 2026-07-23

Combines the dashboard-usability / hook-logging work (Group-by-Script, "What changed" card, TensorBoard auto-capture) with the run/try/compare loop (L1–L6): change code → break a run → fix → rerun → see what changed → repeat.

### Added
- **TensorBoard metric auto-capture** — exptrack now mirrors `SummaryWriter` calls into its own metrics table with zero code changes, closing the gap where custom losses and activation stats logged through TensorBoard were invisible to exptrack (until now, a value only reached the metrics table via an explicit `exp.log_metric(...)`). A new `capture/tensorboard_patch.py` monkey-patches `SummaryWriter.add_scalar`/`add_scalars` (scalars → metrics) and `add_histogram` (activation/gradient distributions → `<tag>/{mean,std,min,max}` metrics) on both `torch.utils.tensorboard` and `tensorboardX`, the same way `plt.savefig()` is patched for plots. It patches writers already imported *and* installs a `sys.meta_path` hook so a writer imported later (the common case — the script's `import` runs after exptrack patches) is patched too; the originals still run so TensorBoard behaves exactly as before. No new dependency: exptrack patches the writer at the call site instead of parsing `.tfevents` files (which would need `tensorboard`/`protobuf`). Toggle via the new `auto_capture.tensorboard` config key (default on). Note: this captures anything routed through TensorBoard — a training loop that only `print()`s a loss still needs an explicit `exp.log_metric()`, since there's no library call to intercept there.
- **"What changed" card on the Overview tab** — every run's Overview now opens with a card auto-diffing its params against the previous experiment that used the same script, showing only the params that actually changed (`key | previous → this run`) plus a one-click **Compare** button to open the full side-by-side view. Aimed squarely at the "tweak one line, rerun, forget to rename" workflow — you no longer have to rename runs (or manually build a Compare) just to see what's different between two attempts. New `GET /api/experiment/<id>/prev-by-script` endpoint / `find_previous_by_script()` query.
- **Metric delta in the "What changed" card** — the card now also lists any metrics that changed since the previous same-script run (`key | previous → this run | delta`, arrow + color + % change), so "changed lr, got +5% acc" is visible in one glance instead of requiring a full Compare. Backed by a new `get_metrics_last()` query and shared with Compare's own metrics table via a common `metricDelta()` helper so the two never disagree on formatting.
- **Group by Script** — the sidebar's "Group by study" header button now cycles through **None → Study → Script** (📄 icon when grouping by script), and the main table's group-by bar gains a matching **Script** option. Groups by the training script's basename (`train.py`), so a burst of "tweak one line, run again" experiments against the same script collapses into one collapsible group instead of flooding the list — the specific pain point when the sidebar gets crowded during rapid iteration. `list_experiments`/`/api/experiments` now also expose the `script` field needed for this.
- **Broken notebook runs mark themselves failed** — a notebook cell that raises now records its traceback on the active run, and the automatic finish paths (kernel shutdown, starting a new run) mark that run `failed` with the traceback instead of silently `done`. An explicit `%exp_done` / `done()` still declares success even if the last cell raised. So a run that broke is self-identifying and never needs manual deletion to keep the list clean.
- **`auto_trash_failed` config (default off)** — when true, a run that finishes `failed` is moved straight to Trash, so the experiment list only ever shows runs worth comparing. Recoverable from the Trash view like any soft-delete.
- **"Show failed" toggle + failed runs hidden by default** — the dashboard experiment list now hides `failed` runs behind a **Show failed (N)** toggle in the group bar, so a morning of broken attempts doesn't bury the runs that worked.
- **Diff-vs-previous at finish** — every run now ends by printing a one-line summary of what changed versus the previous run of the same script (`lr 0.01→0.02 · code changed · acc 0.84→0.87`), so you see the delta without opening anything. Backed by `get_previous_run` / `diff_runs` / `format_run_delta` in `core/queries.py`.
- **"vs previous" strip in the dashboard detail view** — the same delta renders as a chip strip at the top of a run's detail (`GET /api/run-delta/<id>`), linking back to the previous run.
- **Real-command capture (`--cmd`)** — `exptrack run-start` / `run-finish` accept `--cmd "python train.py --lr 0.01"` to record the actual command a run was launched with, so a run wrapped inside a bash/SLURM script no longer records a truncated wrapper argv. Last writer wins (`run-finish --cmd` overrides).
- **Content-addressed code snapshots** — script and shell-script source is snapshotted at run time into a new `code_snapshots` table (deduped by content hash) and referenced from the `_code_snapshot` param, so a run stays re-runnable even after the file is edited. `.ipynb` files are never snapshotted (notebook JSON stays out of the record by design).
- **`%exp_new` magic + `start(new=True)`** — start a fresh notebook run without restarting the kernel, so each "run, run, try" attempt is its own comparable experiment. Put `%exp_new` at the top of the notebook to make every Run-All a separate attempt with zero per-cell ceremony.
- **Sort the experiment table by any metric** — a **Sort by metric** selector in the group bar orders runs by a chosen metric's latest value, so "which attempt was best?" is one click.
- **Code changes in the Compare view** — comparing two runs now shows a **Code changes** panel with the exact edit between them: paired cell-source diffs for notebook runs (via the executed `cell_exec` cells, since notebook JSON is excluded from git diffs), or the script-source snapshot diff for script runs, rendered with the shared word-level diff highlighter. Backed by `compare_run_code` in `core/queries.py`, surfaced on `/api/compare`.

### Fixed
- **Cross-notebook cell lineage bleed** — `lookup_stored_parent` matched a cell purely by content hash, so identical source in two different notebooks shared one lineage row and a cell's parent resolved in notebook A leaked into notebook B. The lookup is now notebook-scoped, so each notebook resolves lineage against its own history.
- **Git failure no longer masquerades as a clean tree** — `git diff` returning empty on an actual failure (contended `index.lock`, timeout, git error) was indistinguishable from a genuinely clean working tree, so a run with real uncommitted changes could be recorded as "all changes committed". `git_diff` now returns a `[capture-failed]` sentinel when the diff errors *inside a git repo* (empty stays empty outside one), rendered honestly wherever diffs are shown (CLI, dashboard detail + session views, export) and skipped by the compaction/stats paths instead of being treated as real diff text.

## [1.38.1] - 2026-07-19

### Fixed
- **Dashboard import crashed on Python 3.9** — `dashboard/handler.py` used the `str | None` union syntax in a method signature, which Python 3.9 evaluates at class-definition time and rejects (`TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`), breaking module import and collection of `tests/test_dashboard_security.py`. Added `from __future__ import annotations` to the module (matching every other module in the package) so annotations are lazily evaluated and the dashboard imports cleanly under 3.9.

## [1.38.0] - 2026-07-12

### Changed
- **Dashboard JS/CSS extracted to real static files** — the ~13k lines of dashboard JavaScript and CSS lived as big Python string constants in `static_parts/js/*.py` and `static_parts/css/*.py`, so they couldn't be edited with JS/CSS tooling (linters, formatters, editor language servers). The content now lives in `exptrack/dashboard/static/js/*.js` and `static/css/*.css`; each `static_parts` module is a thin loader shim that reads its file at import time, preserving every `JS_*`/`CSS_*` name and keeping the assembled bundles byte-for-byte identical. (Static files ship in the wheel + sdist via new `package-data`/`MANIFEST.in` entries.)
- **Dashboard JS/CSS served as cached external bundles** — the page previously inlined the full ~600 KB of JS/CSS into every HTML response. The JS and CSS are now served as separate `/static/dashboard.js` and `/static/dashboard.css` responses referenced by hash-versioned `<link>`/`<script src>`, so the browser caches them across reloads and the HTML shell drops from ~640 KB to ~31 KB. The `?v=<content-hash>` query busts the cache automatically on any change (no staleness), and the bundles are auth-exempt but Host-gated like the vendored Chart.js.

### Added
- **ESLint for the dashboard JS (dev-only)** — a flat `eslint.config.js` + `package.json` (`npm run lint`) lint the extracted JS for single-file correctness (duplicate keys/args/cases, unreachable code, accidental assignments, `const` reassignment, `typeof` typos, …). Node is a dev-only tool; the Python package remains stdlib-only and needs no Node to run.

## [1.37.0] - 2026-07-12

### Changed
- **Schema checks no longer run on every connection** — `_ensure_schema` used to probe every table (`PRAGMA table_info` × 7) and `PRAGMA quick_check` scanned the whole database file on every fresh connection (every CLI invocation, every notebook kernel). The database now carries a schema stamp (`PRAGMA user_version`); when it matches, both the integrity scan and all migration probes are skipped. A new or pre-upgrade database still gets the full check + migration on first open, and `exptrack upgrade` always forces a complete re-verify.
- **Finishing a run no longer scans the whole database** — `Experiment.finish()`/`fail()` closed the DB connection with an orphan sweep that runs five `COUNT(*)` anti-join scans over params/metrics/artifacts/timeline/cell_lineage; in a notebook or script that finishes many runs in one process this re-scanned the growing metrics/timeline tables on every run. Finishing a run only updates its own row and can't orphan anything, so the sweep is skipped there (`close_db(sweep=False)`); the per-command CLI exit and `exptrack clean` still sweep, so orphans from deletes are still collected.
- **Experiment list is paginated + search is debounced** — the dashboard fetched only the server's default top 50 experiments with no way to reach older runs, and re-filtered/re-sorted/rebuilt the entire table and sidebar on every search keystroke. The list now loads a full page (200) with a **Load more** button that pages through the rest (`/api/experiments?limit=&offset=`, new `offset` on `list_experiments`), and the search inputs debounce their re-render (150 ms) so fast typing no longer thrashes the DOM.

### Added
- **`offset` pagination on `list_experiments` / `/api/experiments`** — pages the experiment list past the first N rows (`ORDER BY created_at DESC`), backing the dashboard's "Load more".

### Fixed
- **Cell-lineage parent matching is no longer O(N²) per cell** — every executed notebook cell fuzzy-matched its source against *every* stored cell for that notebook with a full `SequenceMatcher.ratio()` (quadratic in cell length), even when re-running an unchanged cell. Re-runs now short-circuit on a single indexed lookup (`lookup_stored_parent` — a content-addressed cell's parent is already frozen), and the fuzzy search prunes candidates by a length band and `SequenceMatcher`'s cheap `real_quick_ratio`/`quick_ratio` upper bounds before computing the real ratio (behaviorally identical — verified against 20k random cases). A new `idx_cell_lineage_notebook` index speeds the candidate fetch.

## [1.36.2] - 2026-07-12

### Fixed
- **`exptrack ui --host 0.0.0.0` works again for network clients** — the 1.36.0 Host-header validation compared the client's `Host` against the literal bind address, but clients reaching a wildcard bind (`0.0.0.0`/`::`) send the machine's real name or IP, never `0.0.0.0` — so every non-loopback request got `403` and an all-interfaces bind effectively served loopback only. A wildcard bind now accepts any `Host` (binding all interfaces is an explicit opt-in to network exposure); the default localhost bind and specific-address binds keep the full DNS-rebinding defense.

## [1.36.1] - 2026-07-12

### Fixed
- **Back-to-back runs in one process no longer leak params onto the first run** — the argparse monkey-patch installed its `parse_args`/`parse_known_args` hooks once, closing over the *first* `Experiment`, so a second run created in the same process (a long-lived notebook kernel, programmatic reuse, or successive runs) kept logging every captured param onto experiment #1. The hooks now read a module-level active-experiment reference that each `patch_argparse(exp)` call retargets, so params always land on the current run.

## [1.36.0] - 2026-07-11

### Security
- **Stored-XSS hardening for inline dashboard handlers** — user-controlled values (experiment/session names, tags, studies, param & metric keys, artifact labels & paths, node labels) interpolated into inline `on*="…"` event handlers were HTML-escaped with `esc()` only. Inside a handler attribute the browser HTML-decodes the value *before* the JS engine parses it, so `esc()`'s `&#39;` decoded back to `'` and broke the button — or, with a crafted value from an arbitrary tracked script or a shared `.exptrack` DB, executed script. A new `escJs()` JS-string-context escaper (applied *before* `esc()`, via the composed `escJsAttr()` helper) now wraps every such site across the dashboard JS, and the ad-hoc quote-escapers were removed. A static `test_dashboard_js_integrity.py` guards the pattern (and that every inline handler references a defined function).
- **Host-header validation (DNS-rebinding defense)** — the dashboard now rejects any request whose `Host` header isn't a local name (`127.0.0.1`/`localhost`/`::1`) or the host it was explicitly bound to, returning `403`. Without this, a remote page resolving its own hostname to `127.0.0.1` could reach destructive endpoints same-origin.
- **`/api/file/` no longer serves `.exptrack/` internals** — the file route's path-traversal guard was correct, but its mime allow-list (`.json`/`.log`/…) let a token-holder fetch `.exptrack/config.json`, which holds the `dashboard_token`. Anything resolving under `<project>/.exptrack/` is now rejected with `403`; legitimate assets (logs under `outputs/`, plot images in the project tree) are unaffected.

### Changed
- **Chart.js is vendored locally** — the dashboard loaded Chart.js from `cdn.jsdelivr.net` (no SRI, broken offline, against the local-first promise). It now ships `chart.js@4.4.9` at `exptrack/dashboard/vendor/chart.umd.min.js`, served at `/vendor/chart.umd.min.js`, so charts render offline with no third-party request.
- **Malformed dashboard input returns `400`/defaults instead of `500`** — a non-JSON `POST` body now returns `400 Invalid JSON body` (was an unhandled `500` traceback), and junk numeric query params (`?limit=abc`, `?seq=abc`) fall back to their defaults via a shared `_qint()` helper.
- **CLI commands exit non-zero on failure** — `show`, `diff`, `compare`, `timeline`, `watch`, `export`, `note`, `edit-note`, `finish`, `study`, `unstudy`, `stage`, `tag`, and `untag` printed "Not found" (sometimes to **stdout**) and returned `0` on a missing experiment / bad argument, so `exptrack show $ID || handle_missing` never fired. Every hard-error / not-found path now routes through a shared `die()` (message to **stderr**, exit `1`); informational no-ops ("already done", "tag not found on any experiment") stay exit `0` but moved to stderr for stream consistency.

### Fixed
- **Batch export honours `--format params*`** — `exptrack export --all --format params` (and `params-flags`/`params-json`/`params-md`/`params-tsv`) silently emitted the full-JSON batch dump instead of the requested params style. Batch export now formats each run's params in the chosen style (`params-json` as a valid JSON array of `{id, name, params}`).
- **Augmented assignments (`x += 1`) are tracked** — a cell doing `x += 1` was misclassified as observational and its variable was never extracted, because the assignment detector treated the `+` before `=` as "not an assignment". Plain and augmented assignments (`+= -= *= /= //= %= **= &= |= ^= >>= <<= @=`) are now both recognized; `x += 1` reads as `x = x + 1` on the timeline.
- **Re-logging a param keeps its `source`** — `log_params` used `INSERT OR REPLACE`, which deletes and re-inserts the row and so reset a `manual` param back to the `auto` column default; it now upserts (`ON CONFLICT … DO UPDATE SET value`) and preserves `source`.
- **Metrics logged after a run finishes are ignored, not written** — `log_metric`/`log_metrics` warned "after experiment finished" but still inserted the point; they now return after the warning, matching `log_params`.
- **Git-diff file lists no longer mangle `b/`-prefixed paths** — a `diff --git a/x b/backbone.py` file summary used `str.lstrip("b/")`, which strips a *char set* and turned `b/backbone.py` into `ackbone.py`; a shared `diff_b_path()` now strips only the `b/` prefix (used across `core/db.py`, `cli/admin_cmds.py`, and the dashboard compact routes).
- **`github_sync` push timeout lowered** — the plugin's synchronous GitHub API calls on the run-finish path used `timeout=20`; reduced to `10s` so a hung request blocks a finishing run for less time.

### Removed
- **Dead code swept** — removed an `if False:` dispatch placeholder, a duplicate `api_delete_preview` route, unused CLI color imports, a doubled `gamma` in the hyperparameter regex, a legacy `cleanDatabase()` JS alias, an unreachable old-style `tag`/`untag` calling convention, and ~13 verified-dead dashboard CSS classes. The `static_parts/scripts.py` compat shim now re-exports all JS modules (was missing 7).

## [1.35.1] - 2026-07-11

### Fixed
- **`Experiment.resume()` no longer crashes** — every resume path (`Experiment.resume(id)`, `exptrack run --resume` auto-detect, and `run-start --resume`) raised `AttributeError` because the instance was built via `object.__new__` and never got `_defer_commit`, which the first `log_event` reads. Resume now works: you can reopen a finished run and keep logging metrics/params onto the same experiment.
- **`exptrack run-start --resume` actually resumes now** — the flag was dropped by the pre-argparse interception in `main.py`, so `--resume latest` was stored as a junk `resume` **param** on a brand-new run instead of continuing the previous one. `--resume` is now parsed on that path and excluded from captured params.
- **`exptrack clean --orphans` no longer crashes** — a missing `from pathlib import Path` import made the orphan scan raise `NameError` whenever the configured outputs directory existed.
- **`last_metrics()` keeps step-less metrics and returns the right value** — the old SQL (`GROUP BY key HAVING MAX(COALESCE(step,0))`) silently dropped any metric logged without a step (the common `log_metric(k, v)` case) and could return an arbitrary row's value for stepped metrics. A shared `core/queries.last_metrics()` now returns the latest value per key (by step, then timestamp, then insert order); the notebook/pipeline finish paths and `github_sync` use it.
- **Notebook `tag()` / `note()` now persist** — interactive `%exp_tag` / `exptrack.notebook.tag()` only wrote an in-memory list plus a hidden `_tags` param, so tags never reached the `experiments.tags` column and were invisible to the dashboard and CLI. `tag()` now routes through `Experiment.add_tag()` (deduped) and `note()` through `add_note()`, so both show up everywhere.
- **`exptrack finish` / `run-finish` plugin sync no longer silently fails** — these paths built incomplete experiment stand-ins for plugins, so `github_sync` hit `AttributeError` on the first missing field (`project`, `created_at`, `duration_s`, `script`, `_params`, `tags` as a list, …) and every sync was swallowed by the plugin registry. A single shared `plugins.make_exp_proxy()` now exposes the full interface on both paths.
- **Dashboard note "edit" button works after an inline save** — the rebuilt notes HTML called an undefined `editNotes()` (a `ReferenceError` on click); it now calls the real `startDetailNoteEdit()` on the `#detail-notes` element.
- **Rapid experiment switching no longer clobbers the detail panel** — `refreshDetail()` awaited several fetches then wrote the panel without re-checking which experiment is selected, so a slow response for run A could overwrite run B's panel. It now bails before any DOM write if the user navigated away mid-fetch.
- **Legacy `_result:*` params can no longer be stranded on migration** — the `metrics.source` migration backfill did all-or-nothing: one un-parseable `_result:*` value aborted the whole block, but the column already existed, so it never re-ran and those params were never migrated or cleaned up. The backfill is now per-row tolerant — good rows migrate into `metrics` and are deleted from `params`; a bad row is warned about and left in place.

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
