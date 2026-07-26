# exptrack Audit Remediation — Implementation Spec

Handoff document for an implementing agent. Every finding below was verified against the
source at v1.35.0 (all file:line references checked). Implement in phase order; each fix
lists the exact change and the tests to add.

## Ground rules

- **Branch:** develop on `claude/codebase-audit-z1f50t` (exists). Commit per phase (or per
  logical group), push with `git push -u origin claude/codebase-audit-z1f50t`.
- **Run tests** with `python -m pytest tests/ -x -q`. Baseline: 532 passed, 5 skipped
  (optional deps). The suite must stay green after every phase.
- **Repo rules (from CLAUDE.md):** every user-visible change updates (1) `CLAUDE.md` where
  the documented behavior changes, (2) `CHANGELOG.md` (Keep-a-Changelog format, bold short
  title per bullet), (3) `pyproject.toml` version. Do ONE version bump for this whole batch
  at the end: **1.35.0 → 1.36.0** (minor: new vendor route + security behavior changes).
- **stdlib only.** No new dependencies anywhere.
- Existing test fixtures: see `tests/conftest.py` and `tests/test_pipeline_shell.py` for
  the tmp-project + DB fixture patterns; reuse them.

---

## Phase 1 — Verified high-impact bug fixes

### F1 (H1) — `Experiment.resume()` crashes: missing `_defer_commit`  · S

**Problem.** `exptrack/core/experiment.py:157-193`: `resume()` builds the instance via
`object.__new__(cls)` and sets attributes manually, but never sets `_defer_commit`
(assigned only in `__init__` at line ~144, no class default). `resume()` ends with
`exp.log_event("resume", ...)` → `_maybe_commit()` → `if not self._defer_commit:` →
**AttributeError**. Every resume path is dead: `Experiment.resume()`, `exptrack run
--resume` auto-detect (`__main__.py`), and `run-start --resume` (`pipeline_cmds.py:209`).

**Fix.**
1. Add a class-level default on `Experiment` (top of the class body):
   ```python
   _defer_commit = False
   ```
   (Keep the `self._defer_commit = False` in `__init__`; the class attr is the safety net
   for `object.__new__` construction.)
2. In `resume()`, also set the other `__init__`-only attrs that lifecycle methods read.
   Audit by grepping `self\._` / `self\.` usage in `finish()`, `fail()`, `log_*`,
   `_save`-adjacent code. At minimum set: `exp._defer_commit = False`,
   `exp.name_is_auto = False`, `exp.duration_s = None` if `finish()`/`fail()` read it
   before assignment. Verify each is actually needed rather than blindly adding.

**Tests — new file `tests/test_resume.py`:**
- `test_resume_by_id`: create+finish an Experiment, `Experiment.resume(exp.id)` returns an
  instance; DB row status flips back to `running`. (This alone crashes today.)
- `test_resume_logs_timeline_event`: after resume, a `timeline` row with
  `event_type='resume'` exists with seq > previous max.
- `test_resume_by_prefix`: resume with the first 6 chars of the id.
- `test_resume_unknown_raises`: `pytest.raises(ValueError)`.
- `test_resume_then_log_and_finish`: after resume, `log_metric`, `log_params`,
  `log_event`, and `finish()` all work; metrics aggregate onto the same exp_id; duration
  set; status `done`.
- `test_resume_batched_writes`: `with exp.batched_writes(): exp.log_params({...})` works
  after resume (exercises `_defer_commit` save/restore).

### F2 (H3) — `exptrack clean --orphans` crashes: `NameError: Path` · S

**Problem.** `exptrack/cli/mutate_cmds.py:412` calls `Path(r["output_dir"]).resolve()`;
the module never imports `Path` (imports are lines 6-14). Crashes whenever the configured
outputs dir exists.

**Fix.** Add `from pathlib import Path` to the imports in `mutate_cmds.py`.

**Tests — add to a new `tests/test_clean_orphans.py` (or existing clean tests if any):**
- In a tmp project: create an experiment with an `output_dir` pointing into `outputs/`,
  create `outputs/` with one orphan subdir not referenced by any experiment. Call the
  clean command body with `SimpleNamespace(orphans=True, yes=True, ...)` (match the real
  arg names from `main.py`'s `clean` subparser). Assert: no exception, orphan reported,
  referenced dir untouched.

### F3 (H2) — `run-start --resume` never resumes · S

**Problem.** `exptrack/cli/main.py:69-84`: `run-start` is intercepted *before* argparse
with a mini-parser that omits `--resume`. So `--resume latest` lands in `unknown` →
`known.params` → stored as a junk `resume` param on a **new** run.
`_RUN_START_RESERVED` (`pipeline_cmds.py:139`) doesn't include `"resume"` either. The
real subparser (`main.py:113-128`, which defines `--resume` with `nargs="?"`,
`const="latest"`, `default=None`) is unreachable unless a global flag precedes the
subcommand. Docs (`docs/cli-reference.md:22`) describe the broken flag as working.

**Fix.**
1. In the pre-parse block (`main.py:70-78`) add, matching the subparser exactly:
   ```python
   p_rs.add_argument("--resume", nargs="?", const="latest", default=None)
   ```
2. Add `"resume"` to `_RUN_START_RESERVED` in `pipeline_cmds.py:139` (belt-and-braces for
   the subparser path, where `--resume` placed after the first positional param falls into
   the REMAINDER).
3. Do **not** delete the real subparser (it still serves `exptrack <global-flag>
   run-start ...`); just keep the two argument lists identical. Add a comment on each
   pointing at the other.

**Depends on F1** (resume must work at all).

**Tests — new file `tests/test_run_start_resume.py`** (drive through `main()` with
`monkeypatch.setattr(sys, "argv", [...])` and capture stdout — this exercises the
pre-parse interception that the existing tests bypass by calling `cmd_*` directly):
- `test_run_start_resume_by_id`: run-start once, parse `EXP_ID` from the emitted
  `export EXP_ID=...`; run-start again with `--resume <id> --lr 0.02`; assert same id
  emitted, **no param named `resume`** stored, and `lr` updated to 0.02.
- `test_run_start_resume_latest`: bare `--resume` resumes the most recent run for the
  same script.
- `test_run_start_resume_no_previous`: `--resume` with an empty DB creates a new run
  (stderr contains "No previous experiment").
- `test_run_start_resume_before_params`: `--resume latest --lr 0.01` — `lr` captured as a
  param, `resume` not.

### F4 (M1) — `last_metrics()` SQL drops step-less metrics / returns arbitrary rows · S

**Problem.** `exptrack/core/experiment.py:442-450`:
```sql
SELECT key, value FROM metrics WHERE exp_id=?
GROUP BY key HAVING MAX(COALESCE(step, 0))
```
(a) `HAVING MAX(COALESCE(step,0))` is a boolean filter: any key whose steps are all
NULL/0 → `HAVING 0` → group dropped entirely (the common `log_metric(k, v)` case).
(b) bare `value` isn't tied to the max-step row (the MAX is in HAVING, not SELECT) → an
arbitrary row's value is returned. The same broken SQL is duplicated in the
`_FakeExp.last_metrics` lambda at `cli/pipeline_cmds.py:436-439`.

**Fix.** Add one shared helper in `exptrack/core/queries.py`:
```python
def last_metrics(conn, exp_id: str) -> dict:
    """Latest value per metric key (by step, then ts, then insert order)."""
    rows = conn.execute(
        "SELECT key, value FROM metrics WHERE exp_id=? "
        "ORDER BY COALESCE(step,-1), ts, rowid", (exp_id,)).fetchall()
    return {r["key"]: r["value"] for r in rows}   # later rows overwrite earlier
```
Use it from `Experiment.last_metrics()` and from the pipeline proxy (see F6). Delete both
copies of the broken SQL.

**Tests — `tests/test_queries.py` (or new `tests/test_last_metrics.py`):**
- step-less: log `loss=0.5` then `loss=0.3` (no step) → `{"loss": 0.3}` (today: `{}`).
- stepped out of order: `acc step=10 → 0.9`, `acc step=5 → 0.7` → `0.9`.
- mixed keys, mixed step/step-less.

### F5 (M2) — Notebook `tag()` never persists to the `tags` column · S

**Problem.** `exptrack/notebook.py:87-90`:
```python
def tag(*tags):
    exp = _require()
    exp.tags.extend(tags)
    exp.log_param("_tags", exp.tags)
```
Mutates the in-memory list + writes a `_tags` *param*; never touches
`experiments.tags`. `finish()` doesn't write tags either, so interactive tags are
invisible to the dashboard/CLI. `Experiment.add_tag()` (`experiment.py:346`) does it
correctly.

**Fix.** Route through the real mutator (verify `add_tag`'s exact signature first):
```python
def tag(*tags: str) -> None:
    exp = _require()
    for t in tags:
        exp.add_tag(t)
```
Drop the `_tags` param write (it was never read back — grep to confirm; if something
reads `_tags`, keep writing it too). Similarly check `notebook.note()` (`notebook.py:93`)
— it reimplements `set_note`/`add_note` with raw SQL; switch it to `exp.add_note(text)`
if the semantics match (append). Verify `add_note`'s newline behavior matches before
swapping.

**Tests — `tests/test_notebook_api.py` (new or existing):** set a fake active experiment
(`notebook._active = exp` or via its setter), call `tag("a", "b")`, read the
`experiments.tags` column from the DB → `["a","b"]`; call again with a duplicate →
no duplicate (match `add_tag` semantics).

### F6 (M3) — `exptrack finish` plugin proxy is missing fields; github_sync always fails · S

**Problem.** `cli/mutate_cmds.py:521-530` builds `_FinishProxy` with only
`id`/`name`/`status`. `github_sync._push` (`plugins/github_sync.py:64-79`) reads
`project`, `created_at`, `duration_s`, `script`, `git_branch`, `git_commit`, `git_diff`,
`_params`, `last_metrics()`, `tags`, `notes` → `AttributeError`, swallowed by the plugin
registry → every sync from `exptrack finish` silently fails.
**Additional verified nuance:** the pipeline path's `_FakeExp`
(`pipeline_cmds.py:425-440`) copies raw row columns, so (a) it has **no `project`**
attribute (`project` is not an `experiments` column — github_sync crashes on this path
too), and (b) `fake.tags` is the raw JSON **string**, not a list.

**Fix.** Add ONE shared proxy builder, e.g. in `exptrack/plugins/__init__.py`:
```python
def make_exp_proxy(conn, exp_id: str, status: str = "done", duration_s=None):
    """Build a plugin-facing experiment stand-in from DB rows (full interface)."""
    from ..core.queries import last_metrics
    from .. import config as cfg
    row = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
    p = types.SimpleNamespace(**{k: row[k] for k in row.keys()})
    p.status = status
    p.duration_s = duration_s if duration_s is not None else row["duration_s"]
    p.tags = json.loads(row["tags"] or "[]")
    p.project = cfg.load().get("project", cfg.project_root().name)
    p._params = {r["key"]: json.loads(r["value"]) for r in conn.execute(
        "SELECT key, value FROM params WHERE exp_id=?", (exp_id,)).fetchall()}
    p.last_metrics = lambda: last_metrics(conn, exp_id)
    return p
```
Use it in **both** `cmd_finish` (replacing `_FinishProxy`) and `cmd_run_finish`
(replacing `_FakeExp`). Keep the surrounding try/except so plugin failure never breaks
the command.

**Tests — new `tests/test_plugin_proxy.py`:**
- Register a capture plugin (subclass `Plugin`, record the exp object in `on_finish`)
  directly on the registry; run `cmd_finish` on a running experiment; assert the captured
  object has ALL fields github_sync reads (`project`, `created_at`, `duration_s`,
  `script`, `git_branch`, `git_commit`, `git_diff`, `_params`, `tags` as a **list**,
  `notes`) and `last_metrics()` returns the logged metrics.
- Same assertion for `cmd_run_finish`.

### F7 (M8) — Undefined `editNotes()` in rebuilt notes HTML · S

**Problem.** `dashboard/static_parts/js/inline_edit.py:298` — after an inline note save,
the detail panel is rebuilt with `onclick="editNotes('<id>')"`. `editNotes` is defined
nowhere (verified). Clicking → `ReferenceError`. The real editor is
`startDetailNoteEdit(id, el)` (`js/mutations.py:148`); the pristine render uses
`ondblclick="startDetailNoteEdit('${exp.id}', this)"` on the `#detail-notes` span
(`js/detail.py:519`).

**Fix.** In `inline_edit.py:298`, replace the button handler with:
```js
onclick="startDetailNoteEdit('` + id + `', document.getElementById('detail-notes'))"
```
(match quoting style of the surrounding template string; the element passed must be the
`#detail-notes` span, same as the pristine path).

**Test.** Covered by the new JS integrity test in F10 below (it would have caught this).

### F8 (M9) — `refreshDetail` async race clobbers the wrong panel · S

**Problem.** `js/detail.py:200-445` — `refreshDetail(id)` awaits several fetches then
writes `#detail-panel.innerHTML` without re-checking identity. Click exp A then quickly
exp B: A's slower response overwrites B's panel. (The auto-refresh poll at `detail.py:704`
already guards; the main path doesn't.)

**Fix.** Immediately after each `await` batch and before ANY DOM write in
`refreshDetail`, add:
```js
if (currentDetailId !== id) return;   // user navigated away while we were fetching
```
Note `currentDetailId = id;` is set at line ~207 — the guard works because a later click
on B updates `currentDetailId` before A's response lands.

**Test.** Not unit-testable without a JS runtime; verify manually (see Verification).

### F9 (M10) — `_migrate_metrics` can strand legacy `_result:*` params forever · S

**Problem.** `core/db.py:399-421`: the `source` column is added first; the backfill then
does `float(json.loads(r["value"]))` inside a single list comprehension. One bad value →
exception → outer `except` warns and aborts — but the column now exists, so on every
future connection `_add_columns` returns empty and the whole block is skipped. The
`_result:*` params never migrate and never get cleaned up.

**Fix.** Make the backfill per-row tolerant and delete only what migrated:
```python
if "source" in added and result_params:
    ts = datetime.now(timezone.utc).isoformat()
    migrated = []
    for r in result_params:
        try:
            migrated.append((r["exp_id"], r["key"][8:], float(json.loads(r["value"])), ts, "manual"))
        except Exception:
            print(f"[exptrack] warning: could not migrate param {r['key']!r}", file=sys.stderr)
            continue
        conn.execute("DELETE FROM params WHERE exp_id=? AND key=?", (r["exp_id"], r["key"]))
    if migrated:
        conn.executemany("INSERT INTO metrics (exp_id, key, value, step, ts, source) VALUES (?,?,?,NULL,?,?)", migrated)
```
(Keep the structure consistent with the surrounding `_migrate_*` helpers; note the key
slice `[8:]` assumes the `'_result:'` prefix — keep as-is.)

**Tests — extend `tests/test_db.py` migration tests:** build a legacy-shaped DB (metrics
table without `source`; params containing one good `_result:acc` = `"0.9"` and one bad
`_result:junk` = `'"not-a-number"'`), open with `get_db()` → good row lands in `metrics`
with `source='manual'`, bad row **remains in params** (not deleted), no exception, and a
second open is a no-op.

### Phase 1 bookkeeping

- `CHANGELOG.md`: one `### Fixed` bullet per F1-F9 (bold short title + one sentence).
- `CLAUDE.md`: no pattern rewrites needed for F1-F9 except: the **Auto-resume detection**
  bullet is now actually true (no text change needed); mention the shared plugin proxy in
  the `plugins/__init__.py` line of the architecture map.
- Commit: `fix: repair resume paths, clean --orphans, last_metrics, notebook tags, plugin proxy, dashboard note-edit + migration stranding`.

---

## Phase 2 — Security hardening

### F10 (H4) — JS-string-context escaping (stored XSS + apostrophes break buttons) · M

**Problem.** `js/mutations.py:5` `esc()` HTML-entity-escapes (incl. `'`→`&#39;`), but
~40 call sites interpolate user data **inside inline handler attributes**, e.g.
`js/detail.py:487`:
```js
onclick="deleteExp('${exp.id}','${esc(exp.name)}')"
```
The browser HTML-decodes the attribute *before* the JS engine parses it, so `&#39;`
becomes `'` again and terminates the JS string literal. Any experiment name / tag /
study / param key / metric key / artifact label or **path** containing `'` breaks the
button; a crafted value (artifact paths and params come from arbitrary scripts run under
`exptrack run`, or a shared `.exptrack` DB) executes script — stored XSS.

**Fix.**
1. Add a JS-context escaper next to `esc()` in `js/mutations.py` (function declarations
   are hoisted across the single concatenated script, so placement is safe):
   ```js
   function escJs(s) {
     if (s == null) return '';
     return String(s).replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'\\"')
                     .replace(/</g,'\\x3c').replace(/>/g,'\\x3e')
                     .replace(/\n/g,'\\n').replace(/\r/g,'\\r');
   }
   ```
2. **Composition rule:** inside an inline handler the value passes through HTML decoding
   then JS parsing, so the correct nesting is `esc(escJs(value))` — JS-escape first, then
   HTML-attribute-escape.
3. Site inventory: in `exptrack/dashboard/static_parts/js/`, grep each module for
   interpolations inside `on*="..."` attributes:
   `grep -n "on[a-z]*=\\\\\"" *.py | grep '\${'` and also template-literal built handlers
   using `\' + var + \'`. Known confirmed sites to fix (non-exhaustive — do the full
   sweep): `detail.py:261,264,267,283,284,324,328,380,390,487`,
   `experiments.py:120,228`, `sidebar.py:77`, `core.py:396-397,645-646,659-660`,
   `todos.py:59,127-129` (its ad-hoc `v.replace(/'/g,"\\'")` misses `"` and backslash —
   replace with `esc(escJs(v))`), plus equivalents in `sessions.py`, `trash.py`,
   `studies.py`, `commands.py`, `confusion.py`, `timeline.py`. Only values that can
   contain user data need `escJs` (ids generated by `uuid.hex` are safe, but wrapping
   them too is harmless — prefer consistency at sites that mix id + name).
4. Consolidate duplicate HTML escapers: `escapeHtml` (`sessions.py:1492`) and `escx`
   (`confusion.py:659`) have identical bodies to `esc`. Reduce each to
   `function escapeHtml(s){ return esc(s); }` (keep the names — other lines reference
   them) or replace their call sites with `esc`.

### F10b — JS integrity regression test (catches F7/H4-class bugs) · S

**New file `tests/test_dashboard_js_integrity.py`** (pure-Python static checks over the
assembled bundle — no JS runtime needed):
```python
from exptrack.dashboard.static_parts.js import get_all_js
```
- `test_all_inline_handlers_are_defined`: regex all identifiers invoked in inline
  handlers, `re.findall(r'on(?:click|dblclick|change|input|keydown|blur|submit|error|mouse\w+)="([A-Za-z_$][\w$]*)\(', html_and_js)`
  over `get_all_js()` **and** `static_parts.html` content; assert each name has a
  `function <name>(` (or `const <name> =`) definition in the bundle. Allow-list browser
  globals (`event`, etc.) as needed. *(This test fails today on `editNotes` — land it
  with F7.)*
- `test_escjs_defined_once`: `escJs` appears exactly once as a definition.
- `test_no_raw_esc_in_handler_strings` (best-effort guard): assert no occurrence of
  `('${esc(` inside an `on*="` attribute without `escJs` — implement as a targeted regex
  over the known-risky pattern `'\$\{esc\((?!escJs)` within lines containing `on[a-z]+="`.
  Tune until it passes on the fixed tree; it prevents regressions at new sites.

### F11 (M6) — Host-header validation (DNS-rebinding) · S

**Problem.** `dashboard/handler.py` `do_GET`/`do_POST` never validate `Host`. The server
binds 127.0.0.1 by default (`app.py:18`), but DNS rebinding makes a remote page's
requests same-origin, bypassing the JSON-preflight mitigation, and reaching destructive
endpoints (`/api/reset-db`, bulk permanent delete) once the token is presented or
`--no-auth` is used.

**Fix.** In `DashboardHandler`, add a check at the top of both `do_GET` and `do_POST`:
```python
def _host_allowed(self) -> bool:
    host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
    return host in ("127.0.0.1", "localhost", "::1", getattr(self.server, "allowed_host", ""))
```
→ if not allowed: `self.send_error(403, "Forbidden: bad Host header")`. In `app.main`,
set `server.allowed_host = host` after constructing `HTTPServer` so non-local binds
(already gated at `app.py:41`) keep working.
Note the `rsplit(":", 1)` + `strip("[]")` handles `host:port` and `[::1]:7331`.

**Tests — extend the existing dashboard route tests** (see how `tests/test_dashboard*.py`
drive the handler): request with `Host: evil.example` → 403; `Host: 127.0.0.1:7331` and
`Host: localhost` → 200.

### F12 (M7) — Vendor Chart.js locally · S

**Problem.** `static_parts/html.py:14`:
`<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>` — no SRI, breaks
offline, contradicts local-first.

**Fix.**
1. Download the UMD build once (pin a version): 
   `curl -L -o exptrack/dashboard/vendor/chart.umd.min.js https://cdn.jsdelivr.net/npm/chart.js@4.4.9/dist/chart.umd.min.js`
   (any current 4.x is fine; record the version in a comment/README in `vendor/`).
   **If the implementing environment has no network:** fall back to keeping the CDN tag
   but pin the exact version AND add `integrity="sha384-..."` + `crossorigin="anonymous"`,
   and note the deviation in the CHANGELOG.
2. Make it a package: `exptrack/dashboard/vendor/__init__.py` is NOT needed if you serve
   by file path; ensure packaging picks it up — add to `MANIFEST.in`
   (`include exptrack/dashboard/vendor/*.js`) and `[tool.setuptools.package-data]` in
   `pyproject.toml` (check current packaging config and mirror it).
3. Serve it: in `handler.py` `do_GET`, add a route `path == "/vendor/chart.umd.min.js"` →
   read the file relative to the package
   (`Path(__file__).parent / "vendor" / "chart.umd.min.js"`), send with
   `Content-Type: application/javascript` and a long `Cache-Control`. **This route must
   be exempt from the auth-token check** (the script tag can't carry the token) — mirror
   however `/` (the HTML page) is exempted; it must still pass the Host check.
4. `html.py:14` → `<script src="/vendor/chart.umd.min.js"></script>`.

**Tests:** GET `/vendor/chart.umd.min.js` → 200, `application/javascript`, body length >
100k; `DASHBOARD_HTML` contains no `cdn.jsdelivr`.

### F13 — Malformed input → 400, not 500 · S

**Problems.** `handler.py:204`: `json.loads(self.rfile.read(...))` unguarded → non-JSON
POST body raises → 500 traceback. `read_routes.py:28` (`int(qs.get("limit", 50))`) and
`read_routes.py:121` (`int(qs.get("seq", 999999))`) → `?limit=abc` → 500.

**Fix.**
- Wrap the body parse: `try: body = json.loads(...) except (ValueError, UnicodeDecodeError): self.send_error(400, "Invalid JSON body"); return`.
- Add to `read_routes.py` a tiny helper and use it at both sites (and any other bare
  `int(qs.get(...))` you find in the routes — grep `int(qs.get`):
  ```python
  def _qint(qs, key, default):
      try: return int(qs.get(key, default))
      except (TypeError, ValueError): return default
  ```

**Tests:** POST `/api/...` with body `not-json` → 400. GET `/api/experiments?limit=abc`
→ 200 with default limit. GET vars route with `seq=abc` → 200.

### F14 — Scope `/api/file/` away from `.exptrack/` internals · S

**Problem.** `handler.py:355-393`: traversal guard is correct (realpath +
prefix check), but the mime whitelist includes `.json/.csv/.txt/.log`, so a token-holder
can fetch `/api/file/.exptrack/config.json` — which contains `dashboard_token`.

**Fix.** After resolving the real path, additionally reject anything under
`<project_root>/.exptrack/`:
```python
if real.startswith(os.path.realpath(root / ".exptrack") + os.sep):
    self.send_error(403); return
```
**Before landing, verify nothing legitimate is served from there:** grep the JS for
`fileUrl(` / `/api/file/` usages (log viewer uses run `output_dir` under `outputs/`;
session plot images live in the project tree; cell sources come from `/api/cell-source`,
not files). If notebook-history snapshots turn out to be served via `/api/file/`, allow
only the `notebook_history` subdir instead of blanket-denying.

**Tests:** GET `/api/file/.exptrack/config.json` → 403; GET of a real log under
`outputs/` → 200; traversal attempt `/api/file/../../etc/passwd` → still rejected.

### Phase 2 bookkeeping

- `CHANGELOG.md`: `### Security` section for F10/F11/F14; `### Changed` for F12/F13.
- `CLAUDE.md`: dashboard section — one sentence each: Host-header validation exists;
  Chart.js is vendored at `/vendor/chart.umd.min.js` (new `dashboard/vendor/` entry in
  the architecture tree); `escJs` is the JS-string-context escaper and the
  `esc(escJs(x))` composition rule for inline handlers (add to the dashboard "Rules for
  changes" bullets so future JS follows it).
- Commit: `security: JS-context escaping for inline handlers, Host validation, vendored Chart.js, input validation, scope /api/file`.

---

## Phase 3 — Consistency + dead code

### F15 (M5) — Standardize CLI exit codes and error streams · M

**Problem.** Pipeline/session commands `sys.exit(1)` on not-found; inspect/mutate
commands print (sometimes to **stdout**) and return 0: `inspect_cmds.py` `cmd_show:96`,
`cmd_diff:305`, `cmd_compare:338-339`, `cmd_timeline:176`, `_compare_within:389`;
`mutate_cmds.py` `cmd_tag:42`, `cmd_untag`, `cmd_finish:508`, `cmd_study:543`, and
similar. Scripts can't detect failure (`exptrack show $ID || ...` never fires).

**Fix.**
1. Add to `cli/formatting.py`:
   ```python
   def die(msg: str, code: int = 1):
       print(col(msg, R), file=sys.stderr)
       sys.exit(code)
   ```
2. Sweep every `cmd_*` in `inspect_cmds.py` and `mutate_cmds.py`: each "Not found" /
   hard-error path → `die(...)`. Informational no-ops (e.g. "already done") stay exit 0
   but move to stderr if currently on stdout.
3. **Update existing tests**: several tests call these `cmd_*` functions directly and
   assert printed output without expecting `SystemExit` — grep tests for each command
   name and wrap not-found cases in `pytest.raises(SystemExit)`. This is the churny part;
   budget for ~10-20 test edits.

**Tests:** for each converted command add/adjust one not-found case asserting
`SystemExit` with `code == 1` and message on stderr (capsys `err`, not `out`).

### F16 — Dead-code removals (each verified) · S each

1. `handler.py:114-115`: literal `if False: pass` — delete.
2. `static_parts/scripts.py`: stale shim re-exports only 15/22 JS modules — make it
   re-export all of them (mirror `js/__init__.py`) rather than deleting the shim (it's
   documented as a compat layer).
3. `cli/session_cmds.py:24`: unused `DIM`, `RST` imports — delete.
4. `capture/variables.py:20`: `_HP_RE` lists `gamma` twice — delete one.
5. `js/core.py:1028`: `cleanDatabase()` legacy alias — grep bundle + `html.py` for
   references; if zero, delete.
6. Duplicate `api_delete_preview` in both `routes/read_routes.py:45` and
   `routes/write_routes.py:100` — check which one `handler.py` dispatches to; keep that
   one, delete the other (or have one import the other if both are wired).
7. `mutate_cmds.py:27-30,66-69`: old-style `hasattr(args,"tag")` branch in
   `cmd_tag`/`cmd_untag` unreachable from the CLI — delete AND update
   `tests/test_integration.py:110-123` which invokes that calling convention with a
   synthetic namespace; switch those tests to the real CLI shape (`id` as `nargs="+"`
   list + tag arg per the actual subparser in `main.py`).
8. **Dead CSS (conservative pass):** remove ONLY these verified-dead classes after
   re-confirming each with `grep -rn "<name>" exptrack/dashboard/` (mind dynamically
   composed names like `dl-${kind}` — if a grep hits any string-building site, keep it):
   `bulk-bar`, `bulk-count`, `study-card`, `study-card-name`, `study-card-meta`,
   `study-card-actions`, `summary-card`, `summary-grid`, `multi-compare-grid`,
   `home-btn`, `search-box`, `detail-export-bar`, `artifact-thumb`,
   `cmp-type-branch`, `cmp-type-checkpoint`, `manage-tags-link`, `pill-active`,
   `pill-ended`, `detail-grid-full`, `exp-metrics-preview`.

### F17 — Small verified correctness nits · S each

1. `core/db.py:510` — `parts[3].lstrip("b/")` strips a char-*set* (`b/backbone.py` →
   `ackbone.py`). Replace with `p[2:] if p.startswith("b/") else p`.
2. `core/experiment.py:396-404` — `log_metric` warns "after finished" but still inserts;
   make it `return` after the warning like `log_params`/`log_metrics`. **Check tests
   first** (grep for "after finished") — if a test asserts the current warn-and-write
   behavior, align the test with the consistent behavior.
3. `core/experiment.py:308-311` — `INSERT OR REPLACE INTO params` omits `source`, so
   re-logging resets `manual` → `auto`. Params PK is `(exp_id, key)` (db.py:195-199), so
   use an upsert that preserves the existing source:
   `INSERT INTO params (exp_id,key,value) VALUES (?,?,?) ON CONFLICT(exp_id,key) DO UPDATE SET value=excluded.value`.
   Add a test: add manual param via the write-route helper, re-log same key via
   `log_params`, assert `source` still `manual`.
4. `capture/cell_lineage.py:101-113` — `store_cell_lineage` check-then-insert →
   `INSERT OR IGNORE`, drop the pre-SELECT.
5. `cli/inspect_cmds.py:730-758` — `_export_batch` silently emits JSON for
   `--format params|params-md|params-txt`. Either implement those styles for batch (reuse
   the single-export formatter) or `die("--format params* not supported with --all")`.
   Pick implement-if-trivial, else explicit error; add a test either way.
6. `tests/test_main_failure.py` — spawns `python -m exptrack` without setting
   `PYTHONPATH`, so it fails on a bare checkout. Fix: pass
   `env={**os.environ, "PYTHONPATH": str(REPO_ROOT)}` and use `sys.executable`.
7. `plugins/github_sync.py` — `_api` uses `timeout=20` twice per push, synchronously, on
   the run-finish path. Reduce to `timeout=10`; optionally note in CHANGELOG. (Do NOT
   move to a background thread in this pass — out of scope.)
8. `capture/variables.py:63,245` — augmented assignments (`x += 1`) misclassified
   because the guard char-set check treats `+=` as "not an assignment". Fix both sites to
   recognize augmented assignment operators (`+= -= *= /= //= %= **= &= |= ^= >>= <<=`)
   as assignments; the extracted name is the LHS. Add a test in the variables test file:
   a cell `x += 1` is NOT observational and `x` is extracted.

### Phase 3 bookkeeping

- `CHANGELOG.md`: `### Fixed` for F17 items, `### Changed` for F15 (exit codes — this is
  a user-visible behavior change; call it out clearly), `### Removed` for F16.
- `CLAUDE.md`: update the `cli/` bullet to note the standardized exit-code contract
  (not-found → stderr + exit 1).
- Commit: `chore: standardize CLI exit codes, remove dead code, fix small correctness nits`.

---

## Explicitly OUT OF SCOPE (Phase 4 — separate efforts, do not start here)

- Extract the ~16k lines of embedded JS/CSS to real static files + ESLint.
- Split `sessions/manager.py` (~1750 lines) into manager/lifecycle/materialize.
- Fix argparse-patch statefulness (M4: `_patched` one-shot closure over first Experiment).
- Core→capture layering inversion (M11), god-function refactors, scaling cliffs
  (`_ensure_schema` per connection, `_sweep_orphans` per close, O(N²) lineage matching,
  dashboard render performance/pagination/debounce/live updates).

---

## Final acceptance checklist

1. `python -m pytest tests/ -q` — all green (baseline 532 + the new tests; expect ~560+).
2. New test files exist and fail if their fix is reverted (spot-check by `git stash` of
   one fix): `test_resume.py`, `test_run_start_resume.py`, `test_clean_orphans.py`,
   `test_plugin_proxy.py`, `test_dashboard_js_integrity.py`.
3. Manual smoke (documented in PR/commit body, use `run` skill patterns if available):
   - `eval $(exptrack run-start --lr 0.1)`; `exptrack run-finish $EXP_ID`;
     `eval $(exptrack run-start --resume $EXP_ID)` → same id, no `resume` param.
   - `exptrack clean --orphans` in a project with an outputs dir → no crash.
   - `exptrack ui`: create an experiment named `Bob's run` and a tag `it's-a-tag` →
     Delete/tag/rename buttons work, no console errors; edit a note inline, then click
     "edit" again (F7); rapidly switch detail between two experiments (F8); charts render
     offline (F12); `curl -H "Host: evil.com" http://127.0.0.1:7331/` → 403 (F11);
     `curl .../api/file/.exptrack/config.json` → 403 (F14).
4. `CHANGELOG.md` updated (Security/Fixed/Changed/Removed sections), `pyproject.toml`
   bumped to **1.36.0**, `CLAUDE.md` touched per the bookkeeping notes above.
5. All commits on `claude/codebase-audit-z1f50t`, pushed with
   `git push -u origin claude/codebase-audit-z1f50t`. Do not open a PR unless asked.
6. Delete this file (`AUDIT_IMPLEMENTATION_PLAN.md`) in the final commit if the user
   doesn't want it kept in the repo (ask, or leave it — it's the audit record).
