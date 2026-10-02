
// ── Global state variables ──────────────────────────────────────────────────
// These are kept as top-level `let` declarations for backward compatibility
// with the 16+ JS modules that reference them directly.
let currentFilter = '';
let searchQuery = '';
let tagFilter = '';
let studyFilter = '';
let charts = {};
let selectedIds = new Set();
let pinnedIds = new Set(JSON.parse(localStorage.getItem('exptrack-pinned') || '[]'));
let hiddenIds = new Set(JSON.parse(localStorage.getItem('exptrack-hidden') || '[]'));
let allExperiments = [];
// Pagination: the list is loaded in pages of EXP_PAGE_SIZE (ORDER BY
// created_at DESC). `expPageLoaded` tracks how many rows we've fetched so
// "Load more" can request the next OFFSET; `expHasMore` gates the button.
//
// Filtering, search and metric-sort all run over `allExperiments` — i.e. the
// rows fetched so far, NOT the whole project. That makes "sort by metric" answer
// "best of the loaded runs", which is only the same thing as "best run" while
// everything is loaded. So: a page big enough that most projects load whole in
// one request, and `expTotal` + the truncation notice below so that when it
// isn't, the UI says so instead of quietly answering the wrong question.
const EXP_PAGE_SIZE = 1000;
let expPageLoaded = 0;
let expHasMore = false;
let expTotal = 0;
let currentDetailId = '';
// {exp_id: "where it was set"} for every run pinned as a reference, filled by
// loadStats. A Map rather than a Set because the badge has to be able to say
// *which* level pinned it — "reference" with no origin is the ambiguity the
// whole feature exists to avoid.
let _referenceIds = new Map();
let sortCol = 'created_at';
let sortDir = 'desc';
// Main-table grouping. Defaults to 'script' and is remembered across reloads.
// It used to default to 'git_commit', which is the worst possible grouping for
// the tweak-one-line-and-rerun loop: every run has its own commit, so you got
// one "— 1 run" header per run, doubling the row count for zero information.
// Grouping by script actually clusters a burst of reruns of the same file.
let groupBy = (function() {
  const saved = localStorage.getItem('exptrack-group-by');
  return saved === null ? 'script' : saved;
})();
let collapsedGroups = new Set();
let clickTimer = null;
let currentTimezone = localStorage.getItem('exptrack-tz') || '';
let allKnownTags = []; // {name, count}[]
let allKnownStudies = []; // {name, count}[]
let highlightMode = localStorage.getItem('exptrack-highlight') === 'true';
// Sidebar grouping mode: '' | 'study' | 'script' | 'day' | 'git_branch'.
// Cycled by the sidebar header button; see SIDEBAR_GROUP_MODES in sidebar.js
// for the per-mode key/label/collapse state. Migrates the old boolean
// 'exptrack-sidebar-group-study' key.
let sidebarGroupBy = localStorage.getItem('exptrack-sidebar-group-by') ||
  (localStorage.getItem('exptrack-sidebar-group-study') === 'true' ? 'study' : '');
// Groups default to collapsed: we track which ones are EXPANDED. Each mode
// keeps its own set, so collapsing "May 20" cannot silently collapse a study
// of the same name when the user cycles back. expandedStudyGroups is the one
// exception — it is shared with the main table when groupBy === 'study'.
let expandedStudyGroups = new Set(JSON.parse(localStorage.getItem('exptrack-expanded-studies') || '[]'));
let expandedScriptGroups = new Set(JSON.parse(localStorage.getItem('exptrack-expanded-scripts') || '[]'));
let expandedDayGroups = new Set(JSON.parse(localStorage.getItem('exptrack-expanded-days') || '[]'));
let expandedBranchGroups = new Set(JSON.parse(localStorage.getItem('exptrack-expanded-branches') || '[]'));
let autoRefreshTimer = null;
// Date-range filter ('' = all time, 'today', '7d', '30d') and "needs naming"
// (only runs that still carry their auto-generated name). Both apply globally
// to the sidebar and the main table via getFilteredExperiments.
let dateRange = localStorage.getItem('exptrack-date-range') || '';
let autoNamedOnly = localStorage.getItem('exptrack-auto-named-only') === 'true';
// Failed runs are listed by default: a failed run is a result, not noise —
// "it broke" is information about the change you just made, which is why
// `_BASELINE_WHERE` keeps failed runs as valid baselines (trashed and running
// are the excluded ones). Hiding them also let the table disagree with the
// FAILED stat tile directly above it, which counts them. The group bar's
// control is therefore "Hide failed", flipping to "Show failed (N)" once they
// are hidden — a filter withholding rows has to say how many.
//
// The state is persisted under a *new* key. `exptrack-show-failed` was written
// under the opposite default, so a stored 'false' there cannot be told apart
// from "toggled twice back to the default" — reading it would hand every
// existing reader the old behaviour forever, which is exactly the flip's
// purpose. The old key is dropped rather than left as a value nothing reads.
let showFailed = _storageGet('exptrack-hide-failed') !== '1';
try { localStorage.removeItem('exptrack-show-failed'); } catch (e) { /* private window */ }
// Rows the user just renamed in this session. While the "Needs naming" filter
// is on, these stay visible so the rename is visible to the user (the row's
// `name_is_auto` flag flips to false on commit, which would otherwise drop it
// out of the filtered view immediately and erase the user's confirmation).
// Cleared whenever the filter toggle is touched.
let recentlyRenamedIds = new Set();

// Internal bookkeeping params excluded from user-facing param diffs/tables.
// Shared by the Compare view, the param-column picker and the Overview "What
// changed" card so they all agree on what counts as a real param.
//
// The rule is the `_` prefix, not a list of known keys: exptrack writes every
// internal param `_`-prefixed, so an enumeration silently misses each new one.
// It did — `_code_snapshot` (a JSON blob naming the snapshot hash and the
// script's absolute path) was not on the list, so a run whose script had been
// edited showed that blob as the headline row of "What changed", burying the
// hyperparameter the user actually changed.
// `error` is the one un-prefixed internal key: Experiment.fail() writes the
// failure message there for backward compatibility (`_error_traceback` got the
// prefix when it was added later). Without this exception a failed run's error
// message surfaced as a "param change" against every other failed run.
// Mirrors LEGACY_INTERNAL_PARAM_KEYS in core/utils.py — keep the two in step.
const LEGACY_INTERNAL_PARAM_KEYS = new Set(['error']);

function isUserParamKey(k) {
  const s = String(k);
  return !s.startsWith('_') && !LEGACY_INTERNAL_PARAM_KEYS.has(s);
}

// Renders one param-diff <tr> comparing the same key across two params
// objects (JSON-stringified, '--' for missing). Shared by the Compare view
// and the Overview "What changed" card so the diff-cell styling (only tint
// the side that actually holds a differing value) can't drift between them.
function paramDiffRow(k, paramsBefore, paramsAfter) {
  const vBefore = JSON.stringify(paramsBefore[k] ?? '--');
  const vAfter = JSON.stringify(paramsAfter[k] ?? '--');
  const differs = vBefore !== vAfter;
  const clsBefore = differs && paramsBefore[k] !== undefined ? ' class="diff-removed"' : '';
  const clsAfter = differs && paramsAfter[k] !== undefined ? ' class="diff-added"' : '';
  const html = '<tr><td>' + esc(k) + '</td><td' + clsBefore + '>' + esc(vBefore) + '</td><td' + clsAfter + '>' + esc(vAfter) + '</td></tr>';
  return {differs, html};
}

// Wraps pre-built <tr> row html in a "what changed"-style table, or returns a
// fallback message when there are no rows — shared by the Overview card's
// param and metric diff tables so they can't drift into two slightly
// different table-building blocks.
function changeTableHtml(headers, rows, emptyMessage) {
  if (!rows.length) return emptyMessage ? `<p style="color:var(--muted);font-size:13px">${emptyMessage}</p>` : '';
  const head = '<tr>' + headers.map(h => '<th>' + h + '</th>').join('') + '</tr>';
  return `<table class="params-table what-changed-table">${head}${rows.join('')}</table>`;
}

// {key: last} map from an experiment's `metrics` summary array (as returned
// by GET /api/experiment/<id>) — shared so Compare and the "What changed"
// card build it the same way instead of two independent inline reductions.
function latestMetricsMap(metricsArray) {
  return Object.fromEntries(metricsArray.map(m => [m.key, m.last]));
}

function fmtMetricVal(v) {
  return v !== undefined && v !== null ? (typeof v === 'number' ? v.toFixed(4) : String(v)) : '--';
}

// ── Metric polarity ────────────────────────────────────────────────────────
// Whether a metric is better going down. Delta colouring used to key purely on
// the sign of the change, so a loss climbing 0.221 → 0.275 rendered as a green
// ▲ — the run got worse and the UI called it an improvement. That is the exact
// question the run-vs-run loop exists to answer, so the arrow must track
// *better/worse*, not *bigger/smaller*.
//
// Matched on the base name (after the last `/`) so `train/loss` and `val/mae`
// resolve the same as bare `loss`/`mae`. A user override lives in localStorage
// (`exptrack-metric-polarity`, a {key: 'lower'|'higher'} map) keyed on the full
// metric name, so an unusual metric can be corrected without a code change.
const LOWER_IS_BETTER_RE =
  /^(loss|losses|err|error|errors|err_rate|error_rate|mse|rmse|mae|mape|smape|nll|kl|kld|perplexity|ppl|wer|cer|fpr|fnr|eer|regret|cost|latency|runtime|overfit|val_loss|train_loss)$/;

function _metricPolarityOverrides() {
  try { return JSON.parse(localStorage.getItem('exptrack-metric-polarity') || '{}') || {}; }
  catch (e) { return {}; }
}

// Returns -1 when lower is better, +1 when higher is better.
function metricGoodDirection(key) {
  const k = String(key || '');
  const ov = _metricPolarityOverrides()[k];
  if (ov === 'lower') return -1;
  if (ov === 'higher') return 1;
  const si = k.lastIndexOf('/');
  let base = (si >= 0 ? k.slice(si + 1) : k).toLowerCase().replace(/[\s-]+/g, '_');
  if (LOWER_IS_BETTER_RE.test(base)) return -1;
  // Suffixed/prefixed forms: `smooth_loss`, `loss_total`, `val_rmse`, `grad_err`.
  for (const part of base.split('_')) {
    if (LOWER_IS_BETTER_RE.test(part)) return -1;
  }
  return 1;
}

// The overrides as the server states goals: `{key: "min"|"max"}`. Sent with
// any request whose answer depends on which direction is better, so the two
// ends of one table can't disagree about who won.
function metricPolarityGoals() {
  const out = {};
  const ov = _metricPolarityOverrides();
  for (const k of Object.keys(ov)) {
    if (ov[k] === 'lower') out[k] = 'min';
    else if (ov[k] === 'higher') out[k] = 'max';
  }
  return out;
}

function setMetricPolarity(key, dir) {
  const ov = _metricPolarityOverrides();
  if (dir === 'lower' || dir === 'higher') ov[key] = dir;
  else delete ov[key];
  _storageSet('exptrack-metric-polarity', JSON.stringify(ov));
}

// Colour + arrow for a change of `d` on metric `key`. The arrow keeps showing
// the numeric direction (▲ = value rose) while the colour shows whether that
// was an improvement, so no information is lost.
// `dir` lets a caller that already resolved the polarity for this key pass it
// in, so a render loop over one metric resolves it once instead of per row.
function _deltaVisual(key, d, dir) {
  const gd = dir === undefined ? metricGoodDirection(key) : dir;
  const better = d * gd > 0;
  return {
    better: better,
    arrow: d > 0 ? '&#x25B2;' : '&#x25BC;',
    color: better ? 'var(--status-success,#3fb950)' : 'var(--status-danger,#f85149)',
    title: (better ? 'better' : 'worse') + ' (lower is '
      + (gd < 0 ? 'better' : 'worse') + ' for ' + key + ')',
  };
}

// Delta cell for a numeric metric going from `before` to `after` — shared by
// Compare's metrics table and the Overview "What changed" card so the
// arrow/color/percent formatting can't drift between the two. `key` selects the
// metric's polarity; omitting it falls back to higher-is-better.
function metricDelta(before, after, key) {
  if (before === undefined || after === undefined || typeof before !== 'number' || typeof after !== 'number') {
    return { differs: before !== after, html: '' };
  }
  const d = after - before;
  if (!metricMoved(before, after)) return { differs: false, html: '' };
  const vis = _deltaVisual(key, d);
  const html = '<span style="color:' + vis.color + '" title="' + esc(vis.title) + '">'
    + vis.arrow + ' ' + fmtDeltaNum(d) + fmtDeltaPct(d, before) + '</span>';
  return { differs: true, html };
}

// Floats that differ only in the last bits are not a change: `0.9 + 0.03` and
// `0.85 + 0.04 * 2` are both 0.93 but differ by 1.1e-16, which was reported as a
// metric change rendering "▼ -0.0000 (-0.0%)" — a delta reading as zero on a row
// that only exists because something supposedly moved. Mirrors the server-side
// `_metric_moved` in core/queries.py so the strip and the card agree.
const METRIC_EPS_REL = 1e-12;
function metricMoved(before, after) {
  if (typeof before !== 'number' || typeof after !== 'number') return before !== after;
  return Math.abs(after - before)
    > METRIC_EPS_REL * Math.max(1, Math.abs(before), Math.abs(after));
}

// A real change too small for 4 decimals must not print as "0.0000" either —
// switch to exponential rather than round it away.
function fmtDeltaNum(d) {
  const sign = d > 0 ? '+' : '';
  return sign + (Math.abs(d) >= 1e-4 ? d.toFixed(4) : d.toExponential(1));
}

function fmtDeltaPct(d, before) {
  if (!before) return '';
  const pct = d / Math.abs(before) * 100;
  if (Math.abs(pct) < 0.05) return ' (' + (pct > 0 ? '+' : '-') + '<0.1%)';
  return ' (' + (pct > 0 ? '+' : '') + pct.toFixed(1) + '%)';
}

// Both sides of a change, formatted with just enough precision to actually
// differ — at a fixed 4dp a genuine 1e-6 move printed the same string twice
// ("0.5000 → 0.5000") next to a non-zero delta.
function fmtMetricPair(before, after) {
  const a = fmtMetricVal(before), b = fmtMetricVal(after);
  if (a !== b || typeof before !== 'number' || typeof after !== 'number') return [a, b];
  for (const digits of [6, 9, 12]) {
    const x = before.toFixed(digits), y = after.toFixed(digits);
    if (x !== y) return [x, y];
  }
  return [before.toExponential(6), after.toExponential(6)];
}

// Display abbreviations for common metric names (config stores full names)
const METRIC_ABBREV = {
  accuracy: 'acc', precision: 'prec', recall: 'rec', perplexity: 'ppl',
};
function abbrevMetric(key) {
  // Abbreviate the base name (after last /), keep prefix
  const si = key.lastIndexOf('/');
  const prefix = si > 0 ? key.slice(0, si + 1) : '';
  const base = si > 0 ? key.slice(si + 1) : key;
  return prefix + (METRIC_ABBREV[base] || base);
}
let highlightColors = {}; // study -> color mapping

// Column configuration: id, label, default visibility, sortable, min-width
// The metric a *set* of runs is judged by: the most common resolved key, ties
// broken by name so the answer is stable between renders. The JS mirror of
// core/param_study.consensus_metric, and it exists for the same reason — rows
// arrive newest-first, so taking the first run's key would let one legacy run
// define the axis for the whole list.
//
// It lives here, in one copy, because two views derive it (the Result column's
// sort and the filmstrip's badge) and they must label the same list with the
// same metric. The client genuinely has to derive it locally: the set is
// whatever the list is filtered to, which the server never sees.
function consensusMetricKey(exps) {
  const counts = {};
  for (const e of exps || []) {
    const k = (e.primary_metric || {}).key;
    if (k) counts[k] = (counts[k] || 0) + 1;
  }
  const keys = Object.keys(counts);
  if (!keys.length) return '';
  return keys.sort((a, b) => counts[b] - counts[a] || (a < b ? -1 : 1))[0];
}

const ALL_COLUMNS = [
  {id: 'pin', label: '', sortable: false, defaultOn: true, width: 28},
  {id: 'cb', label: '', sortable: false, defaultOn: true, width: 32},
  {id: 'id', label: 'ID', sortable: true, defaultOn: false, width: 50},
  // Name and Metrics carry the information you scan for, so they get the width;
  // Tags/Studies/Stage are frequently empty and were hoarding it (see
  // EMPTY_COL_WIDTH below, which shrinks any column with no data on screen).
  {id: 'name', label: 'Name', sortable: true, defaultOn: true, width: 250},
  {id: 'status', label: 'Status', sortable: true, defaultOn: true, width: 86},
  {id: 'tags', label: 'Tags', sortable: true, defaultOn: true, width: 84},
  {id: 'studies', label: 'Studies', sortable: true, defaultOn: true, width: 84},
  {id: 'stage', label: 'Stage', sortable: true, defaultOn: true, width: 70},
  {id: 'notes', label: 'Notes', sortable: false, defaultOn: true, width: 112},
  // The number each run is judged by, resolved server-side (run → study →
  // project → heuristic). It sits before the general Metrics cell because that
  // cell shows the first three keys a run happened to log in arbitrary order —
  // useful for a glance, useless for "which of these won".
  {id: 'primary', label: 'Result', sortable: true, defaultOn: true, width: 104},
  {id: 'metrics', label: 'Metrics', sortable: false, defaultOn: true, width: 190},
  {id: 'changes', label: 'Changes', sortable: false, defaultOn: false, width: 80},
  {id: 'started', label: 'Started', sortable: true, defaultOn: true, width: 118},
];
// ── Param columns ───────────────────────────────────────────────────────────
// Hyperparameters are the thing that actually differs between two runs of the
// same script, but the table could only ever show a fixed set of fields — so
// answering "which lr did this row use?" meant opening every run. A column id
// of the form `param:<key>` adds that param as a real, sortable column.
const PARAM_COL_PREFIX = 'param:';
function isParamCol(colId) { return String(colId).startsWith(PARAM_COL_PREFIX); }
function paramColKey(colId) { return String(colId).slice(PARAM_COL_PREFIX.length); }

// Internal bookkeeping params are never column candidates (they're
// `_`-prefixed blobs: snapshots, tracebacks, dataset manifests, var fingerprints).
function isParamColCandidate(k) {
  return isUserParamKey(k);
}

// Short header label: `--learning_rate` → `learning_rate`.
function paramColLabel(key) {
  return String(key).replace(/^-+/, '');
}

// Synthesized column definition for a param column, so every consumer
// (header, width, row cell) can treat static and param columns alike.
function getColumnDef(colId) {
  const stat = ALL_COLUMNS.find(c => c.id === colId);
  if (stat) return stat;
  if (isParamCol(colId)) {
    return {id: colId, label: paramColLabel(paramColKey(colId)),
            sortable: true, defaultOn: false, width: 76, isParam: true};
  }
  return null;
}

// Param keys present across the loaded runs, each flagged with whether its
// value actually varies — the varying ones are what you want as columns.
function paramColCandidates() {
  const seen = new Map();   // key -> Set of JSON-stringified values
  for (const e of (Array.isArray(allExperiments) ? allExperiments : [])) {
    for (const [k, v] of Object.entries(e.params || {})) {
      if (!isParamColCandidate(k)) continue;
      if (!seen.has(k)) seen.set(k, new Set());
      const vals = seen.get(k);
      if (vals.size < 8) vals.add(JSON.stringify(v));   // cap: we only need >1
    }
  }
  return [...seen.entries()]
    .map(([key, vals]) => ({key, varies: vals.size > 1}))
    // Varying params first, then alphabetical — the useful ones land on top.
    .sort((a, b) => (a.varies === b.varies)
      ? a.key.localeCompare(b.key)
      : (a.varies ? -1 : 1));
}

let visibleCols = (function() {
  const saved = JSON.parse(localStorage.getItem('exptrack-cols') || 'null');
  const validIds = new Set(ALL_COLUMNS.map(c => c.id));
  if (!saved) return ALL_COLUMNS.filter(c => c.defaultOn).map(c => c.id);
  // Remove stale column ids, merge in new defaults. Param columns are dynamic,
  // so they validate by shape rather than membership in ALL_COLUMNS.
  const cleaned = saved.filter(id => validIds.has(id) || isParamCol(id));
  const newDefaults = ALL_COLUMNS.filter(c => c.defaultOn && !cleaned.includes(c.id)).map(c => c.id);
  return newDefaults.length ? [...cleaned, ...newDefaults] : cleaned;
})();
let colWidths = JSON.parse(localStorage.getItem('exptrack-col-widths') || '{}');

// ── Consolidated app state object ───────────────────────────────────────────
// Provides a single namespace for all dashboard state. Each property is backed
// by a getter/setter that delegates to the corresponding top-level variable,
// so existing code that reads/writes the globals continues to work unchanged.
const app = {};
Object.defineProperties(app, {
  currentFilter:   { get() { return currentFilter; },   set(v) { currentFilter = v; } },
  searchQuery:     { get() { return searchQuery; },     set(v) { searchQuery = v; } },
  tagFilter:       { get() { return tagFilter; },       set(v) { tagFilter = v; } },
  studyFilter:     { get() { return studyFilter; },     set(v) { studyFilter = v; } },
  charts:          { get() { return charts; },          set(v) { charts = v; } },
  selectedIds:     { get() { return selectedIds; },     set(v) { selectedIds = v; } },
  pinnedIds:       { get() { return pinnedIds; },       set(v) { pinnedIds = v; } },
  hiddenIds:       { get() { return hiddenIds; },       set(v) { hiddenIds = v; } },
  allExperiments:  { get() { return allExperiments; },  set(v) { allExperiments = v; } },
  currentDetailId: { get() { return currentDetailId; }, set(v) { currentDetailId = v; } },
  sortCol:         { get() { return sortCol; },         set(v) { sortCol = v; } },
  sortDir:         { get() { return sortDir; },         set(v) { sortDir = v; } },
  groupBy:         { get() { return groupBy; },         set(v) { groupBy = v; } },
  collapsedGroups: { get() { return collapsedGroups; }, set(v) { collapsedGroups = v; } },
  clickTimer:      { get() { return clickTimer; },      set(v) { clickTimer = v; } },
  currentTimezone: { get() { return currentTimezone; }, set(v) { currentTimezone = v; } },
  allKnownTags:    { get() { return allKnownTags; },    set(v) { allKnownTags = v; } },
  allKnownStudies: { get() { return allKnownStudies; }, set(v) { allKnownStudies = v; } },
  highlightMode:   { get() { return highlightMode; },   set(v) { highlightMode = v; } },
  highlightColors: { get() { return highlightColors; }, set(v) { highlightColors = v; } },
  visibleCols:     { get() { return visibleCols; },     set(v) { visibleCols = v; } },
  colWidths:       { get() { return colWidths; },       set(v) { colWidths = v; } },
});

// Reset transient state to prevent memory leaks (e.g. stale chart instances,
// collapsed-group sets that grow unbounded across navigation).
function resetAppState() {
  // Destroy any existing chart instances to free canvas/bindigs
  if (charts && typeof charts === 'object') {
    for (const key of Object.keys(charts)) {
      try { if (charts[key] && typeof charts[key].destroy === 'function') charts[key].destroy(); } catch(_) {}
    }
  }
  charts = {};
  collapsedGroups = new Set();
  selectedIds = new Set();
  clickTimer = null;
  currentDetailId = '';
  highlightColors = {};
}

function saveColPrefs() {
  localStorage.setItem('exptrack-cols', JSON.stringify(visibleCols));
  localStorage.setItem('exptrack-col-widths', JSON.stringify(colWidths));
}

function getColWidth(colId) {
  const def = getColumnDef(colId);
  return colWidths[colId] || (def ? def.width : 100);
}

// ── Empty-column collapsing ─────────────────────────────────────────────────
// With no tags/studies/stages set, three columns rendered as a wall of "--"
// while holding full width — and Name and Metrics, the two that matter, got
// clipped. Any column with no data anywhere in the current set is rendered at
// this narrow width instead, handing the space back. The column stays visible
// (so the ⚙ Columns checkbox never lies) and pops back to full width the moment
// a value shows up. A width the user set by dragging always wins.
//
// The width has to leave room for the column's *name*. At 44px it didn't, so
// the header rendered the label as a bare `·` — four unlabelled dots between
// STATUS and METRICS, which read as a broken table rather than as empty
// columns, and made a strip you could sort by without knowing what you'd
// sorted. A collapsed header renders its label dimmed and lowercase (see
// `th.col-empty`), which both fits the longest of them in this width and marks
// the column as holding nothing.
const EMPTY_COL_WIDTH = 60;
// Max tag/study chips drawn in a table cell before collapsing to a `+N` chip.
const CHIP_CELL_MAX = 3;
const COLLAPSIBLE_COLS = ['tags', 'studies', 'stage', 'notes', 'changes'];

function _colHasData(colId, exps) {
  switch (colId) {
    case 'tags':    return exps.some(e => (e.tags || []).length);
    case 'studies': return exps.some(e => (e.studies || []).length);
    case 'stage':   return exps.some(e => e.stage !== null && e.stage !== undefined);
    case 'notes':   return exps.some(e => e.notes);
    case 'changes': return exps.some(e => Object.keys(e.params || {})
      .some(k => k.startsWith('_code_change/') || k === '_code_changes'));
    default: return true;
  }
}

// Ids to render narrow, given the rows currently on screen.
function emptyCollapsedCols(exps) {
  const out = new Set();
  if (!exps || !exps.length) return out;
  for (const colId of COLLAPSIBLE_COLS) {
    if (!visibleCols.includes(colId)) continue;
    if (colWidths[colId]) continue;          // user set this width explicitly
    if (!_colHasData(colId, exps)) out.add(colId);
  }
  return out;
}

// Truncate keeping BOTH ends. Auto-generated run names
// (`Jul28_ablate__lr0.01__2aac1081`) differ only in their tail, so a plain
// head-truncation renders a whole screen of identical `Jul28_abl…` rows.
// The last component of a path, whichever separator it was recorded with — a
// run started on Windows stores `C:\proj\train.py`, and splitting on '/'
// alone made the script group header the whole absolute path.
function pathBase(p) { return String(p == null ? '' : p).split(/[\\/]/).pop(); }

function midEllipsis(text, max) {
  const s = String(text == null ? '' : text);
  if (s.length <= max || max < 8) return s;
  const head = Math.ceil((max - 1) * 0.55);
  const tail = max - 1 - head;
  return s.slice(0, head) + '…' + s.slice(s.length - tail);
}

// An auto-generated name, split so the table can lead with the part that
// differs. `Sep24_train__lr0.1_width32_epochs10_seed0__6aba210a` is a date
// (the Started column), a script (the group header), the params and the id.
// Middle-ellipsizing the whole string kept the date and the id and cut the
// params, so a sweep rendered as a screen of `Sep24_train..._6aba210a` rows
// that differed only in a hex suffix.
// `_{2}` rather than two literal underscores before a group: the bundle's
// helper check (test_dashboard_js_integrity) reads that as a function call.
const _AUTO_NAME_RE = /^([A-Z][a-z]{2}\d{1,2})_(.+?)(?:_{2}(.+))?_{2}([0-9a-f]{8})$/;
function autoNameParts(name) {
  const m = _AUTO_NAME_RE.exec(String(name || ''));
  return m ? {date: m[1], script: m[2], params: m[3] || '', uid: m[4]} : null;
}

// The Name cell's text for a run: a user's own name as written; an auto name
// as its params (plus the script when the table is not grouped by script), the
// id in a dim suffix. The full name is always the cell's title.
function tableNameHtml(e, budget) {
  const parts = e.name_is_auto ? autoNameParts(e.name) : null;
  if (!parts) return esc(midEllipsis(e.name, budget));
  const lead = [];
  if (groupBy !== 'script' || !parts.params) lead.push(parts.script);
  if (parts.params) lead.push(parts.params);
  const text = lead.join(' · ');
  // The id renders in the smaller mono face: ~0.8 of a name character each.
  return esc(midEllipsis(text, Math.max(8, budget - Math.ceil(parts.uid.length * 0.8) - 1)))
    + ' <span class="name-uid">' + esc(parts.uid) + '</span>';
}

// How many characters of a run name actually fit the Name column. This has to
// be computed rather than fixed: the cell is inside a `table-layout: fixed`
// column with `text-overflow: ellipsis`, so if the JS string is longer than the
// column, CSS clips the *tail* and undoes the middle-ellipsis above. Budget out
// the cell padding, the "auto" badge and the pencil icon, then divide by an
// approximate advance width for the 14px table font.
function nameCellMaxChars(hasAutoBadge) {
  // The width the column actually rendered at, when the header is on screen:
  // a fixed-layout table stretches its columns to fill the page, so the
  // configured width undercounted a 329px column as 250 and cut names early.
  const th = document.querySelector('#exp-thead th[data-col="name"]');
  const rendered = th ? th.getBoundingClientRect().width : 0;
  const px = (rendered || getColWidth('name')) - 18 - (hasAutoBadge ? 42 : 0) - 16;
  return Math.max(10, Math.floor(px / 8.2));
}

function toggleColumnSettings() {
  const panel = document.getElementById('col-settings-panel');
  if (panel.style.display === 'block') { panel.style.display = 'none'; return; }
  let html = '<div class="col-settings-list">';
  for (const col of ALL_COLUMNS) {
    if (col.id === 'cb') continue; // checkbox always visible
    const checked = visibleCols.includes(col.id) ? 'checked' : '';
    const label = col.label || (col.id === 'pin' ? 'Pin' : col.id);
    html += '<label class="col-setting-item"><input type="checkbox" ' + checked + ' onchange="toggleColumn(\'' + col.id + '\',this.checked)"> ' + label + '</label>';
  }
  html += '</div>';

  // Param columns — the hyperparameters actually present on the loaded runs.
  const cands = paramColCandidates();
  if (cands.length) {
    const varying = cands.filter(c => c.varies);
    html += '<div class="col-settings-group-title">Params'
      + (varying.length ? ' <span class="col-settings-hint">' + varying.length + ' vary</span>' : '')
      + '</div>';
    html += '<div class="col-settings-list">';
    for (const c of cands) {
      const colId = PARAM_COL_PREFIX + c.key;
      const checked = visibleCols.includes(colId) ? 'checked' : '';
      html += '<label class="col-setting-item' + (c.varies ? ' col-setting-varies' : '') + '"'
        + ' title="' + escJsAttr(c.key) + (c.varies ? ' — varies across runs' : ' — same on every run') + '">'
        + '<input type="checkbox" ' + checked + ' onchange="toggleColumn(\'' + escJsAttr(colId) + '\',this.checked)"> '
        + esc(paramColLabel(c.key)) + (c.varies ? '<span class="col-varies-dot" title="varies across runs">●</span>' : '')
        + '</label>';
    }
    html += '</div>';
    if (varying.length) {
      html += '<div class="col-settings-actions">'
        + '<button class="col-reset-btn" onclick="addVaryingParamColumns()">Show the ' + varying.length
        + ' varying param' + (varying.length > 1 ? 's' : '') + '</button></div>';
    }
  }

  html += '<div style="border-top:1px solid var(--border);margin-top:8px;padding-top:8px"><button class="col-reset-btn" onclick="resetColumnDefaults()">Reset to defaults</button></div>';
  panel.innerHTML = html;
  panel.style.display = 'block';
  _dismissOnOutsideClick(panel, '.col-settings-btn');
}

// Close `panel` on the next click that lands neither inside it nor on the
// button that opened it. The containment test is the load-bearing part: a
// one-shot `{once: true}` listener is consumed by a click on the panel's own
// padding, which leaves the panel open with nothing left to close it — and it
// forces the anchor button to carry an `event.stopPropagation()`, putting
// dismissal logic in the markup, a file away from the panel it dismisses.
function _dismissOnOutsideClick(panel, anchorSelector, onClose) {
  function close(ev) {
    if (panel.contains(ev.target)) return;
    if (anchorSelector && ev.target.closest(anchorSelector)) return;
    document.removeEventListener('click', close);
    if (onClose) onClose(); else panel.style.display = 'none';
  }
  // Deferred so the click that opened the panel doesn't immediately close it.
  setTimeout(() => document.addEventListener('click', close), 0);
}

function resetColumnDefaults() {
  visibleCols = ALL_COLUMNS.filter(c => c.defaultOn).map(c => c.id);
  colWidths = {};
  _setAutoParamCols(true);
  syncAutoParamColumns();
  saveColPrefs();
  renderExperiments();  // re-renders the header itself
  document.getElementById('col-settings-panel').style.display = 'none';
}

// Canonical sort position for a column id. Param columns are grouped together
// just before Metrics, so the row reads name → config → results → time.
function _colOrderIndex(colId) {
  const order = ALL_COLUMNS.map(c => c.id);
  if (isParamCol(colId)) return order.indexOf('metrics') - 0.5;
  return order.indexOf(colId);
}

function _sortVisibleCols() {
  visibleCols.sort((a, b) => {
    const d = _colOrderIndex(a) - _colOrderIndex(b);
    // Ties are only possible between two param columns — keep them alphabetical.
    return d !== 0 ? d : String(a).localeCompare(String(b));
  });
}

function toggleColumn(colId, on) {
  _setAutoParamCols(false);
  if (on && !visibleCols.includes(colId)) {
    visibleCols.push(colId);
    _sortVisibleCols();
  } else if (!on) {
    visibleCols = visibleCols.filter(c => c !== colId);
  }
  saveColPrefs();
  renderExperiments();  // re-renders the header itself
}

// Until the user picks columns themselves, the params that vary are columns.
// A sweep's rows differ in exactly those values, and the one-click "Show the
// N varying params" sat behind ⚙ Columns, where nobody opening the table for
// the first time looks. Any toggle in that panel hands the choice to the user
// (`exptrack-cols-auto` = '0'); Reset to defaults hands it back.
const AUTO_PARAM_COLS_MAX = 4;
function _autoParamColsOn() { return _storageGet('exptrack-cols-auto') !== '0'; }
function _setAutoParamCols(on) { _storageSet('exptrack-cols-auto', on ? '1' : '0'); }
function syncAutoParamColumns() {
  if (!_autoParamColsOn()) return;
  const want = paramColCandidates().filter(c => c.varies).slice(0, AUTO_PARAM_COLS_MAX)
    .map(c => PARAM_COL_PREFIX + c.key);
  const next = visibleCols.filter(id => !isParamCol(id)).concat(want);
  if (next.length === visibleCols.length && next.every(id => visibleCols.includes(id))) return;
  visibleCols = next;
  _sortVisibleCols();
}

// One click to surface every param that differs across the loaded runs — the
// fast path from "140 near-identical rows" to "what did I actually change?".
function addVaryingParamColumns() {
  _setAutoParamCols(false);
  for (const c of paramColCandidates()) {
    if (!c.varies) continue;
    const colId = PARAM_COL_PREFIX + c.key;
    if (!visibleCols.includes(colId)) visibleCols.push(colId);
  }
  _sortVisibleCols();
  saveColPrefs();
  renderExperiments();  // re-renders the header itself
  const panel = document.getElementById('col-settings-panel');
  if (panel) panel.style.display = 'none';
}

// `exps` is the already-filtered row set when the caller has one (renderExperiments
// does) — recomputing it here would run the whole filter+sort pass a second time
// on every keystroke and refresh tick.
function renderTableHeader(exps) {
  const thead = document.getElementById('exp-thead');
  if (!thead) return;
  // Columns with no data in the current set render narrow (see EMPTY_COL_WIDTH).
  const rows = exps || (typeof getFilteredExperiments === 'function' ? getFilteredExperiments() : []);
  const collapsed = emptyCollapsedCols(rows);
  let html = '<tr>';
  for (const colId of visibleCols) {
    const col = getColumnDef(colId);
    if (!col) continue;
    // Never widen a column by collapsing it — a narrow column stays as it is.
    const isEmpty = collapsed.has(colId) && getColWidth(colId) > EMPTY_COL_WIDTH;
    const w = isEmpty ? EMPTY_COL_WIDTH : getColWidth(colId);
    const emptyCls = isEmpty ? ' col-empty' : '';
    const emptyTitle = isEmpty
      ? ' title="' + esc(col.label) + ' — not set on any run in view"' : '';
    const resizer = '<span class="col-resizer" onmousedown="startColResize(event,\'' + escJsAttr(colId) + '\')"></span>';
    if (colId === 'cb') {
      html += '<th class="cb-col" style="width:' + w + 'px"><input type="checkbox" onclick="selectAllVisible()" title="Select all"></th>';
    } else if (colId === 'pin') {
      html += '<th style="width:' + w + 'px;position:relative">' + resizer + '</th>';
    } else if (col.isParam) {
      html += '<th class="sortable param-col-th" style="width:' + w + 'px;position:relative"'
        + ' title="param ' + esc(paramColKey(colId)) + '"'
        + ' onclick="toggleSort(\'' + escJsAttr(colId) + '\')">' + esc(col.label)
        + '<span class="sort-arrow"></span>' + resizer + '</th>';
    } else if (col.sortable) {
      html += '<th class="sortable' + emptyCls + '" data-col="' + colId + '" style="width:' + w + 'px;position:relative"' + emptyTitle + ' onclick="toggleSort(\'' + (colId === 'started' ? 'created_at' : colId) + '\')">' + col.label + '<span class="sort-arrow"></span>' + resizer + '</th>';
    } else {
      html += '<th class="' + emptyCls.trim() + '" style="width:' + w + 'px;position:relative"' + emptyTitle + '>' + col.label + resizer + '</th>';
    }
  }
  html += '</tr>';
  thead.innerHTML = html;
  updateSortHeaders();
}

// Column resize via drag
let resizeState = null;
function startColResize(ev, colId) {
  ev.preventDefault();
  ev.stopPropagation();
  const th = ev.target.closest('th');
  const startX = ev.clientX;
  const startW = th.offsetWidth;
  resizeState = {colId, th, startX, startW};
  document.addEventListener('mousemove', doColResize);
  document.addEventListener('mouseup', endColResize);
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
}
function doColResize(ev) {
  if (!resizeState) return;
  const newW = Math.max(40, resizeState.startW + ev.clientX - resizeState.startX);
  resizeState.th.style.width = newW + 'px';
}
function endColResize(ev) {
  if (!resizeState) return;
  const newW = Math.max(40, resizeState.startW + ev.clientX - resizeState.startX);
  colWidths[resizeState.colId] = newW;
  saveColPrefs();
  resizeState = null;
  document.removeEventListener('mousemove', doColResize);
  document.removeEventListener('mouseup', endColResize);
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  renderExperiments();  // re-renders the header itself
}

// Dark mode
function toggleTheme() {
  document.body.classList.toggle('dark');
  const isDark = document.body.classList.contains('dark');
  localStorage.setItem('exptrack-theme', isDark ? 'dark' : 'light');
  document.getElementById('theme-toggle').innerHTML = isDark ? '&#9788;' : '&#9790;';
}
if (localStorage.getItem('exptrack-theme') === 'dark') {
  document.body.classList.add('dark');
  document.getElementById('theme-toggle').innerHTML = '&#9788;';
}

function togglePin(id) {
  if (pinnedIds.has(id)) pinnedIds.delete(id);
  else pinnedIds.add(id);
  localStorage.setItem('exptrack-pinned', JSON.stringify([...pinnedIds]));
  renderExperiments();
}

function hideSelected() {
  for (const id of selectedIds) hiddenIds.add(id);
  selectedIds.clear();
  localStorage.setItem('exptrack-hidden', JSON.stringify([...hiddenIds]));
  renderExperiments();
  renderExpList();
  renderHiddenPanel();
}

function unhideRow(id) {
  hiddenIds.delete(id);
  localStorage.setItem('exptrack-hidden', JSON.stringify([...hiddenIds]));
  renderExperiments();
  renderExpList();
  renderHiddenPanel();
}

function unhideAll() {
  hiddenIds.clear();
  localStorage.setItem('exptrack-hidden', '[]');
  renderExperiments();
  renderExpList();
  renderHiddenPanel();
}

let hiddenPanelOpen = false;

function toggleHiddenPanel() {
  hiddenPanelOpen = !hiddenPanelOpen;
  renderHiddenPanel();
}

function renderHiddenPanel() {
  let panel = document.getElementById('hidden-panel');
  if (!panel) {
    const tableWrap = document.querySelector('.table-scroll-wrap');
    if (!tableWrap) return;
    panel = document.createElement('div');
    panel.id = 'hidden-panel';
    panel.className = 'hidden-panel';
    tableWrap.parentNode.insertBefore(panel, tableWrap.nextSibling);
  }
  if (hiddenIds.size === 0) { panel.style.display = 'none'; return; }
  panel.style.display = 'block';
  const hiddenExps = allExperiments.filter(e => hiddenIds.has(e.id));
  let html = '<div class="hidden-panel-header" onclick="toggleHiddenPanel()">';
  html += '<span class="hidden-panel-toggle">' + (hiddenPanelOpen ? '\u25BC' : '\u25B6') + '</span> ';
  html += hiddenIds.size + ' hidden row' + (hiddenIds.size > 1 ? 's' : '');
  html += '<button class="hidden-panel-clear" onclick="event.stopPropagation();unhideAll()">Unhide all</button>';
  html += '</div>';
  if (hiddenPanelOpen) {
    html += '<div class="hidden-panel-list">';
    for (const e of hiddenExps) {
      html += '<div class="hidden-panel-item">';
      const hpName = String(e.name || e.id || '');
      html += '<span class="hidden-panel-name" title="' + esc(e.id) + '">' + esc(hpName.slice(0, 40)) + '</span>';
      html += '<span class="hidden-panel-status status-' + esc(e.status || '') + '">' + esc(e.status || '--') + '</span>';
      html += '<button class="hidden-panel-unhide" onclick="unhideRow(\'' + escJsAttr(e.id) + '\')" title="Unhide">Unhide</button>';
      html += '</div>';
    }
    html += '</div>';
  }
  panel.innerHTML = html;
}

function renderFilterBar() {
  const bar = document.getElementById('filter-bar');
  if (!bar) return;
  const allTags = new Set();
  const allStudies = new Set();
  allExperiments.forEach(e => {
    (e.tags||[]).forEach(t => allTags.add(t));
    (e.studies||[]).forEach(g => allStudies.add(g));
  });
  if (allTags.size === 0 && allStudies.size === 0) { bar.innerHTML = ''; return; }
  const hasFilter = tagFilter || studyFilter;
  let html = '';
  // Active filter chip
  if (tagFilter) {
    html += '<span class="tag-chip active" style="position:relative;padding-right:18px">';
    html += '<span onclick="tagFilter=\'\';rerender()">#' + esc(tagFilter) + '</span>';
    html += '<span class="tag-delete-x" style="opacity:1" onclick="event.stopPropagation();tagFilter=\'\';rerender()" title="Clear filter">&times;</span>';
    html += '</span>';
  } else if (studyFilter) {
    html += '<span class="tag-chip active" style="position:relative;padding-right:18px">';
    html += '<span onclick="studyFilter=\'\';rerender()">' + esc(studyFilter) + '</span>';
    html += '<span class="tag-delete-x" style="opacity:1" onclick="event.stopPropagation();studyFilter=\'\';rerender()" title="Clear filter">&times;</span>';
    html += '</span>';
  }
  // Searchable dropdown
  html += '<div class="filter-dropdown-wrap">';
  html += '<input type="text" class="filter-search-input" id="filter-search-input" placeholder="' + (hasFilter ? 'Change filter...' : 'Filter by tag/study...') + '" oninput="renderFilterDropdown()" onfocus="renderFilterDropdown()" autocomplete="off">';
  html += '<div class="filter-dropdown-list" id="filter-dropdown-list" style="display:none"></div>';
  html += '</div>';
  if (hasFilter) {
    html += '<span class="tag-chip" style="cursor:pointer" onclick="tagFilter=\'\';studyFilter=\'\';rerender()">&times; Clear</span>';
  }
  bar.innerHTML = html;
  // Close dropdown on outside click
  const input = document.getElementById('filter-search-input');
  if (input) {
    input.addEventListener('blur', () => { setTimeout(() => { const dd = document.getElementById('filter-dropdown-list'); if (dd) dd.style.display = 'none'; }, 150); });
    input.addEventListener('keydown', (ev) => {
      const dd = document.getElementById('filter-dropdown-list');
      if (!dd) return;
      const items = dd.querySelectorAll('.filter-dropdown-item');
      let activeIdx = -1;
      items.forEach((el, i) => { if (el.classList.contains('active')) activeIdx = i; });
      if (ev.key === 'ArrowDown') { ev.preventDefault(); activeIdx = Math.min(activeIdx + 1, items.length - 1); items.forEach((el, i) => el.classList.toggle('active', i === activeIdx)); }
      else if (ev.key === 'ArrowUp') { ev.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); items.forEach((el, i) => el.classList.toggle('active', i === activeIdx)); }
      else if (ev.key === 'Enter') { ev.preventDefault(); if (activeIdx >= 0 && items[activeIdx]) items[activeIdx].click(); }
      else if (ev.key === 'Escape') { dd.style.display = 'none'; input.blur(); }
    });
  }
}

function renderFilterDropdown() {
  const dd = document.getElementById('filter-dropdown-list');
  const input = document.getElementById('filter-search-input');
  if (!dd || !input) return;
  const q = input.value.trim().toLowerCase();
  const allTags = new Set();
  const allStudies = new Set();
  allExperiments.forEach(e => {
    (e.tags||[]).forEach(t => allTags.add(t));
    (e.studies||[]).forEach(g => allStudies.add(g));
  });
  let items = [];
  for (const t of [...allTags].sort()) {
    const count = allExperiments.filter(e => (e.tags||[]).includes(t)).length;
    if (!q || t.toLowerCase().includes(q)) items.push({type: 'tag', name: t, count});
  }
  for (const g of [...allStudies].sort()) {
    const count = allExperiments.filter(e => (e.studies||[]).includes(g)).length;
    if (!q || g.toLowerCase().includes(q)) items.push({type: 'study', name: g, count});
  }
  if (items.length === 0) { dd.innerHTML = '<div style="padding:6px 10px;color:var(--muted);font-size:12px">No matches</div>'; dd.style.display = 'block'; return; }
  dd.innerHTML = items.map(item =>
    '<div class="filter-dropdown-item" data-type="' + item.type + '" data-name="' + esc(item.name) + '" onmousedown="event.preventDefault();applyFilterFromDropdown(\'' + item.type + '\',\'' + escJsAttr(item.name) + '\')">' +
    '<span>' + (item.type === 'tag' ? '<span style="color:var(--muted)">#</span>' : '<span style="color:var(--blue)">\u25CF </span>') + esc(item.name) + '</span>' +
    '<span style="color:var(--muted);font-size:11px">' + item.count + '</span>' +
    '</div>'
  ).join('');
  dd.style.display = 'block';
}

function applyFilterFromDropdown(type, name) {
  if (type === 'tag') { tagFilter = name; studyFilter = ''; }
  else { studyFilter = name; tagFilter = ''; }
  rerender();
}

// `updateFailedCount` belongs here, not only on the load path: the number of
// failed runs being withheld depends on every other filter in effect, so a
// search or a date-range change that narrows the set has to move it too.
function rerender() {
  renderExperiments(); renderExpList(); renderFilterBar(); updateFailedCount();
}

// ── Auth ────────────────────────────────────────────────────────────────────
// Tokens live in localStorage (not the URL) so they don't leak via browser
// history or referer. Image URLs still carry the token as a query param
// because <img> can't set request headers.
const _TOKEN_KEY = 'exptrack_token';

function _storageGet(k) { try { return localStorage.getItem(k) || ''; } catch (e) { return ''; } }
function _storageSet(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
function _storageDel(k) { try { localStorage.removeItem(k); } catch (e) {} }

// One CSV cell, quoted only when it has to be. Spelled out separately in every
// surface that exports a table, so a fix to the quoting rule reached one of
// them.
function csvCell(v) {
  const s = v === undefined || v === null ? '' : String(v);
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function downloadBlob(text, filename, mime) {
  const blob = new Blob([text], {type: mime || 'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a); a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
}

// Save to <project_root>/exports/ if the user has opted in (Settings → Display);
// otherwise fall back to a browser download. Server picks a non-conflicting
// filename, so existing files are never overwritten.
async function saveOrDownload(text, filename, mime) {
  if (_storageGet('exptrack-export-to-folder') !== 'true') {
    downloadBlob(text, filename, mime);
    return;
  }
  try {
    const res = await postApi('/api/save-export', { filename, content: text });
    if (res && res.ok) { owlSay('Saved to ' + res.path); return; }
    owlSay('Save failed: ' + ((res && res.error) || 'unknown') + ' — downloading');
  } catch (e) { /* fall through to download */ }
  downloadBlob(text, filename, mime);
}

// Copy a document in two flavours at once: `html` for the paste targets that
// render it (OneNote, Word, Outlook, Google Docs — none of them render
// markdown, so a markdown copy landed there as pipes and dashes) and `text`
// for everything that reads plain text (a markdown editor, GitHub, a
// terminal). The paste target picks the one it understands.
//
// Over plain http to a non-loopback host the async clipboard API is absent,
// which used to fail every Copy on a tunnelled dashboard. The fallback is the
// older selection copy: a rendered, off-screen copy of the HTML is selected
// and copied, which still carries both flavours.
async function copyRich(text, html, what) {
  const label = what || 'it';
  if (html && navigator.clipboard && window.ClipboardItem && window.isSecureContext) {
    try {
      await navigator.clipboard.write([new window.ClipboardItem({
        'text/html': new Blob([html], {type: 'text/html'}),
        'text/plain': new Blob([text], {type: 'text/plain'}),
      })]);
      owlSay('Copied ' + label + ' — pastes as tables in OneNote/Word, as markdown elsewhere.');
      return true;
    } catch (e) { /* fall through to the selection copy */ }
  } else if (!html && navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      owlSay('Copied ' + label + '!');
      return true;
    } catch (e) { /* fall through */ }
  }
  if (_selectionCopy(text, html)) {
    owlSay('Copied ' + label + '!');
    return true;
  }
  owlSay('The browser refused the clipboard — use Export to save a file instead.');
  return false;
}

function _selectionCopy(text, html) {
  const host = document.createElement(html ? 'div' : 'textarea');
  host.style.cssText = 'position:fixed;left:-9999px;top:0;opacity:0';
  if (html) {
    host.contentEditable = 'true';
    host.innerHTML = html;
  } else {
    host.value = text;
  }
  document.body.appendChild(host);
  let ok = false;
  try {
    if (html) {
      const range = document.createRange();
      range.selectNodeContents(host);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } else {
      host.select();
    }
    ok = document.execCommand('copy');
  } catch (e) {
    ok = false;
  }
  window.getSelection().removeAllRanges();
  host.remove();
  return ok;
}

function setExportToFolder(checked) {
  _storageSet('exptrack-export-to-folder', checked ? 'true' : 'false');
}

// Word-level diff spotlighting (default on). Persisted so the renderer
// (_wordDiffEnabled in highlight.py) picks it up; re-render the open detail
// view so the change is immediate rather than waiting for the next refresh.
function setWordDiff(checked) {
  _storageSet('exptrack-word-diff', checked ? 'true' : 'false');
  if (typeof currentDetailId !== 'undefined' && currentDetailId) refreshDetail(currentDetailId);
}

// Sync settings checkboxes to persisted state on first paint.
{
  const el = document.getElementById('settings-export-to-folder');
  if (el) el.checked = _storageGet('exptrack-export-to-folder') === 'true';
  const wd = document.getElementById('settings-word-diff');
  if (wd) wd.checked = _storageGet('exptrack-word-diff') !== 'false';
}

// Rewrite one query param in this tab's address without reloading. An empty
// value removes it. The two callers below want opposite things from the same
// mechanism — the token is consumed and stripped, the project is kept because
// it IS the tab's binding — so the shared piece is the rewrite, not the
// policy. A URL the browser will not let us rewrite is never a reason to fail
// the caller: the token and the project both also travel on the request.
function _setUrlParam(key, value) {
  try {
    const url = new URL(window.location);
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
    window.history.replaceState({}, '', url.toString());
  } catch (e) { /* opaque or unwritable URL — nothing to do */ }
}

let _authToken = (function() {
  const urlToken = new URLSearchParams(window.location.search).get('token');
  if (urlToken) {
    _storageSet(_TOKEN_KEY, urlToken);
    _setUrlParam('token', '');
    return urlToken;
  }
  return _storageGet(_TOKEN_KEY);
})();

const _PROJECT_KEY = 'exptrack_project';

// The project is per TAB, not per browser. It used to live only in
// localStorage, which is shared by every tab of the origin: opening a second
// worktree in a second window moved the first one under the reader on its
// next reload, so three checkouts still meant three dashboards. The URL is
// the only per-tab store a reload survives, so `?project=` wins when present
// and localStorage is demoted to the default for a tab opened without one.
//
// Unlike `?token=`, this param is deliberately NOT stripped from the address
// bar: stripping it is what would lose the binding on reload.
const _urlProjectId = new URLSearchParams(window.location.search).get('project') || '';
let _activeProjectId = _urlProjectId || _storageGet(_PROJECT_KEY) || '';
if (_urlProjectId) _storageSet(_PROJECT_KEY, _urlProjectId);

// Put `id` in this tab's address without reloading. Every caller reloads
// straight afterwards (every view is project-scoped), but the two are
// separate so the recovery path can correct a dead id in the URL without
// looping through another reload.
function _setUrlProject(id) {
  _setUrlParam('project', id);
}

function _authHeaders() {
  const h = _authToken ? {'Authorization': 'Bearer ' + _authToken} : {};
  // The active project rides with the credentials rather than in a cookie:
  // auth here is Bearer-only, which is what makes the dashboard immune to
  // cross-site request forgery, and a cookie would give that away.
  if (_activeProjectId) h['X-Exptrack-Project'] = _activeProjectId;
  return h;
}

// Headers for a request about a run in a *specific* project, which may not be
// the one the page is on. Compare is the only surface that can hold such a
// run, and the project rides on the request rather than on the page: switching
// the page's project to fetch one panel would move every other view under the
// reader. Falsy `projectId` means "wherever the page is", which is every
// caller that existed before Compare could span projects.
function _projectHeaders(projectId) {
  const h = _authHeaders();
  if (projectId) h['X-Exptrack-Project'] = projectId;
  return h;
}

function fileUrl(path, projectId) {
  const base = '/api/file/' + encodeURIComponent(path).replace(/%2F/g, '/');
  const q = [];
  if (_authToken) q.push('token=' + encodeURIComponent(_authToken));
  // An <img src> can carry no headers at all — which is exactly why the token
  // already rides in the query here. The project travels the same way, for the
  // same reason: an image belonging to a run in another project has no other
  // way to say so.
  if (projectId) q.push('project=' + encodeURIComponent(projectId));
  return q.length ? base + '?' + q.join('&') : base;
}

function mergeArtifactImages(images, artifactImages) {
  if (!artifactImages || !artifactImages.length) return images;
  const existing = new Set(images.map(i => i.path));
  for (const ai of artifactImages) {
    if (!existing.has(ai.path)) { images.push(ai); existing.add(ai.path); }
  }
  return images;
}

// ── Request error banner ────────────────────────────────────────────────────
// A failed GET used to reject out of api() with nothing catching it, so the
// render that depended on it never ran: the table stayed empty while the stats
// cards above it still showed "N total runs" — no error, no retry, no clue.
// Surface it instead.
function _showApiError(path, detail) {
  let bar = document.getElementById('api-error-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'api-error-bar';
    bar.className = 'api-error-bar';
    document.body.appendChild(bar);
  }
  bar.innerHTML =
    '<span class="api-error-msg"><strong>Couldn\'t load data from the exptrack server.</strong> ' +
    esc(String(detail || 'request failed')) + ' <code>' + esc(path) + '</code></span>' +
    '<button class="api-error-retry" onclick="_retryApiError()">Retry</button>' +
    '<button class="api-error-close" onclick="_dismissApiError()" title="Dismiss">&times;</button>';
  bar.style.display = 'flex';
}

function _dismissApiError() {
  const bar = document.getElementById('api-error-bar');
  if (bar) bar.style.display = 'none';
}

// Retry re-issues the data the mounted views need, rather than reloading the
// page: a full reload throws away scroll position, the open tab, an in-progress
// rename and the Commands notepad's unsaved text — for a request that usually
// just needs asking again. The bar re-appears by itself if the retry fails too.
function _retryApiError() {
  const btn = document.querySelector('#api-error-bar .api-error-retry');
  if (btn) { btn.disabled = true; btn.textContent = 'Retrying…'; }
  _dismissApiError();
  const done = () => {
    if (btn) { btn.disabled = false; btn.textContent = 'Retry'; }
  };
  Promise.resolve()
    .then(() => (typeof loadStats === 'function' ? loadStats() : null))
    .then(() => (typeof loadExperiments === 'function' ? loadExperiments() : null))
    .then(() => {
      if (typeof currentDetailId !== 'undefined' && currentDetailId &&
          typeof refreshDetail === 'function') return refreshDetail(currentDetailId);
      return null;
    })
    .catch(() => {})
    .then(done, done);
}

// Parse a response body as JSON, reporting rather than throwing on a truncated
// or non-JSON body (a 500 mid-response resets the connection and yields both).
async function _readJson(r, path) {
  const text = await r.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    _showApiError(path, 'server returned ' + r.status + ' with an unreadable body');
    return null;
  }
}

// Shared fetch → 401 → JSON-parse path for api()/postApi(). Returns exactly one
// of: `{auth: false}` (login needed), `{failed: msg}` (network-level failure or
// an unreadable body — already reported to the user), or `{r, data}`. The two
// wrappers differ only in the request options and the shape they give up with.
async function _request(path, opts) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    // Network-level failure: server died, or the handler crashed mid-response.
    _showApiError(path, e && e.message ? e.message : 'connection failed');
    return {failed: 'request failed'};
  }
  if (r.status === 401) { _showLoginOverlay(); return {auth: false}; }
  const data = await _readJson(r, path);
  if (data === null) return {failed: 'unreadable server response'};
  return {r: r, data: data};
}

// `projectId` is optional and trailing, so every existing one-argument call is
// unchanged. It names the project this one request is about — used by Compare,
// the only surface that can be showing a run from somewhere else. The return
// contract is identical, `null` on failure included, so every existing guard
// applies to a cross-project fetch too.
async function api(path, projectId) {
  const res = await _request(path, {headers: _projectHeaders(projectId)});
  if (res.auth === false) return {};
  if (res.failed) return null;
  if (!res.r.ok) {
    _showApiError(path, (res.data && res.data.error) || ('HTTP ' + res.r.status));
    return null;
  }
  _dismissApiError();
  return res.data;
}

async function postApi(path, body = {}, projectId) {
  const res = await _request(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', ..._projectHeaders(projectId)},
    body: JSON.stringify(body)
  });
  if (res.auth === false) return {};
  if (res.failed) return {error: res.failed};
  if (!res.r.ok && !res.data.error) res.data.error = 'HTTP ' + res.r.status;
  return res.data;
}

// Trailing-edge debounce: returns a wrapper that delays `fn` until `wait`ms
// after the last call. Used for the search box and to coalesce the burst of
// loadExperiments() calls that a single mutation can trigger.
function debounce(fn, wait) {
  let t = null;
  return function(...args) {
    if (t) clearTimeout(t);
    t = setTimeout(() => { t = null; fn.apply(this, args); }, wait);
  };
}

// ── Reproduce-command form toggle ────────────────────────────────────────────
// `exptrack run <script>` captures the command as a plain, runnable
// `python <abs-path> <args>`. These helpers let the Reproduce box flip between
// that plain form and the tracked `exptrack run <abs-path> <args>` form — the
// two differ only by the interpreter prefix, so conversion is lossless.
const _REPRO_TRACKED_KEY = 'exptrack-reproduce-tracked';
function _reproIsTracked(cmd) {
  const t = (cmd || '').trim();
  return t.startsWith('exptrack run ') || t.startsWith('python -m exptrack ');
}
function _reproFormAlt(cmd) {
  const t = (cmd || '').trim();
  if (t.startsWith('exptrack run ')) return 'python ' + t.slice('exptrack run '.length);
  if (t.startsWith('python -m exptrack ')) return 'python ' + t.slice('python -m exptrack '.length);
  if (t.startsWith('python ')) return 'exptrack run ' + t.slice('python '.length);
  return null;   // no recognizable interpreter prefix → not toggleable
}
function _preferredReproForm(cmd) {
  const wantTracked = localStorage.getItem(_REPRO_TRACKED_KEY) === '1';
  if (wantTracked === _reproIsTracked(cmd)) return cmd;   // already in the wanted form
  return _reproFormAlt(cmd) || cmd;                       // flip, or leave as-is if not toggleable
}
function toggleReproduceForm() {
  const cur = localStorage.getItem(_REPRO_TRACKED_KEY) === '1';
  localStorage.setItem(_REPRO_TRACKED_KEY, cur ? '0' : '1');
  if (typeof currentDetailId !== 'undefined' && currentDetailId) refreshDetail(currentDetailId);
}

// Search handlers: update the filter string synchronously (so the next render
// sees the latest query) but debounce the expensive re-render so typing fast
// doesn't re-filter+re-sort+rebuild the whole table/sidebar on every keystroke.
const _debouncedSidebarRender = debounce(() => renderExpList(), 150);
function onSidebarSearch(v) { searchQuery = v; _debouncedSidebarRender(); }
const _debouncedMainRender = debounce(() => { renderExperiments(); renderExpList(); }, 150);
function onMainSearch(v) { searchQuery = v; _debouncedMainRender(); }

// What the last /api/ping said about this tab's project: 'ok', 'unknown',
// 'unavailable', or '' when no project was named. Boot reads it to decide
// whether the stored id has to be recovered *before* anything loads.
let _pingProjectState = '';

async function _ping(headers) {
  if (_activeProjectId) headers['X-Exptrack-Project'] = _activeProjectId;
  try {
    const r = await fetch('/api/ping', {headers: headers});
    if (!r.ok) return false;
    try { _pingProjectState = (await r.json()).project || ''; } catch (e) { /* older server */ }
    return true;
  } catch (e) { return false; }
}

async function _validateToken(tok) {
  return _ping({'Authorization': 'Bearer ' + tok});
}

// True when the server accepts an unauthenticated request — i.e. it was started
// with `exptrack ui --no-auth`. Without this check an empty token fell straight
// through to the login overlay, which asked for a token that does not exist and
// could never be satisfied, making --no-auth unusable.
async function _authDisabledOnServer() {
  return _ping({});
}

// Resolves true once we have a token the server accepts. Called from init
// to gate the initial data load; also resolved by the login overlay after
// a successful submit.
let _authResolve;
const _authReady = new Promise(r => { _authResolve = r; });

async function ensureAuth() {
  if (_authToken && await _validateToken(_authToken)) {
    _authResolve(true);
    return true;
  }
  _storageDel(_TOKEN_KEY);
  _authToken = '';
  // Auth off on the server (`--no-auth`) → nothing to log in with, proceed.
  if (await _authDisabledOnServer()) {
    _authResolve(true);
    return true;
  }
  _showLoginOverlay();
  return _authReady;
}

// The standing "not logged in" state. Deliberately a strip rather than a
// dialog: it does not block the page, it does not come back on its own, and it
// is the one control that reopens the prompt.
function _showAuthBanner() {
  if (document.getElementById('exptrack-auth-banner')) return;
  const el = document.createElement('div');
  el.id = 'exptrack-auth-banner';
  el.className = 'auth-banner';
  el.innerHTML = '<span>Not logged in \u2014 requests will keep failing. '
    + 'Run <code>exptrack ui status</code> to print the URL with the token, or '
    + 'paste the token here.</span>'
    + '<button class="btn-sm" onclick="openLoginPrompt()">Enter token</button>';
  document.body.appendChild(el);
}

function _hideAuthBanner() {
  const el = document.getElementById('exptrack-auth-banner');
  if (el) el.remove();
}

function openLoginPrompt() { _showLoginOverlay(true); }

// The token prompt. Shown at boot when there is no usable token, and again
// whenever any request comes back 401. The token is persisted to
// .exptrack/dashboard_token, so a restart no longer invalidates the one this
// browser stored — that was the 1.9.0 fix. A 401 now means something else: a
// token cleared or replaced (`exptrack ui --clear-token`, `--token`), a
// different dashboard, or browser storage that was dropped.
//
// It used to have no way out: no Cancel, no Escape, no click-outside, over the
// whole viewport at z-index 10000. So a stale token did not degrade the page,
// it *locked* it — every control unreachable behind a dialog whose only exit
// was a token the user had to go and find, with the error line ("Invalid token")
// giving no hint that the reason was a restart. It is now dismissible, and says
// what actually happened.
// Once dismissed, a 401 raises the *banner* rather than the modal. Making the
// modal dismissible fixed the lock-out and created a subtler failure in its
// place: a session with a stale token renders (from cache, or empty), reads as
// working, and then ambushes you with the full-screen prompt again at the first
// thing you click — "the home page is fine but Compare demands a token". One
// dismissal is one decision; after it the state is stated where you can see it
// and act on it when you choose.
let _authDismissed = false;

function _showLoginOverlay(force) {
  if (_authDismissed && !force) { _showAuthBanner(); return; }
  if (document.getElementById('exptrack-login-overlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'exptrack-login-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;z-index:10000;'
    + 'background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center';
  overlay.innerHTML = ''
    + '<div style="background:var(--bg,#fff);color:var(--fg,#222);'
    + 'border-radius:8px;padding:28px 32px;min-width:360px;max-width:440px;'
    + 'box-shadow:0 12px 40px rgba(0,0,0,.4);font-family:system-ui,sans-serif">'
    +   '<div style="font-size:18px;font-weight:600;margin-bottom:6px">exptrack dashboard</div>'
    +   '<div style="color:var(--muted,#666);font-size:13px;margin-bottom:16px;line-height:1.5">'
    +     'This dashboard needs the token printed when it started — '
    +     'it is in that URL after <code>?token=</code>. '
    +     '<strong>Run <code>exptrack ui status</code></strong> to print it again; '
    +     'opening that URL logs you straight back in. The token survives a '
    +     'restart, so if it stopped working it was cleared or replaced.'
    +   '</div>'
    +   '<input id="exptrack-token-input" type="password" autocomplete="off" '
    +          'placeholder="token" '
    +          'style="width:100%;padding:10px 12px;border:1px solid var(--border,#ccc);'
    +                 'border-radius:4px;font-size:14px;box-sizing:border-box;'
    +                 'background:var(--bg,#fff);color:var(--fg,#222)">'
    +   '<button id="exptrack-login-btn" '
    +           'style="margin-top:12px;width:100%;padding:10px;border:0;border-radius:4px;'
    +                  'background:#2563eb;color:#fff;font-size:14px;font-weight:600;cursor:pointer">'
    +     'Log in'
    +   '</button>'
    +   '<button id="exptrack-login-dismiss" '
    +           'style="margin-top:8px;width:100%;padding:8px;border:0;border-radius:4px;'
    +                  'background:none;color:var(--muted,#666);font-size:13px;cursor:pointer">'
    +     'Dismiss (Esc)'
    +   '</button>'
    +   '<div id="exptrack-login-error" style="color:#dc3545;font-size:13px;'
    +        'margin-top:10px;min-height:18px"></div>'
    + '</div>';
  document.body.appendChild(overlay);

  const input = document.getElementById('exptrack-token-input');
  const btn = document.getElementById('exptrack-login-btn');
  const err = document.getElementById('exptrack-login-error');
  input.focus();

  function dismiss() {
    overlay.remove();
    document.removeEventListener('keydown', onKey);
    // Dismissed without a token, the page behind is stale or empty and every
    // request will keep failing — leave a standing banner rather than a
    // silently dead dashboard, and don't raise this dialog again unasked.
    if (!_authToken) {
      _authDismissed = true;
      _showAuthBanner();
    }
  }
  function onKey(ev) { if (ev.key === 'Escape') dismiss(); }
  document.addEventListener('keydown', onKey);
  overlay.addEventListener('click', ev => { if (ev.target === overlay) dismiss(); });
  document.getElementById('exptrack-login-dismiss').onclick = dismiss;

  async function submit() {
    const tok = input.value.trim();
    if (!tok) { err.textContent = 'Enter a token.'; return; }
    btn.disabled = true;
    try {
      if (await _validateToken(tok)) {
        _authToken = tok;
        _storageSet(_TOKEN_KEY, tok);
        _authDismissed = false;
        _hideAuthBanner();
        overlay.remove();
        document.removeEventListener('keydown', onKey);
        _authResolve(true);
        // The request that 401'd returned empty and nothing retries it, so the
        // view behind the dialog is whatever half-rendered before the token
        // went stale. Reload it rather than leave a blank page logged in.
        if (typeof loadExperiments === 'function') loadExperiments();
      } else {
        err.textContent = 'Invalid token. Check the URL printed by the running exptrack ui.';
        _storageDel(_TOKEN_KEY);
      }
    } finally {
      btn.disabled = false;
    }
  }
  btn.onclick = submit;
  input.onkeydown = (e) => { if (e.key === 'Enter') submit(); };
}

function logout() {
  _storageDel(_TOKEN_KEY);
  _authToken = '';
  location.reload();
}

async function deleteTagGlobal(tag) {
  const count = allExperiments.filter(e => (e.tags||[]).includes(tag)).length;
  if (!confirm('Remove #' + tag + ' from ' + count + ' experiment(s)? This cannot be undone.')) return;
  const res = await postApi('/api/delete-tag-global', {tag});
  if (res.ok) {
    if (tagFilter === tag) tagFilter = '';
    await loadAllTags();
    await loadExperiments();
    loadTodos(); loadCommands();
    renderManagePanel();
  }
}

function toggleManageDrawer() {
  const drawer = document.getElementById('manage-drawer');
  const overlay = document.getElementById('manage-overlay');
  if (!drawer) return;
  const isOpen = drawer.classList.contains('visible');
  if (isOpen) {
    closeManageDrawer();
  } else {
    drawer.classList.add('visible');
    overlay.classList.add('visible');
    renderManagePanel();
  }
}

function closeManageDrawer() {
  const drawer = document.getElementById('manage-drawer');
  const overlay = document.getElementById('manage-overlay');
  if (drawer) drawer.classList.remove('visible');
  if (overlay) overlay.classList.remove('visible');
}

function renderManagePanel() {
  const panel = document.getElementById('manage-drawer-body');
  if (!panel) return;
  let html = '';

  // Tags section
  html += '<div class="manage-section"><h4>Tags</h4>';
  if (!allKnownTags.length) {
    html += '<div style="color:var(--muted);font-size:12px;padding:4px 0">No tags yet.</div>';
  } else {
    for (const t of allKnownTags) {
      html += '<div class="tag-manager-row">'
        + '<span class="tm-name-edit" ondblclick="startEditGlobalTag(this,\'' + escJsAttr(t.name) + '\')">#' + esc(t.name) + ' <span class="tm-count">(' + t.count + ')</span></span>'
        + '<span class="tm-delete" onclick="deleteTagGlobal(\'' + escJsAttr(t.name) + '\')" title="Remove from all experiments">&times;</span>'
        + '</div>';
    }
  }
  html += '</div>';

  // Studies section
  html += '<div class="manage-section"><h4>Studies</h4>';
  if (!allKnownStudies.length) {
    html += '<div style="color:var(--muted);font-size:12px;padding:4px 0">No studies yet.</div>';
  } else {
    for (const g of allKnownStudies) {
      html += '<div class="tag-manager-row">'
        + '<span class="tm-name-edit" ondblclick="startEditGlobalStudy(this,\'' + escJsAttr(g.name) + '\')">' + esc(g.name) + ' <span class="tm-count">(' + g.count + ')</span></span>'
        + '<span class="tm-delete" onclick="deleteStudyGlobal(\'' + escJsAttr(g.name) + '\')" title="Remove from all experiments">&times;</span>'
        + '</div>';
    }
  }
  if (selectedIds.size > 0) {
    html += '<div class="study-create-form" style="margin-top:8px">';
    html += '<input type="text" id="new-study-name" placeholder="New study for ' + selectedIds.size + ' selected...">';
    html += '<button onclick="createStudyFromPanel()">Create</button>';
    html += '</div>';
  }
  html += '</div>';
  panel.innerHTML = html;
}

async function startEditGlobalTag(el, oldName) {
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'name-edit-input';
  input.value = oldName; input.style.cssText = 'width:120px;font-size:12px;padding:2px 4px';
  el.innerHTML = ''; el.appendChild(input); input.focus(); input.select();
  let saved = false;
  async function doSave() {
    if (saved) return; saved = true;
    const newName = input.value.trim();
    if (newName && newName !== oldName) {
      // Rename tag across all experiments and config (todos/commands)
      for (const e of allExperiments) {
        if ((e.tags||[]).includes(oldName)) {
          await postApi('/api/experiment/' + e.id + '/edit-tag', {old_tag: oldName, new_tag: newName});
        }
      }
      await postApi('/api/propagate-tag-rename', {old_tag: oldName, new_tag: newName});
      await loadAllTags(); await loadExperiments();
      loadTodos(); loadCommands();
    }
    renderManagePanel();
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; renderManagePanel(); }
  });
}

async function startEditGlobalStudy(el, oldName) {
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'name-edit-input';
  input.value = oldName; input.style.cssText = 'width:120px;font-size:12px;padding:2px 4px';
  el.innerHTML = ''; el.appendChild(input); input.focus(); input.select();
  let saved = false;
  async function doSave() {
    if (saved) return; saved = true;
    const newName = input.value.trim();
    if (newName && newName !== oldName) {
      // Rename study across all experiments and config (todos/commands)
      for (const e of allExperiments) {
        if ((e.studies||[]).includes(oldName)) {
          await postApi('/api/experiment/' + e.id + '/study', {study: newName});
          await postApi('/api/experiment/' + e.id + '/delete-study', {study: oldName});
        }
      }
      await postApi('/api/propagate-study-rename', {old_study: oldName, new_study: newName});
      if (studyFilter === oldName) studyFilter = newName;
      await loadAllStudies(); await loadExperiments();
      loadTodos(); loadCommands();
    }
    renderManagePanel();
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; renderManagePanel(); }
  });
}

function fmtDur(s) {
  if (!s) return '--';
  if (s >= 3600) return Math.floor(s/3600) + 'h' + Math.floor((s%3600)/60) + 'm';
  if (s >= 60) return Math.floor(s/60) + 'm' + Math.floor(s%60) + 's';
  return s.toFixed(1) + 's';
}

// ── Date helpers (grouping + range filtering) ────────────────────────────────
// created_at is stored as UTC ISO; bare timestamps are treated as UTC.
function expDate(iso) {
  if (!iso) return null;
  // Not every timestamp in the dashboard is an ISO string. `sessions` and
  // `session_nodes` store unix floats, and these helpers are shared across
  // both domains — `fmtTimeAgo(s.created_at * 1000)` on the sessions list
  // handed a *number* to what assumed a string, and reading `.endsWith` off it
  // threw a TypeError out of the render loop, taking the whole session list
  // down with it. A number is epoch milliseconds, which is what `new Date(n)`
  // already means; there is nothing to append a zone suffix to.
  if (typeof iso === 'number') return isNaN(iso) ? null : new Date(iso);
  if (typeof iso !== 'string') return null;
  return new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
}

// The day formatter, memoized on the timezone it was built for. dayKeyOf runs
// once per experiment per render — up to EXP_PAGE_SIZE rows, on every debounced
// keystroke and every mutation, in the table, the rail and the date filter — so
// building an Intl.DateTimeFormat per call was pure churn. setTimezone
// reassigns currentTimezone, which is the whole cache key.
let _dayFmt = null, _dayFmtTz = null;

function _dayFormatter() {
  if (_dayFmt && _dayFmtTz === currentTimezone) return _dayFmt;
  _dayFmtTz = currentTimezone;
  _dayFmt = new Intl.DateTimeFormat('en-CA', {
    timeZone: currentTimezone, year: 'numeric', month: '2-digit', day: '2-digit'
  });
  return _dayFmt;
}

// Calendar-day key (YYYY-MM-DD) in the active timezone — stable group/filter key.
function dayKeyOf(iso) {
  const d = expDate(iso);
  if (!d || isNaN(d)) return '';
  if (currentTimezone) {
    // en-CA already formats as YYYY-MM-DD, so no part-picking is needed.
    try { return _dayFormatter().format(d); } catch (e) { _dayFmt = null; }
  }
  const p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

// Friendly day header: Today / Yesterday / "Wed, May 20, 2026".
function dayLabelOf(iso) {
  const key = dayKeyOf(iso);
  if (!key) return 'unknown';
  const todayKey = dayKeyOf(new Date().toISOString());
  const y = new Date(); y.setDate(y.getDate() - 1);
  if (key === todayKey) return 'Today';
  if (key === dayKeyOf(y.toISOString())) return 'Yesterday';
  const d = expDate(iso);
  const opts = { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' };
  if (currentTimezone) opts.timeZone = currentTimezone;
  try { return d.toLocaleDateString('en-US', opts); } catch (e) { return key; }
}

// ── Grouping modes (shared by the main table and the sidebar rail) ───────────
// How each mode keys and labels a run. The two views used to derive the same
// six modes independently and had already drifted: the table keyed an unset
// branch as the literal `'no branch'` while the rail used a `'__no_branch__'`
// sentinel, the day key was computed in three places, and the table rendered
// its italic "(no X)" placeholder for Study only — so its Script and Branch
// modes showed a bare `no script` header. The *rendering* and the collapse
// state stay per-view on purpose (different markup, and opposite
// expanded-by-default conventions); only the derivation is shared.
//
// `keyOf` returns NO_GROUP when the run has no value for the mode; `labelOf`
// is plain text (never markup — the views escape and decorate it themselves).
const NO_GROUP = '__none__';

const GROUP_MODES = {
  git_commit: { empty: '(no commit)',
    keyOf: e => e.git_commit ? e.git_commit.slice(0, 7) : NO_GROUP },
  git_branch: { empty: '(no branch)', keyOf: e => e.git_branch || NO_GROUP },
  script: { empty: '(no script)',
    keyOf: e => e.script ? pathBase(e.script) : NO_GROUP },
  status: { empty: '(no status)', keyOf: e => e.status || NO_GROUP },
  day: { empty: '(no date)',
    keyOf: e => dayKeyOf(e.created_at) || NO_GROUP,
    labelOf: (key, items) => dayLabelOf(items[0].created_at) },
  study: { empty: '(no study)',
    keyOf: e => (e.studies && e.studies.length) ? e.studies[0] : NO_GROUP },
};

// The group header text for a key, as escaped HTML — the italic placeholder
// for the empty group, the plain escaped label otherwise.
function groupLabelHtml(modeId, key, items) {
  const mode = GROUP_MODES[modeId];
  if (!mode) return esc(key);
  if (key === NO_GROUP) {
    return '<span style="color:var(--muted);font-style:italic">' + esc(mode.empty) + '</span>';
  }
  return esc(mode.labelOf ? mode.labelOf(key, items) : key);
}

function setDateRange(r) {
  dateRange = r;
  localStorage.setItem('exptrack-date-range', r);
  // Both surfaces carry the control now (group bar and sidebar rail), so both
  // have to show which range is on.
  document.querySelectorAll('#group-bar [data-range], #sidebar-range-chips [data-range]')
    .forEach(b => b.classList.toggle('active', b.getAttribute('data-range') === r));
  rerender();
}

function setAutoNamedOnly(on) {
  autoNamedOnly = !!on;
  localStorage.setItem('exptrack-auto-named-only', autoNamedOnly ? 'true' : 'false');
  const cb = document.getElementById('auto-named-toggle');
  if (cb) cb.checked = autoNamedOnly;
  recentlyRenamedIds.clear();
  rerender();
}

// Kept as the named setter because the empty-state buttons ("Show failed runs")
// call it with an explicit value — they are not toggles.
function setShowFailed(on) {
  showFailed = !!on;
  _storageSet('exptrack-hide-failed', showFailed ? '0' : '1');
  // This changes what is *listed*, not what is selected, so the full re-render
  // is the right call (and it is a re-render, not a reload — the rows are
  // already in `allExperiments`).
  rerender();
}

function toggleShowFailed() { setShowFailed(!showFailed); }

// Sort the main table by a metric value ('' clears back to created_at).
function setMetricSort(key) {
  if (!key) {
    if (sortCol.startsWith('metric:')) { sortCol = 'created_at'; sortDir = 'desc'; }
  } else {
    sortCol = 'metric:' + key;
    sortDir = 'desc';
  }
  const sel = document.getElementById('metric-sort-select');
  if (sel) sel.value = key;
  if (typeof updateSortHeaders === 'function') updateSortHeaders();
  rerender();
}

// Populate the metric-sort dropdown with every metric key present in the
// current experiment set, preserving the active selection.
function updateMetricSortOptions() {
  const sel = document.getElementById('metric-sort-select');
  if (!sel) return;
  const keys = new Set();
  for (const e of (allExperiments || [])) {
    for (const k of Object.keys(e.metrics || {})) keys.add(k);
  }
  const active = sortCol.startsWith('metric:') ? sortCol.slice(7) : '';
  const opts = ['<option value="">—</option>'];
  for (const k of [...keys].sort()) {
    opts.push('<option value="' + esc(k) + '"' + (k === active ? ' selected' : '') + '>' + esc(k) + '</option>');
  }
  sel.innerHTML = opts.join('');
  sel.value = active;
}

// Renders the failed-runs control: one button that states the action it
// offers, and — while it is hiding rows — how many it is withholding.
//
// The count is what makes the hidden state honest, so it is counted against
// the view as it actually stands: the same `getFilteredExperiments` the table
// renders, with this one filter lifted, so search, tag/study, "needs naming"
// and the date range are all already applied. (It covers the runs loaded so
// far, like every other count here; `renderTruncNotice` states that.)
function updateFailedCount() {
  const btn = document.getElementById('show-failed-toggle');
  if (!btn) return;
  // The sidebar's Failed status chip asks the server for exactly these runs,
  // and `getFilteredExperiments` lifts this filter while it is on — otherwise
  // the chip would show nothing. So the button cannot be truthful here: it is
  // disabled and names the control that won, rather than offering an action
  // that does nothing or a count that is a lie.
  if (currentFilter === 'failed') {
    btn.textContent = 'Hide failed';
    btn.disabled = true;
    btn.title = 'The Failed status filter is showing only failed runs';
    return;
  }
  btn.disabled = false;
  if (showFailed) {
    btn.textContent = 'Hide failed';
    btn.title = 'Hide failed runs from the list';
    return;
  }
  const n = getFilteredExperiments({includeFailed: true}).filter(e => e.status === 'failed').length;
  btn.textContent = n > 0 ? 'Show failed (' + n + ')' : 'Show failed';
  btn.title = n > 0
    ? n + ' failed run' + (n > 1 ? 's are' : ' is') + ' hidden from this view'
    : 'No failed runs in the current view';
}

// Reflect persisted date-range / needs-naming state in the controls on boot.
function syncFilterControls() {
  document.querySelectorAll('#group-bar [data-range]').forEach(b =>
    b.classList.toggle('active', b.getAttribute('data-range') === dateRange));
  // The markup's first <option> is not the default, so reflect the real state.
  const gs = document.getElementById('group-by-select');
  if (gs && gs.value !== groupBy) gs.value = groupBy;
  const cb = document.getElementById('auto-named-toggle');
  if (cb) cb.checked = autoNamedOnly;
  updateAutoNamedCount();
  updateFailedCount();
  updateMetricSortOptions();
}

// Live count of un-renamed runs next to the "Needs naming" toggle so the
// filter has a visible signal even when every run happens to need naming.
function updateAutoNamedCount() {
  const el = document.getElementById('auto-named-count');
  if (!el) return;
  const n = (allExperiments || []).filter(e => e.name_is_auto).length;
  el.textContent = n > 0 ? '(' + n + ')' : '';
  el.style.display = n > 0 ? '' : 'none';
}

function fmtTimeAgo(iso) {
  if (!iso) return '--';
  const now = new Date();
  // Stored timestamps are UTC but carry no zone suffix; parsing them raw reads
  // them as local time, so "2h ago" was off by the viewer's UTC offset (and read
  // as a future time west of UTC). expDate() is the shared normalization.
  const then = expDate(iso);
  if (!then || isNaN(then)) return '--';
  const diff = Math.floor((now - then) / 1000);
  if (diff < 60) return diff + 's ago';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

function fmtDt(iso) {
  if (!iso) return '--';
  // expDate is the one normalization — these used to re-implement it inline and
  // so inherited the string-only assumption it has now shed.
  const d = expDate(iso);
  if (!d || isNaN(d)) return '--';
  if (currentTimezone) {
    try {
      const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: currentTimezone, month: 'numeric', day: 'numeric',
        hour: '2-digit', minute: '2-digit', hour12: false
      }).formatToParts(d);
      const get = type => (parts.find(p => p.type === type) || {}).value || '';
      return get('month') + '/' + get('day') + ' ' + get('hour') + ':' + get('minute');
    } catch(e) {}
  }
  return (d.getMonth()+1) + '/' + d.getDate() + ' ' +
         String(d.getHours()).padStart(2,'0') + ':' + String(d.getMinutes()).padStart(2,'0');
}

function fmtDtFull(iso) {
  if (!iso) return '--';
  const d = expDate(iso);
  if (!d || isNaN(d)) return '--';
  const opts = { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
  if (currentTimezone) opts.timeZone = currentTimezone;
  try { return d.toLocaleString('en-US', opts); } catch(e) {}
  return d.toLocaleString();
}

async function setTimezone(tz) {
  currentTimezone = tz;
  localStorage.setItem('exptrack-tz', tz);
  try { await postApi('/api/config/timezone', {timezone: tz}); } catch(e) {}
  renderExperiments();
  renderExpList();
  if (currentDetailId) refreshDetail(currentDetailId);
  owlSay(tz ? 'Timezone set to ' + tz + '!' : 'Using your browser timezone!');
}

async function loadTimezoneConfig() {
  try {
    const data = await api('/api/config/timezone');
    if (data.timezone) {
      currentTimezone = data.timezone;
      localStorage.setItem('exptrack-tz', data.timezone);
    }
  } catch(e) {}
  const sel = document.getElementById('tz-select');
  if (sel) sel.value = currentTimezone;
}

async function loadMetricSettings() {
  try {
    const data = await api('/api/config/metrics');
    _chartsMaxPoints = data.metric_max_points || 500;
    const keepEl = document.getElementById('settings-keep-every');
    const ptsEl = document.getElementById('settings-max-points');
    if (keepEl) keepEl.value = data.metric_keep_every || 1;
    if (ptsEl) ptsEl.value = data.metric_max_points || 500;
    _updateKeepEveryNote(data.metric_keep_every || 1);
  } catch(e) {}
}

// Thinning is the one setting here that destroys data — points it drops are
// never written, so an empty chart is the only feedback the user ever got. Say
// what the value means, in the units they're about to see it in.
function _updateKeepEveryNote(keepEvery) {
  const el = document.getElementById('keep-every-note');
  if (!el) return;
  const n = parseInt(keepEvery, 10);
  if (!(n > 1)) { el.textContent = ''; return; }
  el.textContent = 'Recording 1 of every ' + n + ' points your code logs — a run '
    + 'logging 1,000 points will store about ' + Math.max(1, Math.round(1000 / n))
    + '. Dropped points are never written and cannot be recovered. Set this to 1 '
    + 'to record everything, and thin later with exptrack prune.';
}

async function saveMetricSettings() {
  const keepEl = document.getElementById('settings-keep-every');
  const ptsEl = document.getElementById('settings-max-points');
  const keepEvery = keepEl ? parseInt(keepEl.value, 10) : 1;
  const maxPoints = ptsEl ? parseInt(ptsEl.value, 10) : 500;
  try {
    const res = await postApi('/api/config/metrics', {
      metric_keep_every: keepEvery,
      metric_max_points: maxPoints
    });
    if (res.ok) {
      _chartsMaxPoints = res.metric_max_points;
      _updateKeepEveryNote(res.metric_keep_every);
      owlSay(res.metric_keep_every > 1
        ? 'Saved — storing 1 of every ' + res.metric_keep_every + ' metric points.'
        : 'Metric settings saved!');
    } else {
      alert(res.error || 'Failed to save');
    }
  } catch(e) { alert('Failed to save settings'); }
}

async function loadCaptureSettings() {
  try {
    const data = await api('/api/config/capture');
    const nbEl = document.getElementById('settings-notebook-capture');
    const mbEl = document.getElementById('settings-var-fp-mb');
    if (nbEl) nbEl.checked = data.notebook_capture !== false;
    if (mbEl) mbEl.value = data.var_fingerprint_max_mb || 100;
  } catch(e) {}
}

async function saveCaptureSettings() {
  const nbEl = document.getElementById('settings-notebook-capture');
  const mbEl = document.getElementById('settings-var-fp-mb');
  try {
    const res = await postApi('/api/config/capture', {
      notebook_capture: nbEl ? nbEl.checked : true,
      var_fingerprint_max_mb: mbEl ? parseInt(mbEl.value, 10) : 100
    });
    if (res.ok) {
      if (mbEl) mbEl.value = res.var_fingerprint_max_mb;
      owlSay('Capture settings saved! (restart the notebook kernel to apply)');
    } else {
      alert(res.error || 'Failed to save');
    }
  } catch(e) { alert('Failed to save settings'); }
}

async function loadAllTags() {
  try {
    const data = await api('/api/all-tags');
    allKnownTags = data.tags || [];
  } catch(e) { allKnownTags = []; }
}

async function loadAllStudies() {
  try {
    const data = await api('/api/all-studies');
    allKnownStudies = data.studies || [];
  } catch(e) { allKnownStudies = []; }
}

function toggleHelp() {
  document.getElementById('help-panel').classList.toggle('visible');
  document.getElementById('help-overlay').classList.toggle('visible');
}

// ── Settings panel ─────────────────────────────────────────────────────────

function toggleSettingsPanel() {
  const panel = document.getElementById('settings-panel');
  const isOpen = panel.classList.toggle('visible');
  if (isOpen) loadStorageInfo();
}

// Close settings when clicking outside
document.addEventListener('click', function(e) {
  const panel = document.getElementById('settings-panel');
  if (!panel) return;
  const wrap = panel.closest('.settings-wrap');
  if (panel.classList.contains('visible') && !wrap.contains(e.target)) {
    panel.classList.remove('visible');
  }
});

// Hold the page's scroll position across a write that can change the height of
// what is on screen.
//
// `#main-content` is the scroller, and the browser clamps its scrollTop the
// moment its content becomes shorter than the current offset — so anything that
// collapses part of the page (a panel emptied, an image grid losing its decoded
// images) silently moves the reader, usually to the top. `refreshDetail` has
// carried this by hand since the live-run poll started doing it every five
// seconds; this is the same three lines, shared.
//
// Returns a restore function. Call it after the write, and again on the next
// frame: layout can settle a frame late (images, fonts, a flex reflow), and a
// clamp that happens then would otherwise stand.
function _holdMainScroll() {
  const el = document.getElementById('main-content');
  const kept = el ? el.scrollTop : 0;
  return function () {
    if (!el || !kept) return;
    if (el.scrollTop !== kept) el.scrollTop = kept;
  };
}

// The backdrop an image modal is viewed against. Dark is right for a
// matplotlib plot and wrong for a dark segmentation mask or a light-on-white
// sample, so it is a choice rather than a constant — kept in localStorage
// because it is a per-reader viewing preference, not project state, and it is
// answered once and then wanted on every image after that.
const MODAL_BACKDROPS = [
  {id: 'dark', label: 'Dark backdrop (default)'},
  {id: 'light', label: 'Light backdrop'},
  {id: 'grey', label: 'Mid-grey backdrop'},
  {id: 'checker', label: 'Checkerboard — shows what is transparent'},
];

let _modalBackdrop = 'dark';
try {
  const saved = localStorage.getItem('exptrack-modal-backdrop');
  if (saved && MODAL_BACKDROPS.some(b => b.id === saved)) _modalBackdrop = saved;
} catch (e) { /* storage can throw outright; the default stands */ }

// The swatch row both modal headers render.
function modalBackdropPickerHtml() {
  let h = '<div class="modal-backdrop-pick" title="Backdrop">';
  for (const b of MODAL_BACKDROPS) {
    h += '<button type="button" data-bd="' + b.id + '"'
      + (b.id === _modalBackdrop ? ' class="active"' : '')
      + ' title="' + esc(b.label) + '" aria-label="' + esc(b.label) + '"'
      + ' onclick="setModalBackdrop(\'' + escJsAttr(b.id) + '\')"></button>';
  }
  return h + '</div>';
}

// Applied to whichever image modal is open. Only one of them is ever open at
// a time, but writing to both keeps this the single place that knows the
// attribute name and which swatch is marked.
function applyModalBackdrop() {
  document.querySelectorAll('.img-cmp-overlay, .img-modal-overlay').forEach(el => {
    el.setAttribute('data-backdrop', _modalBackdrop);
    el.querySelectorAll('.modal-backdrop-pick button').forEach(b => {
      b.classList.toggle('active', b.getAttribute('data-bd') === _modalBackdrop);
    });
  });
}

function setModalBackdrop(id) {
  if (!MODAL_BACKDROPS.some(b => b.id === id)) return;
  _modalBackdrop = id;
  try { localStorage.setItem('exptrack-modal-backdrop', id); } catch (e) {}
  applyModalBackdrop();
}

// A modal opened to look closer must not show the image smaller than the grid
// it was opened from. `max-width`/`max-height` only ever shrink, so a 128x128
// sample rendered at 128px in a full-screen overlay while the gallery thumb
// upscaled it to ~180px — clicking to enlarge made it smaller. This scales a
// small image up to the space the modal actually has, capped at
// MODAL_IMAGE_MAX_UPSCALE so a tiny icon does not become a wall of blur, and
// switches to nearest-neighbour past 2x because a 128px raster upscaled
// smoothly reads as out of focus rather than as pixels.
//
// Every image in one modal gets the SAME scale, computed from the largest of
// them: an overlay or swipe compare aligns two images on top of each other,
// and independently fitted images would not line up.
// Below MIN the image is already near the size of the window and stretching
// it buys nothing but a softer picture; a 1200px figure in a 1296px slot is
// not the problem this solves.
const MODAL_IMAGE_MIN_UPSCALE = 1.25;
const MODAL_IMAGE_MAX_UPSCALE = 4;

function fitModalImages(imgs, availW, availH) {
  const list = Array.from(imgs || []).filter(Boolean);
  if (!list.length) return;
  let pending = list.length;
  const apply = function () {
    let nw = 0, nh = 0;
    for (const img of list) {
      nw = Math.max(nw, img.naturalWidth || 0);
      nh = Math.max(nh, img.naturalHeight || 0);
    }
    if (!nw || !nh) return;
    const scale = Math.min(availW / nw, availH / nh, MODAL_IMAGE_MAX_UPSCALE);
    if (scale < MODAL_IMAGE_MIN_UPSCALE) return;  // near-size images stay as they are
    for (const img of list) {
      const w = img.naturalWidth || nw, h = img.naturalHeight || nh;
      img.style.width = Math.round(w * scale) + 'px';
      img.style.height = Math.round(h * scale) + 'px';
      if (scale >= 2) img.style.imageRendering = 'pixelated';
    }
  };
  // Natural size is only known once each image has decoded, and the scale is
  // shared, so it waits for all of them.
  const ready = function () { if (--pending === 0) apply(); };
  for (const img of list) {
    // `complete` covers a decoded image and a failed one alike; a broken image
    // fires no further event, so it must count itself in or the scale never
    // gets applied to the images beside it.
    if (img.complete) ready();
    else {
      img.addEventListener('load', ready, {once: true});
      img.addEventListener('error', ready, {once: true});
    }
  }
}

function fmtBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1024*1024) return (b/1024).toFixed(1) + ' KB';
  return (b/(1024*1024)).toFixed(1) + ' MB';
}

// Row counts alone never told you what was actually taking the space. The
// panel leads with bytes — metrics first, since they are the only table
// written inside a training loop and so are almost always the largest — then
// names the runs holding it, so the next click is an action rather than
// another question.
function _storageRow(label, value, strong) {
  return '<div class="storage-row' + (strong ? ' storage-row-strong' : '') + '">' +
    '<span>' + esc(label) + '</span>' +
    '<span class="storage-val">' + esc(value) + '</span></div>';
}

function _metricKeyRows(keys) {
  if (!keys || !keys.length) return '';
  return '<div class="storage-sub">' + keys.map(k =>
    '<div class="storage-row storage-row-sub" title="' +
      esc(k.key + ' — ' + k.points.toLocaleString() + ' points across ' +
          k.experiments + ' run(s), up to ' + k.max_per_exp.toLocaleString() +
          ' in one run') + '">' +
      '<span class="storage-key">' + esc(k.key) + '</span>' +
      '<span class="storage-val">' + esc(fmtBytes(k.bytes)) + '</span></div>'
  ).join('') + '</div>';
}

function _largestExpRows(exps) {
  if (!exps || !exps.length) return '';
  return '<div class="storage-sub">' + exps.map(e => {
    const name = e.name || '(unnamed)';
    const tip = name + ' — ' + fmtBytes(e.metrics_bytes) + ' of metrics (' +
      e.n_metrics.toLocaleString() + ' points), ' + fmtBytes(e.timeline_bytes) +
      ' timeline, ' + e.n_artifacts + ' artifacts' +
      (e.trashed ? ' — in Trash' : '');
    return '<div class="storage-row storage-row-sub" title="' + esc(tip) + '">' +
      '<span class="storage-key storage-exp-link" onclick="showDetail(\'' +
        escJsAttr(e.id) + '\')">' + esc(name) +
        (e.trashed ? ' <span class="storage-trash-tag">trash</span>' : '') + '</span>' +
      '<span class="storage-val">' + esc(fmtBytes(e.db_bytes)) + '</span></div>';
  }).join('') + '</div>';
}

// Soft delete keeps every row and leaves output files where they are, so the
// Trash is the one place storage builds up with nothing else in the panel
// showing it. Rendered only when there is something in it — a permanent
// "Trash: 0 B" row is noise on the common case.
function _trashStorageSection(t) {
  if (!t) return '';
  const reclaim = (t.db_bytes || 0) + (t.output_bytes || 0);
  if (!t.experiments && !t.nodes && !t.sessions && !t.local_files) return '';
  let rows = '';
  if (t.experiments) {
    rows += _storageRow(t.experiments.toLocaleString() + ' trashed run' +
                        (t.experiments === 1 ? '' : 's'), fmtBytes(t.exp_db_bytes));
  }
  if (t.nodes || t.sessions) {
    rows += _storageRow(t.nodes.toLocaleString() + ' trashed session node' +
                        (t.nodes === 1 ? '' : 's') +
                        (t.sessions ? ' (' + t.sessions + ' whole session' +
                          (t.sessions === 1 ? '' : 's') + ')' : ''),
                        fmtBytes(t.node_db_bytes));
  }
  if (t.output_files) {
    rows += '<div class="storage-row" title="Output files belonging to trashed ' +
      'runs. Kept in place until you permanently delete with &quot;also move ' +
      'files&quot;.">' +
      '<span>' + esc(t.output_files.toLocaleString() + ' output files on disk') +
      '</span><span class="storage-val">' + esc(fmtBytes(t.output_bytes)) +
      '</span></div>';
  }
  if (t.local_files) {
    rows += '<div class="storage-row" title="Files exptrack could not hand to ' +
      'the OS Trash, kept in .exptrack/trash/. Nothing but you removes these.">' +
      '<span>.exptrack/trash/</span><span class="storage-val">' +
      esc(fmtBytes(t.local_bytes)) + '</span></div>';
  }
  return '<div class="storage-head">Trash' +
      '<button class="storage-prune-btn" onclick="openTrashView()" ' +
        'title="Open the Trash to restore or permanently delete">Open…</button>' +
    '</div>' + rows +
    (reclaim ? '<div class="storage-note">~' + esc(fmtBytes(reclaim)) +
      ' reclaimable by deleting permanently (then Clean → vacuum to return the ' +
      'freed database pages to the filesystem).</div>' : '');
}

// Rows whose experiment no longer exists — a database written by an older
// version, hand-edited, or a process killed mid-delete. They are invisible in
// every list while still occupying the file, and unlike the CLI the dashboard
// never sweeps on its own (the per-request close skips it deliberately), so
// the panel has to both name them and offer the sweep.
function _orphanStorageSection(o) {
  if (!o || !o.rows) return '';
  const rows = Object.entries(o.tables || {}).map(([t, v]) =>
    _storageRow(t + ' (' + v.rows.toLocaleString() + ' row' +
                (v.rows === 1 ? '' : 's') + ')', fmtBytes(v.bytes))
  ).join('');
  return '<div class="storage-head">Orphaned rows' +
      '<button class="storage-prune-btn" onclick="settingsCleanDb()" ' +
        'title="Remove rows that reference an experiment which no longer exists">Clean…</button>' +
    '</div>' + rows +
    '<div class="storage-note">' + o.rows.toLocaleString() + ' row(s), ~' +
      esc(fmtBytes(o.bytes)) + ' — they belong to experiments that no longer ' +
      'exist and show up nowhere in the UI.</div>';
}

// Captured source code, split by what reclaims it: snapshots (the durable
// record — freed only by deleting the last run holding a blob) vs. the
// derived change summaries (freed by compact --code-changes). Both figures
// are exact text sums, so no "estimated" label.
function _sourceCodeStorageSection(sc) {
  if (!sc || !sc.bytes) return '';
  return '<div class="storage-head">Source code — ' + esc(fmtBytes(sc.bytes)) + '</div>' +
    '<div class="storage-row" title="Content-addressed full source, one copy per ' +
      'distinct script version. The durable record — kept until the last run ' +
      'referencing it is permanently deleted.">' +
      '<span>Snapshots</span><span class="storage-val">' +
      esc(sc.snapshot_count.toLocaleString() + ' (' + fmtBytes(sc.snapshot_bytes) + ')') +
    '</span></div>' +
    '<div class="storage-row" title="Derived per-run change summaries. Reclaimable ' +
      'with exptrack compact --code-changes for runs whose snapshot survives.">' +
      '<span>Change summaries</span><span class="storage-val">' +
      esc(sc.summary_rows.toLocaleString() + ' (' + fmtBytes(sc.summary_bytes) + ')') +
    '</span></div>';
}

async function loadStorageInfo() {
  const el = document.getElementById('settings-storage');
  try {
    const res = await postApi('/api/storage-info');
    if (!res || !res.ok) { el.textContent = 'Could not load'; return; }
    const est = res.exact_sizes ? '' :
      '<div class="storage-note">Sizes estimated — this SQLite build has no dbstat.</div>';
    const metricsPct = res.db_bytes
      ? Math.round((res.metrics_bytes / res.db_bytes) * 100) : 0;

    // Deleted rows leave their pages on SQLite's free list — the file itself
    // never shrinks until a vacuum. Without this row the breakdown below
    // simply doesn't add up to the DB file size after a delete, which reads
    // as the delete having done nothing.
    const freeRow = res.free_bytes
      ? '<div class="storage-row" title="Space inside the database file left ' +
          'by deleted rows. It is reused as the database grows; Clean → vacuum ' +
          'returns it to the filesystem.">' +
          '<span>of which free</span><span class="storage-val">' +
          esc(fmtBytes(res.free_bytes) + ' (' + res.free_pct + '%)') +
        '</span></div>'
      : '';
    el.innerHTML =
      _storageRow('DB file', fmtBytes(res.db_bytes), true) +
      freeRow +
      _storageRow('WAL file', fmtBytes(res.wal_bytes)) +
      '<div class="storage-head">Metrics — ' + esc(fmtBytes(res.metrics_bytes)) +
        ' (' + metricsPct + '% of DB)' +
        '<button class="storage-prune-btn" onclick="openPruneMetrics()" ' +
          'title="Thin stored metric points to reclaim space">Prune…</button>' +
      '</div>' +
      _metricKeyRows(res.metric_keys) +
      (res.metric_key_count > (res.metric_keys || []).length
        ? '<div class="storage-note">… and ' +
            (res.metric_key_count - res.metric_keys.length) + ' more keys</div>'
        : '') +
      _sourceCodeStorageSection(res.source_code) +
      '<div class="storage-head">Largest runs (estimated)</div>' +
      _largestExpRows(res.largest_experiments) +
      _trashStorageSection(res.trash) +
      _orphanStorageSection(res.orphans) +
      '<div class="storage-head">Row counts</div>' +
      _storageRow('Experiments', res.experiments.toLocaleString()) +
      _storageRow('Params', res.params.toLocaleString()) +
      _storageRow('Metrics', res.metrics.toLocaleString()) +
      _storageRow('Artifacts', res.artifacts.toLocaleString()) +
      _storageRow('Timeline', res.timeline.toLocaleString()) +
      est;
  } catch(e) { el.textContent = 'Error loading storage info'; }
}

// Prune is destructive and unrecoverable, so it always previews first: the
// confirm text quotes the real point count and byte figure the delete will
// use, not an estimate computed separately.
async function openPruneMetrics() {
  const raw = prompt(
    'Thin stored metric points down to at most how many per metric, per run?\n\n' +
    'Charts downsample to 500 points anyway, so 500 loses nothing visible.\n' +
    'The first, last, minimum and maximum of every series are always kept.',
    '500');
  if (raw === null) return;
  const maxPoints = parseInt(raw, 10);
  if (!maxPoints || maxPoints < 2) { alert('Enter a number of 2 or more.'); return; }

  try {
    const pre = await postApi('/api/prune-metrics',
                              {max_points: maxPoints, dry_run: true});
    if (!pre || pre.error) { alert('Error: ' + ((pre && pre.error) || 'failed')); return; }
    if (!pre.points) {
      owlSay('Nothing to prune — every series is already at or under ' + maxPoints + ' points');
      return;
    }
    if (!confirm('Permanently remove ' + pre.points.toLocaleString() + ' of ' +
                 pre.total_points.toLocaleString() + ' metric points (~' +
                 fmtBytes(pre.freed) + '), leaving ' + pre.remaining.toLocaleString() +
                 '?\n\nThis cannot be undone.')) return;

    // preview_token: delete exactly the set the confirm above described, not a
    // fresh selection that would also take points logged while it was open.
    const res = await postApi('/api/prune-metrics',
                              {max_points: maxPoints, preview_token: pre.preview_token});
    if (!res || res.error) { alert('Error: ' + ((res && res.error) || 'failed')); return; }
    owlSay('Pruned ' + res.deleted.toLocaleString() + ' points (~' +
           fmtBytes(res.freed) + '). Use Vacuum to return the space to disk.');
    if (currentDetailId) refreshDetail(currentDetailId);
  } catch(e) {
    alert('Failed: ' + e.message);
  } finally {
    loadStorageInfo();
  }
}

// Row cleanup runs unprompted (bookkeeping). Orphaned *files* are reported
// back and only moved to the OS Trash after an explicit, itemised confirm —
// an "orphan" under outputs/ is just as likely to be checkpoints the user
// deliberately kept when permanently deleting a run.
async function settingsCleanDb() {
  try {
    const res = await postApi('/api/clean-db');
    if (res.error) { alert('Error: ' + res.error); return; }
    if (res.removed > 0) loadExperiments();
    const rowMsg = res.removed === 0 ? 'Database is clean — no orphans!'
                                     : 'Removed ' + res.removed + ' orphaned row(s)';
    const orphans = res.orphan_files || [];
    if (!orphans.length) { owlSay(rowMsg); return; }
    if (!confirm(_orphanFilesPrompt(res.removed, orphans))) {
      owlSay(rowMsg + ' — files left alone');
      return;
    }
    // Post back exactly what the confirm listed — the server intersects it
    // with the paths still orphaned, so anything written under outputs/
    // since the dialog was built is never trashed unseen.
    const res2 = await postApi('/api/clean-db', {
      delete_files: true,
      paths: orphans.map(o => o.path),
    });
    if (res2.error) { alert('Error: ' + res2.error); return; }
    let msg = 'Moved ' + ((res2.details && res2.details.output_paths) || 0) +
              ' orphaned path(s) to the Trash';
    if (res2.skipped_unconfirmed) {
      msg += ' — ' + res2.skipped_unconfirmed + ' new one(s) appeared since, left alone';
    }
    owlSay(msg);
  } catch(e) {
    alert('Failed: ' + e.message);
  } finally {
    loadStorageInfo();
  }
}

// Itemised confirm text for orphaned output paths. Spells out that "orphan" is
// a heuristic — files kept when a run was permanently deleted land here too.
function _orphanFilesPrompt(removedRows, orphans) {
  // Through the same helper the delete dialogs use: this confirm reports the
  // identical capped-walk figures, and two spellings of "≥" (or two byte
  // formatters) would have the same directory read differently in the two
  // places the user meets it.
  const shown = orphans.slice(0, 12).map(o =>
    '  ' + o.name + (o.is_dir ? '/' : '') +
    '  (' + _dirFigures(o.files, o.bytes, o.truncated, true) + ')'
  ).join('\n');
  const more = orphans.length > 12 ? '\n  …and ' + (orphans.length - 12) + ' more' : '';
  const totalBytes = orphans.reduce((s, o) => s + (o.bytes || 0), 0);
  return 'Removed ' + removedRows + ' orphaned row(s).\n\n' +
    orphans.length + ' path(s) under outputs/ are not claimed by any run ' +
    '(' + fmtBytes(totalBytes) + '):\n\n' + shown + more +
    '\n\nMove them to the Trash? They stay recoverable from your OS Trash.\n' +
    'Runs you deleted while choosing to keep their files appear here too.';
}

async function settingsVacuumDb() {
  try {
    const res = await postApi('/api/vacuum-db');
    if (!res.ok) { alert('Error: ' + (res.error || 'vacuum failed')); return; }
    owlSay('Database vacuumed — WAL cleared!');
    loadStorageInfo();
  } catch(e) { alert('Failed: ' + e.message); }
}

async function settingsResetDb() {
  if (!confirm('DELETE ALL EXPERIMENTS AND DATA?\n\nThis cannot be undone!')) return;
  if (!confirm('Are you really sure? This will permanently erase everything.')) return;
  try {
    const res = await postApi('/api/reset-db');
    if (!res.ok) { alert('Error: ' + (res.error || 'reset failed')); return; }
    owlSay('Database reset — ' + res.deleted_experiments + ' experiment(s) removed');
    loadExperiments();
    loadStorageInfo();
    showWelcome();
  } catch(e) { alert('Failed: ' + e.message); }
}

