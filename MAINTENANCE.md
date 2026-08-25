# Maintaining exptrack — a handbook for the solo maintainer

This is the guide for keeping exptrack healthy **by yourself**, without an AI
pair sitting next to the code. It assumes you know Python but does not assume you
remember how this specific codebase is wired — that knowledge lives in
`CLAUDE.md` (the map) and `docs/design/` (the reasoning), and this handbook tells
you when to reach for each.

Read this once end to end. After that, you'll mostly come back to two sections:
**"The checks that matter"** and **"Working with Claude in a web browser."**

---

## 1. The checks that matter

**Your authoritative green light is CI**, not anything on your laptop. Every PR
runs the full suite on six Python versions plus both linters — that's the gate
that decides whether a change is safe to merge. You don't have to reproduce all
of that locally.

But you *do* want a fast local pre-check so you're not pushing obvious breaks and
waiting on CI. This one block is the same thing CI runs, in order — paste it
before a commit:

```bash
pip install -e ".[dev,integrations]"   # once per environment, not every time
pytest tests/ -q                       # the whole suite
python tests/run_all.py                # the legacy per-file runner (also in CI)
ruff check .                           # Python linter
npx eslint exptrack/dashboard/static/js  # dashboard JS linter
```

If all five are green, CI will almost certainly be green too. If any is red,
**don't commit** — the output tells you what broke.

The other two scripts, both thin and safe to run any time:

| Command | What it does | When |
|---|---|---|
| `python tests/smoke.py` | 30-second real end-to-end: init a throwaway project, run a script, read it back | When you want to *feel* that the tool still works, not just that tests pass |
| `python tests/release_check.py` | Verifies a release won't ship broken — version/changelog consistency + every dashboard and example asset is actually packaged (see §6) | Before tagging a release |

Two things worth knowing about that first block:

- **`.[dev,integrations]`, not just `.[dev]`.** The `integrations` extra pulls in
  matplotlib/numpy/pandas so the capture tests actually *run* instead of skipping.
  A skipped test is green, which would hide a real break — so installing these
  locally gives you the same coverage CI's dedicated `integrations` job enforces.
  (If you install only `.[dev]`, those tests skip silently and your local green is
  a weaker signal than CI's.)
- **You don't strictly need Node/eslint locally.** If `npx eslint` isn't set up on
  your machine, skip that line and let CI's `lint` job catch JS issues — just know
  that's the one part of the block you're deferring to CI.

That's the whole safety net. Everything else in this document is either "how to
read the output when it's red" or "how to make a change without making it red in
the first place."

---

## 2. What "healthy" looks like, and why you can trust it

exptrack is in unusually good shape, and it defends itself in ways worth
knowing about so you trust the green light:

- **1273 tests** across 75 files, plus a legacy runner that executes each test
  file as a standalone script.
- **CI runs on Python 3.9 through 3.14.** If you only have one Python locally,
  CI covers the rest — so "passes for me" is backed by "passes on six versions."
- **A CI job that fails if the capture tests skip.** exptrack's headline trick
  is monkey-patching argparse / matplotlib / TensorBoard. Those libraries aren't
  needed to *run* exptrack, so their tests skip when the libraries are absent —
  and a skipped test is green, which would hide a real break. CI installs those
  libraries in a dedicated job and **fails if the tests skip anyway.** This is
  why the local pre-check block (§1) installs the `integrations` extra: so you
  get the same coverage locally instead of a weaker green.
- **Two linters in CI**: `ruff` (Python) and `eslint` (dashboard JS).
- **stdlib-only.** The package imports nothing outside Python's standard
  library. There is no dependency tree to rot, no `pip` surprises, no
  supply-chain surface. This is the single biggest reason the project will age
  well. Protect it (see §5).

The practical upshot: the things most likely to break a Python project over
time — dependency drift, an untested Python version, a silently-skipped test —
are already fenced off. You are not maintaining a fragile thing.

---

## 3. The one genuinely fragile seam

There is exactly one part of exptrack that depends on **other people's code that
you don't control**: the capture layer in `exptrack/capture/`. It works by
monkey-patching functions inside `argparse`, `matplotlib`, and `tensorboard`. If
one of those libraries changes an internal signature in a future release, the
patch can break.

You do not need to watch for this. It's defended:

- The `integrations` CI job installs current versions of those libraries and
  **runs the patch tests against them.** An upstream signature change gets
  caught here — by you, in CI — rather than by a user whose training run
  crashes.
- Every patch is wrapped so that **if capture fails, the user's script keeps
  running.** That's the project's oldest rule: *a capture failure must never
  crash the user's training run.* (See `docs/design/patterns/capture.md`.)

**If the `integrations` job ever goes red after a library releases a new
version:** that's the signal. The fix is almost always local to one file in
`capture/` — read `docs/design/patterns/capture.md`, then the failing patch
file, and adjust the patch to the new signature. This is the one kind of
maintenance that will find *you* rather than you going looking for it.

---

## 4. Making a change safely (the loop)

The rhythm never changes:

1. **Branch.** Never work on `main`.
   ```bash
   git checkout main && git pull
   git checkout -b fix/whatever-it-is
   ```
2. **Find where the change goes.** Open `CLAUDE.md` and use the routing table
   under *"Which file to read, by what you're touching."* It maps a subsystem to
   the one design doc you should read first. **Read that doc before editing** —
   it's short, and it's where the non-obvious constraints are (the ones that
   look like they can be simplified but can't).
3. **Make the smallest change that does the job.** Match the surrounding code's
   style. Reuse the existing helpers named in `CLAUDE.md` → *Coding Best
   Practices* before writing new ones.
4. **Run the §1 pre-check block.** Green or you're not done.
5. **Update the paper trail** if the change is user-visible:
   - `CHANGELOG.md` — a bullet under the unreleased version.
   - `pyproject.toml` — bump `version` (patch for a fix, minor for a feature).
   - The relevant `docs/design/` file **only if** you changed how a documented
     behavior works. Most fixes don't need this. `CLAUDE.md` §"Rules for Changes"
     has the exact table for what to update when.
6. **Commit** with a message that says *why*, not just *what*.
7. **Open a PR** (even solo — it runs CI on all six Python versions before you
   merge). Merge when green.

If you internalize one thing: **small change, run the pre-check, commit.** The
repo's discipline does the rest.

---

## 5. Rules that keep the project healthy (don't break these)

These are the invariants that make exptrack ageless. Each one exists because
breaking it caused a real problem before.

- **stdlib only.** No `pip install` of a runtime dependency, ever. If you're
  tempted to add one, you almost certainly don't need to — the standard library
  is large. This rule is what makes the package installable and stable years
  from now with zero maintenance.
- **A capture failure must never crash the user's run.** Anything touching git,
  the filesystem, a plugin, or a patched library goes in a `try/except`, with the
  failure logged via `debug_log` (visible only under `EXPTRACK_DEBUG=1`).
- **Bump `_SCHEMA_VERSION` on any database change.** New table, column, index, or
  migration — bump it by 1 in `core/db.py`, or existing databases never run the
  migration. `docs/design/schema.md` explains the migration mechanics.
- **Edit the real `.js`/`.css` files, not the `.py` shims.** Dashboard code lives
  in `exptrack/dashboard/static/{js,css}/`. The `static_parts/*.py` files are
  ~3-line loaders — never put logic there.
- **Escape user values in inline HTML handlers with `escJsAttr`**, not `esc`.
  Plain `esc` there is a stored-XSS hole. A test enforces this, but know the
  rule so you don't fight the test.

When in doubt, the pattern doc for that subsystem (routing table in `CLAUDE.md`)
explains the *why*. The whole point of `docs/design/` is that it records what was
tried and what broke — so a future change doesn't quietly reintroduce an old bug.

---

## 6. Releasing a new version

Releases are automated. You never run `twine` or handle a PyPI token.

1. Make sure `main` is green and `pyproject.toml`'s `version` is bumped and
   `CHANGELOG.md` has the entry for it.
2. Run the pre-flight:
   ```bash
   python tests/release_check.py
   ```
   This confirms the changelog matches the version and — importantly — that
   **every dashboard static file is included in the package.** (Tests import the
   JS from source, so a JS file missing from the packaging config would still
   pass tests but ship a broken dashboard to users. This check is the guard
   against exactly that.)
3. On GitHub, **create a Release** with a tag like `v1.3.0`. Publishing the
   release triggers `.github/workflows/publish.yml`, which builds the package and
   uploads it to PyPI via trusted publishing (no token needed). It also does a
   non-blocking rehearsal upload to TestPyPI.
4. Watch the Actions tab. If the PyPI job is green, `pip install -U exptrack`
   will serve the new version within a couple of minutes.

`version` in `pyproject.toml` is the single source of truth — `__version__` reads
it from installed metadata, so there's nothing else to keep in sync.

---

## 7. Finding and fixing a bug in a codebase this big

You know how to write code. The hard part here is *navigation* — and in this repo
it's mechanical, because the map already exists. Don't read the codebase. Follow
this loop. It's the exact loop that found and fixed the `inf`/`nan` coercion bug
in v1.3.0, used here as a worked example.

**1. Start from a symptom phrased as "a user did X, got wrong Y."**
You don't need a bug report — you generate candidates by looking at the seams
where outside input enters (see the list at the end). Worked example: *"I passed
`--stage inf` and it got stored as a number, not the string `inf`."*

**2. Turn the symptom into a location with the map, not a full read.**
Open `CLAUDE.md` → the routing table *"Which file to read, by what you're
touching."* "Params captured from the command line" → `capture/` → read
`capture.md`. You read **one short doc**, not the module. That's the entire
purpose of that table.

**3. `grep` to the function, then run it — don't reason about it.**
```bash
grep -rn "_coerce" exptrack/            # find the function
python -c "from exptrack.capture.argparse_patch import _coerce; print(_coerce('inf'))"
```
Ten seconds, zero ambiguity. **Never argue with yourself about what code does
when you can execute it.** This one habit replaces most of what an AI pair did.

**4. Check blast radius before fixing — grep the *pattern*, not just the name.**
```bash
grep -rn "_coerce\|float(v)" exptrack/  # is this logic duplicated per layer?
```
That surfaced the twin, `_coerce_str` in `cli/pipeline_cmds.py`, doing the
identical thing on the shell path. In a layered codebase the same logic is often
copied per layer — fix all copies, or you half-fix the bug.

**5. Read the pattern doc for the invariant you might be breaking.**
`server.md` / `core/utils.json_dumps` say *why* non-finite floats are dangerous
(they break `JSON.parse` for the whole dashboard payload). That's how you know a
fix is *correct*, not just tidier. The `docs/design/` files exist to stop you
reintroducing an old bug — believe them over a tempting simplification.

**6. Reproduce with a failing test first, then fix, then watch it pass.**
The test proves the bug exists and proves you fixed it, and it's the guardrail so
a future edit (yours or Claude's) can't bring it back. Put it next to the
existing tests for that function (`grep -rn "def test.*coerce" tests/`).

**7. Run the §1 pre-check block, update the paper trail (§4 step 5), commit.**

Steps 1–4 *are* the skill you're missing — it's `symptom → map → grep → run it →
check for twins`, not "understand the whole codebase."

### Where to point this loop when hunting proactively

Bugs in a solo-maintained tool come from the **input seams**. Audit these first:

- `cli/*_cmds.py` — user arguments and coercion.
- `capture/*` — values coming from libraries you don't control (the fragile seam, §3).
- `dashboard/routes/write_routes/*` — POST bodies from the browser.
- `core/db.py` — anything that can hit a *locked database* during a parallel sweep.

### Triage when something's already broken

1. **Is it my change or was it already broken?** `git stash`, run the §1
   pre-check, `git stash pop`. Still red stashed → not you.
2. **When did it start?** `git log --oneline`, then `git bisect`. Every merge went
   through green CI, so "the last green commit" is a trustworthy anchor.
3. **What is it actually doing?** `EXPTRACK_DEBUG=1` re-run prints every capture
   failure a `try/except` swallowed — the intended way to see inside.
4. **Does the whole pipeline still work?** `python tests/smoke.py`. If units pass
   but it *feels* broken, this tells you whether the integration is intact.

---

## 8. Working with Claude in a web browser (no Claude Code)

You'll keep Claude as a thinking partner through the chat window at
[claude.ai](https://claude.ai) — you paste context in, you copy suggestions out
and apply them yourself. This works well **if you keep control of the file on
disk.** The failure mode — the "bigger mess" — is letting a chat session drive
edits it can't actually see the result of. Here's how to avoid that.

### The golden rules

1. **You hold the pen, not Claude.** In the browser, Claude cannot run your
   tests, cannot see your files, and cannot verify its own suggestion. *You* are
   the one who applies changes and runs the pre-check. Treat every Claude
   suggestion as a proposal from a smart colleague who is working from a
   photocopy — often right, sometimes out of date, never to be pasted in blind.
2. **One change at a time.** Ask for the smallest change that solves one problem.
   Apply it, run the pre-check, commit. Then start the next. A chat that rewrites
   three files at once gives you nothing to bisect when it's wrong.
3. **Always work on a branch.** `git checkout -b fix/x` before you apply anything
   from a chat. If it goes sideways, `git checkout .` throws it all away and you
   lost nothing.
4. **Never paste a whole file back over your file.** Claude will happily
   reproduce a 400-line file with "the fix applied." It will also silently drop a
   function, change unrelated whitespace, or hallucinate an import. Apply changes
   as **small, targeted edits you make by hand**, not by overwriting.

### What to paste in (this is the key to good answers)

The single best thing about this codebase for browser-Claude is that **its
context is already written down.** For most tasks you paste exactly three things:

1. **`CLAUDE.md`** — paste the whole thing at the start of a session. It's the
   map, and it's designed to be loaded first. It tells Claude the architecture,
   the rules, and which design doc governs what.
2. **The one relevant pattern doc.** Use the routing table in `CLAUDE.md` to find
   it (e.g. touching charts → `docs/design/patterns/metrics.md`). Paste that
   file. It carries the constraints Claude must not violate.
3. **Only the specific code you're changing** — the one function or the one file,
   not the whole package. If Claude needs a helper's signature, paste that
   helper's definition, not its entire module.

Then state the task in one or two sentences, and add the constraints explicitly:
*"stdlib only, keep the function under 40 lines, don't change the public
signature, give me a minimal diff — not the whole file."*

### A prompt template that works

> I maintain a local-first Python experiment tracker. Rules: **stdlib only**,
> functions stay small, capture code must never crash the user's script, and I
> want a **minimal targeted change, not a rewritten file**.
>
> Here is the project map (CLAUDE.md): «paste»
> Here is the design doc for the part I'm touching: «paste the pattern file»
> Here is the current code: «paste the one function/file»
>
> The problem: «describe it in 2–3 sentences, include the exact error if any».
>
> Propose the smallest change. Show me only the lines that change, with a few
> lines of context around them, and tell me which file and roughly where.

### Applying the answer safely

1. Read the suggested change and make sure you understand *why* it works. If you
   can't explain it, don't apply it — ask Claude to explain, or ask for a
   simpler version.
2. Make the edit **by hand** in your editor (or apply a small diff). Don't paste
   over the file.
3. Run the §1 pre-check. Red → tell Claude exactly what the failure said and
   iterate. Green → move on.
4. `python tests/smoke.py` if the change touched capture, the CLI, or the run loop.
5. Commit with a clear message. Now it's safe on disk and you can start the next
   change from a clean base.

### Things browser-Claude will get wrong (watch for these)

- **Stale line numbers / context.** It's working from what you pasted, which may
  not be the latest. Trust your file on disk over Claude's memory of it.
- **Suggesting a dependency.** If an answer says `pip install something`, that
  violates the stdlib-only rule. Push back: "stdlib only — do it without a
  dependency."
- **Reintroducing a fixed bug.** The pattern docs exist precisely because some
  "obvious simplification" was tried before and broke. If Claude suggests
  simplifying something a pattern doc warns about, believe the doc.
- **Forgetting the paper trail.** It won't remember to bump the version or update
  the changelog. That's on you (see §4, step 5).
- **Confidently rewriting more than you asked.** If you asked to fix one function
  and got three files back, discard it and ask again for just the one.

### When a task is too big for the chat window

If a change is large enough that you'd need to paste half the codebase, that's a
sign to **break it into steps** rather than to paste more. Ask Claude to first
help you *plan* the change as a numbered list of small edits. Then do them one at
a time, each with its own pre-check. A sequence of small verified steps beats
one big paste every time — and it's exactly how Claude Code worked under the
hood, too.

---

## 9. The map of where things live (quick reference)

You don't need to memorize the architecture — `CLAUDE.md` has the full map and a
routing table. The 30-second version:

- **`exptrack/core/`** — the engine: the `Experiment` lifecycle, the SQLite
  database, queries, analysis (leaderboards, param studies, primary metric).
- **`exptrack/capture/`** — the monkey-patching that captures data with no user
  code changes. The fragile seam (§3).
- **`exptrack/cli/`** — the terminal commands. `main.py` is a thin dispatcher;
  the actual commands live in `*_cmds.py` files grouped by kind.
- **`exptrack/dashboard/`** — the local web UI. Server in `app.py`/`handler.py`;
  the real JS/CSS in `static/{js,css}/`.
- **`exptrack/sessions/`** — Session Trees (the opt-in exploratory notebook
  feature).
- **`docs/design/`** — *why* the code is shaped the way it is. Read the relevant
  file before changing a subsystem.

When you need more than this, `CLAUDE.md` → the routing table → the one pattern
doc it points you to. That path is designed to get you the context for a task in
a single read.
