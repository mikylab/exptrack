# expTrack Codebase Evaluation

## Context

expTrack is a ~16,300-line stdlib-only Python experiment tracker. This evaluation identifies weaknesses, maintainability risks, and improvement opportunities across security, architecture, code quality, and scalability.

---

## 1. Security Vulnerabilities

### Critical
- **Non-finite metrics stored in DB** — `core/experiment.py:317-320`: NaN/Inf values are warned but still inserted, corrupting data and breaking JSON serialization in the dashboard. Should `return` after the warning.
- **Path traversal via symlinks in dashboard** — `dashboard/handler.py:204-215`: `_serve_file()` uses `os.path.normpath()` + `startswith()` which can be bypassed via symlinks. Should use `os.path.realpath()` on both the path and root.

### High
- **SQL f-string pattern** — `cli/admin_cmds.py:84,256,306` and `core/db.py:382`: Table/column names interpolated via f-strings. Currently safe (hardcoded values), but one refactor away from injection. Should use a whitelist check.
- **Unbounded stdin JSON read** — `cli/pipeline_cmds.py:499`: `sys.stdin.read()` with no size cap. A malicious or accidental pipe could exhaust memory.

### Medium
- **No dashboard authentication** — Anyone with network access can delete experiments, modify tags/notes. Dashboard binds to `127.0.0.1` by default, but users may change to `0.0.0.0`.
- **Weak destructive operation confirmations** — `cli/mutate_cmds.py`: Single `y` confirmation for irreversible deletes. Non-interactive stdin could bypass entirely.

---

## 2. Architecture & Design Weaknesses

### Global State Coupling
15+ module-level globals across the codebase make testing and concurrent usage difficult:
- `config.py`: `_cache`, `_root_cache` (never invalidated during process lifetime)
- `capture/argparse_patch.py`: `_patched`, `_orig_parse`, `_orig_known`
- `capture/matplotlib_patch.py`: `_plt_patched`
- `notebook.py`: `_active` (assumes single notebook)
- Dashboard JS: 15+ global variables (`currentFilter`, `charts`, `selectedIds`, etc.)

**Recommendation:** Consolidate JS globals into a single `app` state object. Add `threading.Lock()` to Python patch guards.

### Monkey-Patching Fragility
- Argparse/matplotlib patches are not thread-safe (race between `if _patched` check and set)
- If user imports argparse before exptrack patches it, params silently aren't captured
- No cleanup on exception — patches persist after script errors
- `matplotlib_patch.py:46`: Reentrance flag (`_savefig_in_progress`) uses mutable list; exception between set/clear deadlocks subsequent calls

### Missing Backup/Disaster Recovery
- Single SQLite file is the sole data store — no backup command, no restore command
- No WAL checkpoint documentation
- `cmd_compact` exists but no `exptrack backup` wrapping SQLite's backup API
- No portable full-export format

### Version Management
- Version hardcoded in both `pyproject.toml` and `exptrack/__init__.py` — no single source of truth
- No migration path documentation for major versions
- DB schema migrations exist but lack transactional safety (`core/db.py:264-329`)

---

## 3. Code Quality Issues

### Oversized Functions (violating the 40-line guideline in CLAUDE.md)
| Function | File | Lines | Recommendation |
|----------|------|-------|---------------|
| `_post_run_cell()` | `capture/notebook_hooks.py:147` | **302** | Split into 6+ functions (lineage, diffing, variable capture, timeline, snapshot) |
| `_clean_orphans()` | `cli/mutate_cmds.py:331` | **157** | Extract orphan detection per table |
| `cmd_compact()` | `cli/admin_cmds.py:175` | **118** | Delegate to per-table compaction helpers |
| `_clean_reset()` | `cli/mutate_cmds.py:208` | **82** | Split by cleanup target |
| `__init__()` | `core/experiment.py` | **72** | Extract git/GPU detection |

### Silent Exception Swallowing
27+ files use bare `except Exception: pass`. Examples:
- `core/experiment.py:36-53`: GPU detection failures silently ignored
- `core/experiment.py:124-129`: Artifact hashing failures silently ignored
- `core/db.py:68`: Integrity check failures silently ignored
- `notebook_hooks.py`: Variable capture errors crash entire cell processing (no per-variable isolation)

**Recommendation:** Catch specific exceptions; log warnings with context.

### Code Duplication
- **Experiment ID resolution** (prefix match via `WHERE id LIKE ?`) duplicated in 6+ locations across `pipeline_cmds.py`, `mutate_cmds.py`, `inspect_cmds.py`, `write_routes.py`. Should extract to `core/db.py` or a shared helper.
- **JSON tag/study parsing and updating** repeated 5+ times across CLI and dashboard routes.

### Unsafe Patterns
- `core/db.py:117,130`: `.fetchone()[0]` without null check — `fetchone()` can return `None`
- `core/db.py:352`: Git diff hash truncated to 16 hex chars (64-bit) — collision risk at scale
- `core/naming.py:35`: UUID4 truncated to 4 hex chars (65K possibilities) — likely collisions in long sessions
- `variables.py:137`: `json.dumps()` on large collections can exhaust memory before the 10KB size check
- `variables.py:124`: `.tobytes()` on large numpy arrays can cause OOM

---

## 4. Dashboard-Specific Issues

### JavaScript
- **No state management pattern** — direct DOM manipulation, no diffing/reconciliation
- **Memory leaks** — `charts` object never cleared on experiment switch; modal event listeners not cleaned up; `collapsedGroups` Set grows unbounded
- **Module interdependencies implicit** — assembly order in `get_all_js()` matters but isn't documented; `mutations.js` calls `owlSpeak()` from `owl.js` by convention
- **HTML built via string concatenation** — error-prone, potential XSS if user-controlled data isn't escaped everywhere

### CSS
- `components.py` at 24.6KB is oversized — should split into buttons, forms, modals
- Dark mode toggle exists but theme persistence mechanism unclear
- No accessibility audit (focus indicators, ARIA labels, color contrast)

---

## 5. Scalability Concerns

- **Large metric series**: Downsampling to 1500 points is configurable but not adaptive to display size
- **Filesystem scanning**: `os.walk('.')` in `__main__.py` auto-detect has no depth limit for large project trees
- **Dashboard queries**: `api_list_logs` uses `os.walk()` inside Python loops — slow for 10K+ files
- **No connection pooling**: DB connections cached per-thread but no pool size limit

---

## 6. Missing Infrastructure

| Gap | Impact | Recommendation |
|-----|--------|---------------|
| **No test suite** | Can't verify patches, refactors, or migrations | Add pytest with fixtures for DB, experiment lifecycle, CLI commands |
| **No CI/CD** | No automated quality gates | Add GitHub Actions for lint + test |
| **No backup command** | Data loss risk | Wrap `sqlite3.backup()` API |
| **No structured logging** | Inconsistent error reporting (some stderr, some silent) | Add `logging` module with configurable verbosity |
| **No rate limiting** | Dashboard API vulnerable to abuse | Add basic request throttling |
| **No input validation framework** | Ad-hoc validation scattered across modules | Centralize validation for experiment names, tags, metric values |

---

## 7. Priority Recommendations

### Immediate (security/data integrity)
1. Fix non-finite metric insertion (`core/experiment.py`) — add `return` after NaN/Inf warning
2. Fix path traversal in `_serve_file()` — use `os.path.realpath()`
3. Add size cap to stdin JSON reads in pipeline commands
4. Add thread locks to monkey-patch guards

### Short-term (quality/maintainability)
5. Extract shared `resolve_exp_id()` helper to eliminate 6x duplication
6. Split `_post_run_cell()` (302 lines) into focused functions
7. Replace bare `except Exception: pass` with specific catches + logging
8. Add per-variable error isolation in notebook variable capture
9. Consolidate dashboard JS globals into single state object

### Medium-term (infrastructure)
10. Add pytest test suite covering core experiment lifecycle, DB operations, CLI commands
11. Add `exptrack backup` / `exptrack restore` commands
12. Implement single source of truth for version (dynamic in pyproject.toml)
13. Add basic authentication option for dashboard
14. Document monkey-patching limitations and known edge cases

---

## 8. Overall Assessment

| Aspect | Score | Notes |
|--------|-------|-------|
| Module Separation | 8/10 | Clean boundaries, but global state caching needs review |
| Dependency Direction | 9/10 | No circular imports, good unidirectional flow |
| Code Organization | 7/10 | Some oversized modules and god objects |
| Error Handling | 6/10 | Bare `except Exception` too broad; many silent failures |
| Plugin System | 8/10 | Well-designed but thread-safety unclear |
| Dashboard Architecture | 6/10 | Excessive global JS state; needs state management |
| Monkey-Patching | 6/10 | Functional but fragile; needs documentation |
| Testing | 4/10 | No test suite; global state makes testing hard |
| Documentation | 7/10 | CLAUDE.md excellent; route/query docs missing |
| Backup/DR | 3/10 | No backup mechanism; single-file failure risk |
| Scalability | 7/10 | Handles typical ML workflows; large-scale concerns |
| Build Config | 8/10 | Good; version source-of-truth issue |

**Overall: 7/10** — Solid core with good separation of concerns. The stdlib-only constraint is well-executed. Main risks are security gaps (path traversal, NaN metrics), maintainability debt (oversized functions, silent exceptions, code duplication), and missing infrastructure (tests, backups, logging).
