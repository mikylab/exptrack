// ── Parameter matrix ─────────────────────────────────────────────────────────
// The analysis view over a set of runs: one row per run, one column per
// parameter that actually *varied* across the set. Distinct from the
// experiment list on purpose — that one is for navigation, and showing every
// captured parameter there buries the two or three that were swept.
//
// The set analysed is whatever the list is currently filtered to, posted by id
// (see core/param_study.py): what varies is a property of the set on screen,
// not of a stored grouping.

let _matrixData = null;
let _matrixRankBy = _storageGet('exptrack-matrix-rank-by') || 'final';
let _matrixIncludeRunning = _storageGet('exptrack-matrix-running') === '1';
let _matrixIncludeFailed = _storageGet('exptrack-matrix-failed') !== '0';
let _matrixSort = null;      // {col: 'param:lr'|'metric'|'name'|'started', dir: 1|-1}
let _matrixSelected = new Set();

// `opts.replaceHash` marks a *return* to this view (Compare's Back) rather
// than an entry into it, so the browser's Back doesn't bounce between the two.
function openParamMatrix(opts) {
  releaseCanvas();
  // An address, so the browser's Back button steps back a view instead of
  // leaving the dashboard — and so Back out of a comparison opened from here
  // lands on the matrix rather than on the experiments list.
  _pushViewHash('#matrix', opts && opts.replaceHash);
  document.body.classList.add('matrix-active');
  const mv = document.getElementById('matrix-view');
  if (mv) mv.style.display = '';
  loadParamMatrix();
}

// The "← Back" handler: put the matrix down and return to whatever the user was
// on before it. Callers that raise a view of their own (the Compare handoff,
// opening a run) don't need this at all — every view switcher releases the
// canvas itself, so calling this first would only flash a view being left.
function closeParamMatrix() {
  releaseCanvas();
  _clearViewHash();
  if (currentDetailId) { refreshDetail(currentDetailId, {keepSidebar: true}); return; }
  _showListView();
}

// An explicit set of runs to analyse, chosen in the run picker. Null means
// "whatever the experiment list is filtered to", which is the default and was
// for a long time the *only* option: narrowing the analysed set meant leaving
// this view, rewriting the list's search box, and coming back — and it could
// only be expressed as a search, so "these five runs" was not expressible at
// all unless their names happened to share a substring.
let _matrixIdSet = null;

// The ids analysed are the chosen set, or the filtered one — the controls say
// which, because an analysis over a subset that reads as the whole search would
// misreport what varies.
function _matrixIds() {
  if (_matrixIdSet) return [..._matrixIdSet];
  // includeFailed: the matrix has its own "Show failed" control, so the list's
  // toggle must not strip those runs out upstream — otherwise this view's own
  // checkbox would sit there checked and do nothing.
  return getFilteredExperiments({includeFailed: true}).map(e => e.id);
}

function openMatrixRunPicker() {
  openRunPicker({
    title: 'Choose runs to analyze',
    mode: 'multi',
    preselect: new Set(_matrixIds()),
    confirmLabel: 'Analyze',
    onConfirm: ids => {
      // An empty pick is "go back to the filter", not "analyse nothing": the
      // latter is a dead view whose only escape is the control that produced it.
      _matrixIdSet = ids.length ? new Set(ids) : null;
      loadParamMatrix();
    },
  });
}

function clearMatrixRunChoice() {
  _matrixIdSet = null;
  loadParamMatrix();
}

async function loadParamMatrix() {
  const ids = _matrixIds();
  if (!ids.length) {
    _matrixMessage('No runs in the current filter.<br>' +
      '<span class="mx-empty-hint">Clear the search or filters in the experiments list, ' +
      'or <button class="btn-sm" onclick="openMatrixRunPicker()">choose runs</button> ' +
      'to analyze directly.</span>');
    return;
  }
  _matrixMessage('Analyzing ' + ids.length + ' runs…');
  const data = await postApi('/api/param-matrix', {
    ids: ids,
    rank_by: _matrixRankBy,
    include_running: _matrixIncludeRunning,
    include_failed: _matrixIncludeFailed,
  });
  if (!data || data.error) {
    _matrixMessage(esc((data && data.error) || 'Could not analyze these runs.'));
    return;
  }
  _matrixData = data;
  // The selection survives closing the view, but the set analysed is whatever
  // the list is filtered to — so a pick must not outlive the rows it was made
  // against, or the bar's count and the ticked boxes disagree.
  _pruneMatrixSelection(data.rows || []);
  renderParamMatrix();
}

function _pruneMatrixSelection(rows) {
  if (!_matrixSelected.size) return;
  const present = new Set(rows.map(r => r.id));
  _matrixSelected = new Set([..._matrixSelected].filter(id => present.has(id)));
}

function _matrixMessage(html) {
  const container = document.getElementById('matrix-view');
  if (container) container.innerHTML = _matrixShell('<div class="mx-empty">' + html + '</div>');
}

// The same header shell every other full-canvas view uses (`.back-link` above
// the title, sentence case), rather than a private one. The title used to be an
// `<h2>`, which the table stylesheet renders uppercase, letter-spaced and grey
// for section headings *inside* a view — so this view announced itself in a
// style nothing else on the page used, next to an unstyled default browser
// button. Neither was a decision; both were what the markup happened to inherit.
function _matrixShell(inner) {
  return '<div class="mx-header compare-header">' +
    '<button class="back-link" onclick="closeParamMatrix()">&larr; Back</button>' +
    '<h3>Parameter Matrix</h3>' +
    '<p class="mx-subtitle">These runs read as one parameter search: what varied, ' +
    'what each value was worth, and which run won.</p>' +
    '</div><div id="matrix-body">' + inner + '</div>';
}

function setMatrixRankBy(v) {
  _matrixRankBy = v === 'best' ? 'best' : 'final';
  _storageSet('exptrack-matrix-rank-by', _matrixRankBy);
  // Both numbers are already on every row, so the table's switch is a
  // re-render, not another request. The ranked sections below it are ordered
  // server-side, so those do have to re-ask — otherwise "top runs" would keep
  // showing the previous basis under the new label.
  if (_matrixData) { _matrixData.rank_by = _matrixRankBy; renderParamMatrix(); }
  _reloadOpenMxSections();
}

function setMatrixIncludeRunning(on) {
  _matrixIncludeRunning = !!on;
  _storageSet('exptrack-matrix-running', _matrixIncludeRunning ? '1' : '0');
  loadParamMatrix();
}

function setMatrixIncludeFailed(on) {
  _matrixIncludeFailed = !!on;
  _storageSet('exptrack-matrix-failed', _matrixIncludeFailed ? '1' : '0');
  loadParamMatrix();
}

// The best row for the current basis. The server ranks both bases and ships
// both ids, so switching is a lookup rather than a second implementation of
// the ranking rule — a tie-break that disagreed across the two languages would
// put the "best" badge, the one claim that must not be wrong, on two different
// runs depending on which side computed it.
function _bestRowId() {
  if (!_matrixData) return null;
  return _matrixRankBy === 'best'
    ? _matrixData.best_row_id_best : _matrixData.best_row_id_final;
}

function _rowRankValue(row) {
  const p = row.primary || {};
  return _matrixRankBy === 'best' ? p.best : p.final;
}

function setMatrixSort(col) {
  if (_matrixSort && _matrixSort.col === col) _matrixSort.dir *= -1;
  else _matrixSort = {col: col, dir: col === 'metric' ? -1 : 1};
  renderParamMatrix();
}

function _matrixSortedRows() {
  const rows = (_matrixData.rows || []).slice();
  if (!_matrixSort) return rows;
  const {col, dir} = _matrixSort;
  const valueOf = (r) => {
    if (col === 'metric') return _rowRankValue(r);
    if (col === 'name') return String(r.name || '').toLowerCase();
    if (col === 'started') return r.created_at || '';
    if (col === 'status') return String(r.status || '');
    if (col.startsWith('param:')) {
      const k = col.slice(6);
      return Object.prototype.hasOwnProperty.call(r.params, k) ? r.params[k] : undefined;
    }
    return undefined;
  };
  rows.sort((a, b) => {
    let va = valueOf(a), vb = valueOf(b);
    const ma = va === undefined || va === null, mb = vb === undefined || vb === null;
    // Numeric when both sides are numbers, else text — then the shared rule
    // pins missing values to the bottom in both directions (_cmpMissingLast in
    // table.js), so the matrix and the experiment list order identical data
    // identically.
    const na = Number(va), nb = Number(vb);
    if (!ma && !mb && !isNaN(na) && !isNaN(nb) && va !== '' && vb !== '') {
      va = na; vb = nb;
    } else {
      va = String(va).toLowerCase(); vb = String(vb).toLowerCase();
    }
    return _cmpMissingLast(va, vb, ma, mb, dir);
  });
  return rows;
}

function renderParamMatrix() {
  const container = document.getElementById('matrix-view');
  if (!container || !_matrixData) return;
  const d = _matrixData;
  const cols = d.varying || [];
  const rows = _matrixSortedRows();

  if (!rows.length) {
    container.innerHTML = _matrixShell(
      _matrixControls() +
      '<div class="mx-empty">Every run in this set was filtered out.<br>' +
      '<span class="mx-empty-hint">' + _excludedText(d.excluded) + '</span></div>');
    return;
  }

  let html = _matrixControls() + _matrixSummaryHtml(d) + _matrixNotices(d);

  if (!cols.length) {
    html += '<div class="mx-note mx-note-flat">These ' + rows.length +
      ' runs share identical parameters — nothing varied across the set. ' +
      'Widen the filter, or check the duplicates below.</div>';
  }

  html += '<div class="mx-table-wrap"><table class="mx-table"><thead><tr>' +
    '<th class="mx-th-cb"></th>' +
    _th('name', 'Run') +
    _th('status', 'Status');
  cols.forEach(c => {
    html += '<th class="mx-th-param' + (_matrixSort && _matrixSort.col === 'param:' + c.key ? ' sorted' : '') +
      '" onclick="setMatrixSort(\'' + escJsAttr('param:' + c.key) + '\')" ' +
      'title="' + esc(c.n_values + ' distinct value(s)' +
        (c.n_missing ? ', ' + c.n_missing + ' run(s) without it' : '')) + '">' +
      esc(c.key) + '<span class="mx-th-n">' + c.n_values + '</span></th>';
  });
  html += _th('metric', _metricHeaderLabel(d)) + _th('started', 'Started') + '</tr></thead><tbody>';

  rows.forEach(r => {
    const isBest = r.id === _bestRowId();
    const cls = ['mx-row'];
    if (isBest) cls.push('mx-best');
    if (r.status === 'failed') cls.push('mx-failed');
    if (_matrixSelected.has(r.id)) cls.push('mx-selected');
    html += '<tr class="' + cls.join(' ') + '" data-id="' + esc(r.id) + '">' +
      '<td class="mx-td-cb"><input type="checkbox" ' +
        (_matrixSelected.has(r.id) ? 'checked ' : '') +
        'onchange="toggleMatrixSelect(\'' + escJsAttr(r.id) + '\')" ' +
        'aria-label="Select ' + esc(r.name) + ' for comparison"></td>' +
      '<td class="mx-td-name"><a href="#" onclick="openFromMatrix(\'' + escJsAttr(r.id) + '\');return false">' +
        esc(r.name) + '</a>' +
        (isBest ? '<span class="mx-badge mx-badge-best" title="Best ' +
          esc(_matrixRankBy) + ' value in this set">best</span>' : '') +
        _dupBadge(r) +
        '</td>' +
      '<td class="mx-td-status"><span class="mx-status mx-status-' + esc(r.status) + '">' +
        _statusGlyph(r.status) + esc(r.status) + '</span></td>';
    cols.forEach(c => { html += _paramTdHtml(r, c.key); });
    html += '<td class="mx-td-metric">' + _metricCell(r) + '</td>' +
      '<td class="mx-td-time">' + esc(fmtDt(r.created_at)) + '</td></tr>';
  });
  html += '</tbody></table></div>';
  // The inline comparison sits directly under the rows it was assembled from,
  // so the selection, the parameters and the numbers stay on screen together.
  // Empty and hidden until something is compared; the view is rebuilt from a
  // string, so an open panel is repainted below rather than assumed to survive.
  html += '<div id="mx-cmp-panel" class="mx-cmp-panel" style="display:none"></div>';
  // Ranking, progress and effects live below that: the same question at wider
  // zoom. All collapsed by default and fetched on open — each needs a second
  // pass over every run's metric points, and most visits want the table.
  html += _mxSectionsHtml();
  html += _constantSection(d.constant || []);

  container.innerHTML = _matrixShell(html);
  _renderMatrixBar();
  renderMatrixInlineCompare();
  _renderOpenMxSections();
}

function _th(col, label) {
  const sorted = _matrixSort && _matrixSort.col === col;
  const arrow = sorted ? (_matrixSort.dir > 0 ? ' ↑' : ' ↓') : '';
  return '<th class="mx-th' + (sorted ? ' sorted' : '') +
    '" onclick="setMatrixSort(\'' + escJsAttr(col) + '\')">' + esc(label) + arrow + '</th>';
}

// The column is the set's metric — the one the ranking uses (d.metric, the
// server's consensus) — not the first row's. With two notebook runs judged by
// `acc` listed first, the header read `acc (final)` over ten rows of
// train_loss values, and the best-row badge sat on a loss under an accuracy
// heading.
function _metricHeaderLabel(d) {
  const key = (d.metric || {}).key;
  if (!key) return 'Result';
  return key + ' (' + _matrixRankBy + ')';
}

function _matrixJudgedByHtml(d) {
  const key = (d.metric || {}).key;
  if (!key) return '';
  const src = d.metric_source || {};
  const guess = src.source === 'heuristic';
  return '<span class="mx-ctl-group"><label>Judged by</label>'
    + '<button class="select-sm mx-pm-btn' + (guess ? ' mx-pm-guess' : '') + '"'
    + ' onclick="openMatrixMetricPicker(this)" title="'
    + (guess ? 'Guessed — nothing is set. Click to choose the metric runs are judged by.'
             : 'Set for this ' + esc(src.source || 'project') + '. Click to change it.') + '">'
    + esc(key) + ' · ' + (d.goal === 'min' ? 'lower' : 'higher') + ' is better'
    + (guess ? ' <span class="primary-guess-tag">guessed</span>' : '') + ' ▾</button></span>';
}

function openMatrixMetricPicker(anchor) {
  const d = _matrixData || {};
  const keys = [].concat(...Object.values(d.metric_keys || {}));
  const src = d.metric_source || {};
  // A study level is offered when every analysed run shares that study.
  const rowsById = new Set((d.rows || []).map(r => r.id));
  const inSet = (allExperiments || []).filter(e => rowsById.has(e.id));
  const shared = inSet.length
    ? (inSet[0].studies || []).filter(s => inSet.every(e => (e.studies || []).includes(s))) : [];
  openPrimaryMetricPicker(anchor, {keys, studies: shared,
    current: {key: (d.metric || {}).key, goal: d.goal, source: src.source, study: src.study}});
}

// The metric cell states three different things and must not blur them: a real
// value, a metric that was configured but this run never logged, and a run
// with no metric at all.
function _metricCell(row) {
  const p = row.primary || {};
  if (!p.key) return '<span class="mx-missing" title="this run logged no metrics">—</span>';
  const setKey = ((_matrixData || {}).metric || {}).key;
  if (setKey && p.key !== setKey) {
    // Judged by another metric, so it is not in this ranking — say which,
    // rather than printing its number under a heading it does not measure.
    return '<span class="mx-missing mx-off-metric" title="' + esc('This run is judged by ' + p.key
      + ', not ' + setKey + ', so it is not ranked here') + '">by ' + esc(p.key) + '</span>';
  }
  if (p.missing) {
    return '<span class="mx-missing mx-metric-missing" title="' +
      esc(p.key + ' was never logged by this run') + '">not logged</span>';
  }
  const v = _rowRankValue(row);
  if (typeof v !== 'number') return '<span class="mx-missing">—</span>';
  let out = '<span class="mx-metric-val">' + esc(fmtMetricVal(v)) + '</span>';
  if (_matrixRankBy === 'best' && typeof p.best_step === 'number') {
    out += '<span class="mx-metric-step" title="step at which the best value occurred">@' +
      esc(String(p.best_step)) + '</span>';
  }
  if (p.source === 'heuristic') {
    out += '<span class="mx-guess" title="' + esc(
      'No primary metric is set, so ' + p.key + ' was guessed from this run’s metrics. ' +
      'Choose one with Judged by, above the table.') + '">?</span>';
  }
  return out;
}

// The three duplicate findings lead to different actions, so the badge names
// which one it is rather than flagging every repeat the same way. "Same params,
// different code" is the change-one-line loop working correctly — calling that
// a duplicate would be actively wrong.
const _DUP_LABELS = {
  script_differs: ['other model', 'Same parameters as another run, but a different script ran — two models, not a repeat'],
  identical:    ['rerun',    'Same parameters, code and data as another run in this set'],
  code_differs: ['recode',   'Same parameters as another run, but the code changed — a deliberate re-test, not waste'],
  dataset_differs: ['redata', 'Same parameters and code as another run, but the dataset changed'],
  params_only:  ['dup',      'Same parameters as another run; code or data was not captured for both, so nothing more can be claimed'],
};

function _dupBadge(row) {
  if (row.dup_group === null || row.dup_group === undefined) return '';
  const meta = _DUP_LABELS[row.dup_kind] || _DUP_LABELS.params_only;
  return '<span class="mx-badge mx-badge-dup mx-badge-' + esc(row.dup_kind || 'params_only') +
    '" title="' + esc(meta[1]) + '">' + esc(meta[0]) + '</span>';
}

function _statusGlyph(status) {
  // Status is carried by a glyph as well as colour, so it survives a
  // colour-blind reader and a greyscale screenshot.
  const g = {done: '✓', failed: '✕', running: '◍'}[status] || '·';
  return '<span class="mx-status-glyph" aria-hidden="true">' + g + '</span>';
}

// One param cell for every table in this view. The MISSING-vs-null distinction
// is load-bearing (a run that never had `dropout` is not a run that logged
// null), so it has exactly one implementation — three copies is how one of them
// degrades to a blank cell that reads as "not set" for both.
function _paramTdHtml(row, key) {
  const has = Object.prototype.hasOwnProperty.call(row.params || {}, key);
  return '<td class="mx-td-param' + (has ? '' : ' mx-td-missing') + '" title="' +
    esc(has ? key + ' = ' + _fmtParam(row.params[key])
            : 'this run never had ' + key) + '">' +
    (has ? esc(_fmtParam(row.params[key]))
         : '<span class="mx-missing" aria-label="not set">—</span>') + '</td>';
}

function _fmtParam(v) {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'number') return String(v);
  if (typeof v === 'object') { try { return JSON.stringify(v); } catch (e) { return String(v); } }
  return String(v);
}

function _matrixControls() {
  const d = _matrixData || {};
  return '<div class="mx-controls">' +
    '<span class="mx-ctl-group"><label for="mx-rank">Rank by</label>' +
    '<select id="mx-rank" class="select-sm" onchange="setMatrixRankBy(this.value)">' +
      '<option value="final"' + (_matrixRankBy === 'final' ? ' selected' : '') + '>final value</option>' +
      '<option value="best"' + (_matrixRankBy === 'best' ? ' selected' : '') + '>best value</option>' +
    '</select></span>' +
    '<span class="mx-ctl-group"><label><input type="checkbox"' +
      (_matrixIncludeFailed ? ' checked' : '') +
      ' onchange="setMatrixIncludeFailed(this.checked)"> Show failed</label></span>' +
    '<span class="mx-ctl-group"><label><input type="checkbox"' +
      (_matrixIncludeRunning ? ' checked' : '') +
      ' onchange="setMatrixIncludeRunning(this.checked)"> Show running</label></span>' +
    _matrixJudgedByHtml(d) +
    '<span class="mx-ctl-group">' + _matrixSetControls() + '</span>' +
    '<span class="mx-ctl-spacer"></span>' +
    '<span class="mx-count">' + (d.n_runs || 0) + ' runs · ' +
      ((d.varying || []).length) + ' varying</span>' +
    '</div>';
}

// Which runs are being analysed, and how to change it. The set is stated
// because it decides the answer: "what varied" is a property of the set on
// screen, so a chosen set that read like the whole project would misreport it.
function _matrixSetControls() {
  const pick = '<button class="btn-sm" onclick="openMatrixRunPicker()" ' +
    'title="Search every run by name, id, parameter, status, script or date">' +
    'Choose runs&hellip;</button>';
  if (!_matrixIdSet) return '<span class="mx-set-note">from the current filter</span>' + pick;
  return '<span class="mx-set-note mx-set-chosen">' + _matrixIdSet.size +
    ' chosen runs</span>' + pick +
    '<button class="btn-sm btn-ghost" onclick="clearMatrixRunChoice()">Use current filter</button>';
}

// ── What this view is telling you ────────────────────────────────────────────
// The matrix opens onto a wide table and four collapsible analyses, and it
// never said in words what any of it amounted to — so the first job on arrival
// was to read a grid and work out which columns mattered and which row won. The
// answer is one sentence, and every fact in it is already in the payload.
//
// It leads with what varied because that is the question the view exists to
// answer, and it names the winning run because "which one won" is the second
// thing asked and was previously carried only by a badge halfway down a column.
function _matrixSummaryHtml(d) {
  const varying = d.varying || [];
  const rows = d.rows || [];
  const bits = [];
  bits.push('<strong>' + rows.length + ' run' + (rows.length === 1 ? '' : 's') + '</strong>');
  if (varying.length) {
    const names = varying.map(c => '<code>' + esc(c.key) + '</code>').join(', ');
    bits.push(names + ' varied');
  } else {
    bits.push('every parameter identical');
  }
  const best = rows.find(r => r.id === _bestRowId());
  if (best) {
    const p = best.primary || {};
    const v = _rowRankValue(best);
    if (p.key && typeof v === 'number') {
      bits.push('best <code>' + esc(p.key) + '</code> ' + esc(fmtMetricVal(v)) +
        ' from <a href="#" onclick="openFromMatrix(\'' + escJsAttr(best.id) +
        '\');return false">' + esc(midEllipsis(best.name, 34)) + '</a>');
    }
  }
  const dupes = (d.duplicates || []).length;
  if (dupes) {
    bits.push(dupes + ' repeated configuration' + (dupes === 1 ? '' : 's'));
  }
  return '<p class="mx-summary">' + bits.join(' &middot; ') + '</p>' +
    '<p class="mx-summary-hint">' + (_matrixSelected.size
      ? _matrixSelected.size + ' run' + (_matrixSelected.size === 1 ? '' : 's') +
        ' ticked — <strong>Compare n here</strong> puts their settings and numbers ' +
        'side by side below, without leaving this view.'
      : 'Tick two or more rows to compare them. The sections below the table ' +
        'rank the set, trace whether the search is still paying, and summarize ' +
        'what each value was worth — all closed until you open one.') +
    '</p>';
}

function _matrixNotices(d) {
  let out = '';
  const ex = _excludedText(d.excluded);
  if (ex) out += '<div class="mx-note">' + esc(ex) + '</div>';
  if (d.unknown_ids && d.unknown_ids.length) {
    out += '<div class="mx-note mx-note-warn">' + d.unknown_ids.length +
      ' selected run(s) could not be found and are not in this analysis.</div>';
  }
  const dupes = d.duplicates || [];
  if (dupes.length) {
    // Counted by finding, not lumped together: an identical rerun is wasted
    // compute, a code-differs group is the point of the loop, and a
    // dataset-differs group silently invalidates a comparison.
    const byKind = {};
    dupes.forEach(g => { byKind[g.kind] = (byKind[g.kind] || 0) + 1; });
    const parts = Object.keys(byKind).map(k => {
      const meta = _DUP_LABELS[k] || _DUP_LABELS.params_only;
      return byKind[k] + ' × <span class="mx-badge mx-badge-dup mx-badge-' + esc(k) +
        '" title="' + esc(meta[1]) + '">' + esc(meta[0]) + '</span>';
    });
    out += '<div class="mx-note mx-note-dup">Repeated configurations: ' +
      parts.join(' · ') + '</div>';
  }
  return out;
}

function _excludedText(excluded) {
  const ex = excluded || {};
  const parts = [];
  if (ex.running) parts.push(ex.running + ' still running');
  if (ex.failed) parts.push(ex.failed + ' failed');
  if (ex.trashed_or_missing) parts.push(ex.trashed_or_missing + ' trashed or missing');
  if (!parts.length) return '';
  return 'Hidden from this analysis: ' + parts.join(', ') + '.';
}

function _constantSection(constant) {
  if (!constant.length) return '';
  const rows = constant.map(c => {
    const v = (c.values || [])[0] || {};
    const shown = v.missing ? '—' : _fmtParam(v.value);
    return '<div class="mx-const-item"><span class="mx-const-key">' + esc(c.key) +
      '</span><span class="mx-const-val">' + esc(shown) + '</span></div>';
  }).join('');
  return '<details class="mx-constants"><summary>Held constant across these runs (' +
    constant.length + ')</summary><div class="mx-const-grid">' + rows + '</div></details>';
}

// ── Selection → compare ──────────────────────────────────────────────────────

function toggleMatrixSelect(id) {
  if (_matrixSelected.has(id)) _matrixSelected.delete(id);
  else _matrixSelected.add(id);
  // Re-render only the row's class and the bar, not the table: rebuilding the
  // table on every checkbox would lose the scroll position mid-selection.
  const tr = document.querySelector('#matrix-view tr[data-id="' + CSS.escape(id) + '"]');
  if (tr) tr.classList.toggle('mx-selected', _matrixSelected.has(id));
  _renderMatrixBar();
  // Ticking a row is also how you find that run on the charts below.
  _refreshEffectHighlights();
}

function clearMatrixSelection() {
  _matrixSelected.clear();
  renderParamMatrix();
}

function _renderMatrixBar() {
  let bar = document.getElementById('matrix-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'matrix-bar';
    document.body.appendChild(bar);
  }
  const n = _matrixSelected.size;
  if (!n) { bar.style.display = 'none'; return; }
  bar.style.display = '';
  const few = n < 2 ? ' disabled title="Select at least two runs"' : '';
  bar.innerHTML = '<span class="mx-bar-count">' + n + ' selected</span>' +
    '<button class="btn-sm" onclick="compareMatrixInline()"' + few +
      '>Compare ' + n + ' here</button>' +
    '<button class="btn-sm" onclick="compareMatrixSelection()"' + few +
      ' title="Open the full Compare view — training curves, bar charts and images">' +
      'Open in Compare</button>' +
    '<button class="btn-sm btn-ghost" onclick="clearMatrixSelection()">Clear</button>';
}

function compareMatrixSelection() {
  const ids = Array.from(_matrixSelected);
  if (ids.length < 2) return;
  // Hand off to the existing Compare flow rather than growing a second one: it
  // routes two runs to the pair view and three or more to the aggregate multi
  // view. The ids go as an argument — see compareRuns for why — so nothing
  // outside the matrix moves because of these picks; and that flow raises the
  // Compare view itself, which puts this one down. `origin` is what it takes to
  // get back here afterwards.
  compareRuns(ids, 'matrix');
}

// ── Comparing without leaving the view ───────────────────────────────────────
// Comparing from the matrix used to be a one-way trip: it raised the full
// Compare view, which put the matrix down, and Compare's only way back was
// "Back to experiments" — so answering "what do these four actually differ by"
// cost you the table you had assembled them in, and there was no way to hold
// the comparison and the matrix on screen together. The full view is still
// there (it owns the curves, the bar charts and the images); this renders the
// two tables that answer most of the question directly under the matrix rows,
// so the runs, their parameters and their numbers stay visible at once.
let _mxCmpData = null;
let _mxCmpToken = 0;

function _mxCmpHost() { return document.getElementById('mx-cmp-panel'); }

async function compareMatrixInline() {
  const ids = Array.from(_matrixSelected);
  if (ids.length < 2) return;
  const token = ++_mxCmpToken;
  const host = _mxCmpHost();
  if (host) {
    host.style.display = '';
    host.innerHTML = '<div class="mx-empty">Comparing ' + ids.length + ' runs…</div>';
    host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  }
  const data = await postApi('/api/multi-compare',
                             {ids: ids, rank_by: _matrixRankBy === 'best' ? 'best' : 'final',
                              metric_goals: metricPolarityGoals()});
  // Same staleness guard both Compare surfaces carry: two quick comparisons
  // interleave and the older answer can land last.
  if (token !== _mxCmpToken) return;
  if (!data || data.error || !data.experiments || !data.experiments.length) {
    if (host) {
      host.innerHTML = '<div class="mx-note mx-note-warn">Could not compare these runs' +
        (data && data.error ? ' — ' + esc(String(data.error)) : '') + '.</div>';
    }
    return;
  }
  _mxCmpData = {data: data, ids: ids};
  renderMatrixInlineCompare();
}

function renderMatrixInlineCompare() {
  const host = _mxCmpHost();
  if (!host || !_mxCmpData) return;
  const {data, ids} = _mxCmpData;
  const exps = data.experiments;
  const keys = [...new Set(exps.flatMap(e => Object.keys(e.metrics || {})))].sort();
  // Comparing four runs and rendering three, with nothing saying so, is the
  // dishonesty every other compare surface here already refuses.
  const missing = ids.length - exps.length;
  host.style.display = '';
  host.innerHTML = '<div class="mx-cmp-head">' +
      '<span class="mx-cmp-title">Comparing ' + exps.length + ' selected runs</span>' +
      '<span class="mx-cmp-basis">' +
        esc(data.rank_by === 'best' ? 'best value' : 'final value') + ' · ' +
        '<span class="cmp-best-max">best</span> / <span class="cmp-best-min">worst</span> per row</span>' +
      '<span class="mx-ctl-spacer"></span>' +
      '<button class="btn-sm" onclick="compareMatrixSelection()" ' +
        'title="Training curves, bar charts and images">Open in Compare</button>' +
      '<button class="btn-sm btn-ghost" onclick="closeMatrixInlineCompare()">Close</button>' +
    '</div>' +
    (missing > 0
      ? '<p class="cmp-missing">' + missing + ' of the selected runs could not be found.</p>' : '') +
    _multiConfigTable(exps, data.varying_params) +
    (keys.length
      ? _multiMetricTableHtml(exps, keys)
      : '<p class="cmp-trunc-note">None of these runs logged a metric.</p>');
}

function closeMatrixInlineCompare() {
  _mxCmpData = null;
  _mxCmpToken++;      // any comparison still in flight is no longer wanted
  const host = _mxCmpHost();
  if (host) { host.innerHTML = ''; host.style.display = 'none'; }
}

function openFromMatrix(id) {
  showDetail(id);
}

// ── Lazy sections below the matrix ───────────────────────────────────────────
// Top runs, the best-so-far curve and the per-parameter effects are all the
// same shape: collapsed by default, fetched on open, re-rendered whenever the
// matrix rebuilds. Each needs a second server pass over every run's metric
// points, and most visits to this view want the table — so none of them is
// fetched until it is opened.
//
// One definition of that shape rather than three copies of it. The three
// differ only in their endpoint, their extra request fields, how they render,
// and whether they own Chart.js instances that must be destroyed on close.

// One structure, keyed by id: the definition and the live state (`open`
// survives a matrix rebuild, `data` is what a re-render repaints from without
// another request) on the same object. Two parallel maps keyed identically
// meant every handler did two lookups for one section, and the state map
// silently invented entries for ids the definitions didn't have.
//
// `rankDependent` marks the sections the server orders by the rank basis.
// Effects is not one of them — parameter_effects always scores on the final
// value — so a basis switch must not re-request it for byte-identical data.
// Order is reading order, and the most useful section leads. "Which values
// worked best" answers the question a sweep was run to answer — the others
// rank, trace and trade off *runs*, which is only useful once you know which
// settings are worth running. It was last.
//
// The labels are questions rather than nouns. "What each value was worth" and
// "Progress over the search" name a topic and leave the reader to guess what
// opening them will tell them, which is how four collapsed sections became
// four things to open rather than one to choose.
const MX_SECTIONS = {
  effects: {id: 'effects', label: 'Parameter effects',
            desc: 'what each parameter was set to, and how the runs at each value scored',
            path: '/api/param-effects', loading: 'Summarizing…',
            fail: 'Could not summarize these runs.',
            body: () => ({group_by: _effectsGroupBy}),
            render: () => renderParamEffects(),
            destroy: () => _destroyEffectCharts()},
  top: {id: 'top', label: 'Leaderboard', path: '/api/top-runs',
        desc: 'the best runs by the primary metric, with their settings',
        loading: 'Ranking…', fail: 'Could not rank these runs.',
        rankDependent: true,
        body: () => ({limit: _topLimit}), render: () => renderTopRuns()},
  progress: {id: 'progress', label: 'Search progress',
             desc: 'whether the best result is still improving, run by run',
             path: '/api/best-so-far', loading: 'Tracing the record…',
             fail: 'Could not trace these runs.', rankDependent: true,
             render: () => renderBestSoFar(), destroy: () => _destroyProgressChart()},
  pareto: {id: 'pareto', label: 'Metric trade-offs', path: '/api/pareto',
           desc: 'runs not beaten on both of two metrics you choose',
           loading: 'Finding the frontier…', fail: 'Could not compare these runs.',
           rankDependent: true,
           body: () => ({x: _paretoX, y: _paretoY,
                         x_goal: _paretoGoals.x || '', y_goal: _paretoGoals.y || ''}),
           render: () => renderPareto(), destroy: () => _destroyParetoChart()},
};

function _mxSection(id) { return MX_SECTIONS[id]; }

function _mxSectionHost(id) { return document.getElementById('mx-sec-' + id); }

// One definition of each toggle's label and state, used by the initial render
// and by the toggle itself — the label text was previously spelled twice.
function _mxSectionToggleHtml(sec) {
  // The one-line description is on the *closed* toggle on purpose: four
  // sections named "Progress over the search" and "What each value was worth"
  // are only openable by guessing, and guessing four times is how this view
  // became a wall of tables to read rather than four questions to choose from.
  return '<button class="mx-fx-toggle" id="mx-tog-' + esc(sec.id) + '" ' +
    'onclick="toggleMxSection(\'' + escJsAttr(sec.id) + '\')" ' +
    'aria-expanded="' + (sec.open ? 'true' : 'false') + '">' +
    '<span class="mx-fx-caret">' + (sec.open ? '▾' : '▸') + '</span>' +
    '<span class="mx-fx-name">' + esc(sec.label) + '</span>' +
    (sec.desc ? '<span class="mx-fx-desc">' + esc(sec.desc) + '</span>' : '') +
    '</button>';
}

function _mxSectionsHtml() {
  return Object.values(MX_SECTIONS).map(sec =>
    '<div class="mx-fx-section">' + _mxSectionToggleHtml(sec) +
    '<div id="mx-sec-' + esc(sec.id) + '"' +
    (sec.open ? '' : ' style="display:none"') + '></div></div>'
  ).join('');
}

function toggleMxSection(id) {
  const sec = _mxSection(id);
  if (!sec) return;
  sec.open = !sec.open;
  const host = _mxSectionHost(id);
  if (host) host.style.display = sec.open ? '' : 'none';
  if (sec.open) loadMxSection(id);
  else if (sec.destroy) sec.destroy();
  const btn = document.getElementById('mx-tog-' + id);
  if (btn) btn.outerHTML = _mxSectionToggleHtml(sec);
}

async function loadMxSection(id) {
  const sec = _mxSection(id);
  if (!sec) return;
  const host = _mxSectionHost(id);
  if (host) host.innerHTML = '<div class="mx-empty">' + esc(sec.loading) + '</div>';
  const data = await postApi(sec.path, Object.assign({
    ids: _matrixIds(),
    rank_by: _matrixRankBy,
    include_running: _matrixIncludeRunning,
    include_failed: _matrixIncludeFailed,
  }, sec.body ? sec.body() : {}));
  if (!data || data.error) {
    if (host) host.innerHTML = '<div class="mx-empty">' +
      esc((data && data.error) || sec.fail) + '</div>';
    return;
  }
  sec.data = data;
  sec.render();
}

// Repaint every open section from data it already has. The matrix view is
// rebuilt from a string, so an open section (and its canvases) has to be
// redrawn rather than assumed to survive.
function _renderOpenMxSections() {
  Object.values(MX_SECTIONS).forEach(sec => {
    if (sec.open && sec.data) sec.render();
  });
}

// The ranking basis is a property of the whole view, so the sections ordered
// by it have to re-ask — both numbers are on every matrix row, but these are
// ranked server-side and need the real answer, not a re-sort here. Sections
// that don't read the basis are skipped: each request re-runs the whole matrix
// build server-side, so re-fetching one for data that cannot have changed is a
// full param load and analysis pass thrown away on a click that reorders a table.
function _reloadOpenMxSections() {
  Object.values(MX_SECTIONS).forEach(sec => {
    if (sec.open && sec.rankDependent) loadMxSection(sec.id);
  });
}

// ── Top runs ─────────────────────────────────────────────────────────────────
// The matrix marks the best row; this answers "what are my best five, and what
// did they have in common", which otherwise means sorting and counting by eye.

let _topLimit = parseInt(_storageGet('exptrack-top-limit'), 10) || 5;

function setTopLimit(n) {
  _topLimit = Math.max(1, parseInt(n, 10) || 5);
  _storageSet('exptrack-top-limit', String(_topLimit));
  loadMxSection('top');
}

function renderTopRuns() {
  const host = _mxSectionHost('top');
  const d = MX_SECTIONS.top.data;
  if (!host || !d) return;
  if (!d.metric || !d.metric.key) { host.innerHTML = _noMetricNote(); return; }

  const lower = d.metric.goal === 'min';
  let html = '<div class="mx-fx-head"><span class="mx-fx-caption">' +
    'Ranked by <strong>' + esc(d.metric.key) + '</strong> (' + esc(d.rank_by) +
    '), ' + (lower ? 'lower' : 'higher') + ' is better. ' +
    d.n_scored + ' of ' + d.n_runs + ' runs produced a value.' +
    '</span><span class="mx-ctl-group"><label for="mx-top-n">Show</label>' +
    '<select id="mx-top-n" class="select-sm" onchange="setTopLimit(this.value)">' +
    [3, 5, 10, 25].map(n => '<option value="' + n + '"' +
      (n === d.limit ? ' selected' : '') + '>' + n + '</option>').join('') +
    '</select></span></div>';

  if (!d.runs.length) {
    html += '<div class="mx-note">No run in this set produced a value for ' +
      esc(d.metric.key) + '.</div>';
    host.innerHTML = html;
    return;
  }

  const cols = (d.varying || []).map(c => c.key);
  html += '<div class="mx-table-wrap"><table class="mx-table mx-top-table"><thead><tr>' +
    '<th class="mx-th">#</th><th class="mx-th">Run</th>' +
    cols.map(k => '<th class="mx-th-param">' + esc(k) + '</th>').join('') +
    '<th class="mx-th">' + esc(d.metric.key) + '</th>' +
    '<th class="mx-th" title="difference from the leading run">vs #1</th>' +
    '</tr></thead><tbody>';
  d.runs.forEach(r => {
    html += '<tr class="mx-row' + (r.rank === 1 ? ' mx-best' : '') + '">' +
      '<td class="mx-td-rank">' + r.rank + '</td>' +
      '<td class="mx-td-name"><a href="#" onclick="openFromMatrix(\'' +
        escJsAttr(r.id) + '\');return false">' + esc(r.name) + '</a>' +
        (r.status === 'failed'
          ? '<span class="mx-badge mx-badge-failed" title="this run failed — its value is wherever it stopped">failed</span>'
          : '') + '</td>' +
      cols.map(k => _paramTdHtml(r, k)).join('') +
      '<td class="mx-td-metric"><span class="mx-metric-val">' +
        esc(fmtMetricVal(r.value)) + '</span></td>' +
      '<td class="mx-td-delta">' + (r.rank === 1 ? '<span class="mx-missing">—</span>'
        : '<span class="mx-top-delta">' + esc(_fmtSignedDelta(r.delta_from_best)) +
          '</span>') + '</td></tr>';
  });
  html += '</tbody></table></div>';

  // Never let a short list read as "these are all the runs". The two reasons a
  // run is absent are counted apart: "logged nothing" and "measures something
  // else" call for different responses.
  const silent = d.unscored.filter(r => !r.off_metric).length;
  if (silent) {
    html += '<div class="mx-note mx-note-flat">' + silent + ' run' +
      (silent === 1 ? '' : 's') + ' in this set produced no value for ' +
      esc(d.metric.key) + ' and cannot be ranked.</div>';
  }
  if (d.off_metric_runs) {
    html += '<div class="mx-note mx-note-flat">' + d.off_metric_runs + ' run' +
      (d.off_metric_runs === 1 ? ' is' : 's are') + ' judged by a different metric, ' +
      'so ranking ' + (d.off_metric_runs === 1 ? 'it' : 'them') +
      ' here would compare numbers that do not measure the same thing.</div>';
  }
  host.innerHTML = html;
}

// fmtDeltaNum already signs the value and already drops to exponential below
// 1e-4 ("never round a real move to zero"); this only adds the plain "0" case,
// so the two can't disagree on precision or on the sign.
function _fmtSignedDelta(v) {
  if (typeof v !== 'number' || !isFinite(v) || v === 0) return '0';
  return fmtDeltaNum(v);
}

function _noMetricNote(verb) {
  return '<div class="mx-note">No primary metric resolved for these runs, ' +
    'so there is nothing to ' + (verb || 'rank') + ' against. Set one with ' +
    '<code>exptrack primary-metric &lt;key&gt;</code>.</div>';
}

// ── Progress over the search ─────────────────────────────────────────────────
// The record against launch order. A table cannot show whether the search is
// still paying; a curve that stepped up three times early and has been flat for
// forty runs says the useful move is to change what is being varied.

let _progressChart = null;

function _destroyProgressChart() {
  if (_progressChart) { try { _progressChart.destroy(); } catch (e) { /* gone */ } }
  _progressChart = null;
}

function renderBestSoFar() {
  const host = _mxSectionHost('progress');
  const d = MX_SECTIONS.progress.data;
  if (!host || !d) return;
  _destroyProgressChart();
  if (!d.metric || !d.metric.key) { host.innerHTML = _noMetricNote(); return; }

  const improvements = d.improvements.length;
  let html = '<div class="mx-fx-head"><span class="mx-fx-caption">' +
    'Best <strong>' + esc(d.metric.key) + '</strong> (' + esc(d.rank_by) +
    ') seen after each run, in launch order. ' +
    improvements + ' improvement' + (improvements === 1 ? '' : 's') +
    ' across ' + d.n_runs + ' runs.</span></div>';

  if (!d.n_scored) {
    html += '<div class="mx-note">No run in this set produced a value for ' +
      esc(d.metric.key) + ', so there is no record to trace.</div>';
    host.innerHTML = html;
    return;
  }

  // The number that says "stop". Stated plainly rather than left to be read
  // off the flat right-hand end of the line.
  if (typeof d.since_improvement === 'number') {
    const stalled = d.since_improvement >= 10;
    html += '<div class="mx-prog-stat' + (stalled ? ' mx-prog-stalled' : '') + '">' +
      (d.since_improvement === 0
        ? 'The most recent run set the record.'
        : d.since_improvement + ' run' + (d.since_improvement === 1 ? '' : 's') +
          ' since the record last moved' +
          (stalled ? ' — varying something else may pay more than more of the same.' : '.')) +
      '</div>';
  }

  html += '<div class="mx-prog-chart"><canvas id="mx-prog-canvas"></canvas></div>';

  html += '<div class="mx-prog-list"><div class="mx-prog-list-title">Runs that moved the record</div>';
  d.points.filter(p => p.improved).forEach(p => {
    html += '<div class="mx-prog-item">' +
      '<span class="mx-prog-idx">#' + (p.index + 1) + '</span>' +
      '<a href="#" onclick="openFromMatrix(\'' + escJsAttr(p.id) + '\');return false">' +
        esc(p.name) + '</a>' +
      '<span class="mx-prog-val">' + esc(fmtMetricVal(p.value)) + '</span>' +
      '<span class="mx-prog-changed">' + _progressChangedHtml(p.changed) + '</span>' +
      '</div>';
  });
  html += '</div>';

  host.innerHTML = html;
  _drawProgressChart(d);
}

function _progressChangedHtml(changed) {
  const keys = Object.keys(changed || {});
  if (!keys.length) return '<span class="mx-prog-nochange">first result</span>';
  return keys.map(k => {
    const c = changed[k];
    const before = c.before_missing ? '—' : _fmtParam(c.before);
    const after = c.after_missing ? '—' : _fmtParam(c.after);
    return '<span class="mx-prog-chg">' + esc(k) + ' ' + esc(before) +
      ' → ' + esc(after) + '</span>';
  }).join('');
}

function _drawProgressChart(d) {
  const canvas = document.getElementById('mx-prog-canvas');
  if (!canvas || typeof Chart === 'undefined') return;
  const labels = d.points.map(p => p.index + 1);
  const accent = CHART_COLORS[0];

  _progressChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        // The record: a step line, because the best-so-far genuinely holds flat
        // between improvements — interpolating it would draw a climb that never
        // happened.
        {label: 'best so far', data: d.points.map(p => p.best_so_far),
         borderColor: accent, backgroundColor: accent, stepped: true,
         pointRadius: d.points.map(p => p.improved ? 4 : 0),
         borderWidth: 2, spanGaps: true, order: 1},
        // Each run's own value behind it, so the spread of what was tried stays
        // visible — a record line alone reads as steady progress.
        {label: 'each run', data: d.points.map(p => p.value),
         borderColor: 'transparent', backgroundColor: CHART_MUTED,
         pointRadius: 3, showLine: false, order: 2},
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: {mode: 'nearest', intersect: true},
      plugins: {
        legend: {display: true, labels: {boxWidth: 10, font: {size: 10}}},
        tooltip: {callbacks: {
          title: items => {
            const p = d.points[items[0].dataIndex];
            return p ? p.name : '';
          },
          label: ctx => {
            const p = d.points[ctx.dataIndex];
            if (ctx.datasetIndex === 1) {
              if (p && p.value === null) {
                return p.off_metric
                  ? 'judged by a different metric'
                  : 'no ' + d.metric.key + ' logged';
              }
              return d.metric.key + ' = ' + fmtMetricVal(ctx.parsed.y);
            }
            return 'best so far = ' + fmtMetricVal(ctx.parsed.y) +
              (p && p.improved ? '  (new record)' : '');
          },
        }},
      },
      scales: {
        x: {title: {display: true, text: 'run order', font: {size: 10}},
            ticks: {font: {size: 9}}},
        y: {title: {display: true, text: d.metric.key, font: {size: 10}},
            ticks: {font: {size: 9}}},
      },
    },
  });
}

// ── Trade-off between two metrics ────────────────────────────────────────────
// Ranking assumes one number. Real choices routinely have two that pull against
// each other, and no single ranking says "these are the runs where you cannot
// do better on one without giving up the other".
//
// This is a property of the runs that were launched, not of the parameter
// space: a run is on the frontier when nothing *in this set* beat it on both,
// which includes the case where it is the only run tried in that region. The
// caption says so, for the same reason the effects panel refuses to imply an
// effect it cannot support.

let _paretoX = '';
let _paretoY = '';
// Per-axis goal overrides. Empty means "use the name heuristic", which cannot
// read a key like `size_mb` — so the resolved direction is always shown and
// always switchable, since guessing it wrong inverts the entire frontier.
const _paretoGoals = {x: '', y: ''};
let _paretoChart = null;

function _destroyParetoChart() {
  if (_paretoChart) { try { _paretoChart.destroy(); } catch (e) { /* gone */ } }
  _paretoChart = null;
}

function setParetoAxis(which, key) {
  if (which === 'x') _paretoX = key || ''; else _paretoY = key || '';
  // A goal chosen for the previous metric means nothing for the new one.
  _paretoGoals[which] = '';
  loadMxSection('pareto');
}

function setParetoGoal(which, goal) {
  _paretoGoals[which] = goal || '';
  loadMxSection('pareto');
}

function _axisControls(which, d) {
  const axis = d[which] || {};
  const opts = (d.available_metrics || []).map(m =>
    '<option value="' + esc(m.key) + '"' + (m.key === axis.key ? ' selected' : '') +
    '>' + esc(m.key) + ' (' + m.n_runs + ')</option>').join('');
  return '<span class="mx-ctl-group"><label>' + which.toUpperCase() + '</label>' +
    '<select class="select-sm" onchange="setParetoAxis(\'' + which + '\', this.value)">' +
    '<option value="">—</option>' + opts + '</select>' +
    '<select class="select-sm" onchange="setParetoGoal(\'' + which + '\', this.value)" ' +
    'title="Which direction is better for this metric. Inferred from the name ' +
    'when it can be — get it wrong and the frontier inverts.">' +
    ['max', 'min'].map(g => '<option value="' + g + '"' +
      (g === axis.goal ? ' selected' : '') + '>' +
      (g === 'max' ? 'higher better' : 'lower better') + '</option>').join('') +
    '</select></span>';
}

function renderPareto() {
  const host = _mxSectionHost('pareto');
  const d = MX_SECTIONS.pareto.data;
  if (!host || !d) return;
  _destroyParetoChart();

  // With no axes chosen the payload still carries the pickable metrics, so the
  // empty state is a working chooser rather than a dead end.
  let html = '<div class="mx-fx-head"><span class="mx-fx-caption">' +
    'Runs that nothing else in this set beat on <em>both</em> metrics. ' +
    'This describes the runs you launched, not the parameter space — a run can ' +
    'sit on the frontier because it is the only one tried in that region.' +
    '</span>' + _axisControls('x', d) + _axisControls('y', d) + '</div>';

  if (!d.x.key || !d.y.key) {
    html += '<div class="mx-note">Pick two metrics to compare.' +
      ((d.available_metrics || []).length < 2
        ? ' These runs logged fewer than two distinct metrics, so there is no trade-off to plot.'
        : '') + '</div>';
    host.innerHTML = html;
    return;
  }
  if (d.x.key === d.y.key) {
    html += '<div class="mx-note">Pick two <em>different</em> metrics — a metric ' +
      'plotted against itself has no trade-off.</div>';
    host.innerHTML = html;
    return;
  }
  if (!d.n_placed) {
    html += '<div class="mx-note">No run in this set logged both ' +
      esc(d.x.key) + ' and ' + esc(d.y.key) + '.</div>';
    host.innerHTML = html;
    return;
  }

  html += '<div class="mx-prog-chart"><canvas id="mx-pareto-canvas"></canvas></div>';

  const front = d.points.filter(p => p.frontier);
  const cols = (d.varying || []).map(c => c.key);
  html += '<div class="mx-prog-list"><div class="mx-prog-list-title">On the frontier (' +
    front.length + ' of ' + d.n_placed + ')</div>';
  front.forEach(p => {
    html += '<div class="mx-prog-item">' +
      '<a href="#" onclick="openFromMatrix(\'' + escJsAttr(p.id) + '\');return false">' +
        esc(p.name) + '</a>' +
      '<span class="mx-prog-val">' + esc(d.x.key) + ' ' + esc(fmtMetricVal(p.x)) +
      '</span><span class="mx-prog-val">' + esc(d.y.key) + ' ' + esc(fmtMetricVal(p.y)) + '</span>' +
      '<span class="mx-prog-changed">' + cols.map(k =>
        Object.prototype.hasOwnProperty.call(p.params, k)
          ? '<span class="mx-prog-chg">' + esc(k) + ' ' + esc(_fmtParam(p.params[k])) + '</span>'
          : '').join('') + '</span></div>';
  });
  html += '</div>';

  // A run that logged only one of the two axes cannot be plotted at all, and an
  // absent point looks exactly like a point that was never measured.
  if (d.unplaced.length) {
    html += '<div class="mx-note mx-note-flat">' + d.unplaced.length + ' run' +
      (d.unplaced.length === 1 ? '' : 's') + ' could not be placed — ' +
      esc([...new Set(d.unplaced.flatMap(u => u.missing_metrics))].join(', ')) +
      ' not logged.</div>';
  }
  host.innerHTML = html;
  _drawParetoChart(d);
}

function _drawParetoChart(d) {
  const canvas = document.getElementById('mx-pareto-canvas');
  if (!canvas || typeof Chart === 'undefined') return;
  const front = d.points.filter(p => p.frontier);
  const rest = d.points.filter(p => !p.frontier);
  const accent = CHART_COLORS[0];
  const label = p => p.name;

  _paretoChart = new Chart(canvas.getContext('2d'), {
    type: 'scatter',
    data: {datasets: [
      // The frontier drawn as a connected line so the shape of the trade-off is
      // readable; the dominated runs stay visible behind it, because "how much
      // of the field is below the frontier" is most of what the plot says.
      {label: 'frontier', data: front.map(p => ({x: p.x, y: p.y, _p: p})),
       borderColor: accent, backgroundColor: accent, showLine: true,
       pointRadius: 5, borderWidth: 2, order: 1},
      {label: 'dominated', data: rest.map(p => ({x: p.x, y: p.y, _p: p})),
       backgroundColor: CHART_MUTED, borderColor: 'transparent',
       pointRadius: 3, showLine: false, order: 2},
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: {display: true, labels: {boxWidth: 10, font: {size: 10}}},
        tooltip: {callbacks: {
          title: items => label(items[0].raw._p),
          label: ctx => {
            const p = ctx.raw._p;
            const base = d.x.key + ' = ' + fmtMetricVal(p.x) + ', ' +
              d.y.key + ' = ' + fmtMetricVal(p.y);
            return p.frontier ? [base, 'nothing here beat it on both']
                              : [base, 'beaten on both by another run'];
          },
        }},
      },
      onClick: (ev, els) => {
        if (els.length) openFromMatrix(els[0].element.$context.raw._p.id);
      },
      scales: {
        x: {title: {display: true,
                    text: d.x.key + (d.x.goal === 'min' ? ' (lower better)' : ' (higher better)'),
                    font: {size: 10}}, ticks: {font: {size: 9}}},
        y: {title: {display: true,
                    text: d.y.key + (d.y.goal === 'min' ? ' (lower better)' : ' (higher better)'),
                    font: {size: 10}}, ticks: {font: {size: 9}}},
      },
    },
  });
}

// ── Parameter effects ────────────────────────────────────────────────────────
// Per varying parameter: what was tried, how many runs took each value, and how
// those runs scored. Rendered inline below the matrix because they answer the
// same question at a different zoom level — the columns say what each run had,
// this says what each value was worth.
//
// These are DESCRIPTIVE relationships. The runs were not randomized, the
// parameters were usually not varied independently, and the sample per value is
// typically a handful. Every affordance here is built to keep that visible:
// a perfectly confounded parameter is labelled rather than charted as an
// answer, and a parameter with one run per value says so instead of presenting
// a "median" of a single number.

let _effectsGroupBy = _storageGet('exptrack-effects-group-by') || '';
let _effectsCharts = [];

function _destroyEffectCharts() {
  _effectsCharts.forEach(c => { try { c.destroy(); } catch (e) { /* already gone */ } });
  _effectsCharts = [];
}

function setEffectsGroupBy(key) {
  _effectsGroupBy = key || '';
  _storageSet('exptrack-effects-group-by', _effectsGroupBy);
  // A repaint, not a request. This used to call `loadMxSection`, which blanks
  // the section to "Summarizing…", re-POSTs the whole analysis and rebuilds it
  // — so choosing a colour read as the page reloading, for a change that only
  // decides which points share a colour. The server now ships every grouping's
  // value per run (`run_groups`), so the answer is already here.
  if (MX_SECTIONS.effects.data) renderParamEffects();
}

function renderParamEffects() {
  const host = _mxSectionHost('effects');
  const d = MX_SECTIONS.effects.data;
  if (!host || !d) return;
  _destroyEffectCharts();

  if (!d.metric || !d.metric.key) { host.innerHTML = _noMetricNote('summarize'); return; }

  let html = '<div class="mx-fx-head">' +
    '<span class="mx-fx-caption">Observed association with <strong>' + esc(d.metric.key) +
      '</strong> across ' + d.n_scored + ' scored run' + (d.n_scored === 1 ? '' : 's') +
      '. Descriptive only — the runs were not randomized and parameters were not ' +
      'necessarily varied independently, so this is not a measure of importance.</span>';
  html += '<span class="mx-fx-hint">Tick runs in the table to light them up on ' +
    'every chart here; click a point to identify it.</span>';
  const groupable = (d.groupable || []).slice();
  if (groupable.length) {
    // Marked from `_effectsGroupBy`, the client's own state. Reading the
    // server's echo is what left the control unable to show its value when a
    // payload omitted the key — and the choice is no longer the server's to
    // report, since regrouping never reaches it.
    html += '<span class="mx-ctl-group"><label for="mx-fx-group">Colour by</label>' +
      '<select id="mx-fx-group" class="select-sm" onchange="setEffectsGroupBy(this.value)">' +
      '<option value=""' + (_effectsGroupBy ? '' : ' selected') + '>—</option>' +
      // Each entry carries its own display name — `_script` and `_run` are
      // pseudo-keys (by *model*, which is what a mixed-script set wants, and
      // one colour per run) and the server names them.
      (groupable.map(g => '<option value="' + esc(g.key) + '"' +
        (g.key === _effectsGroupBy ? ' selected' : '') + '>' +
        esc(g.label || g.key) + '</option>').join('')) +
      '</select></span>';
  }
  html += '</div>';
  html += _effectsGroupNoteHtml(d);

  // Side by side rather than one per full page width: each panel is a small
  // chart and a four-row table, and stacking them at 1900px wide meant a screen
  // of whitespace per parameter and a lot of scrolling to compare two of them —
  // which is the comparison the section is for.
  html += '<div class="mx-fx-grid">';
  (d.params || []).forEach((p, i) => { html += _effectPanel(p, d, i); });
  html += '</div>';
  host.innerHTML = html;
  (d.params || []).forEach((p, i) => _drawEffectChart(p, d, i));
}

// ── Identifying a point without leaving the view ─────────────────────────────
// Clicking a dot opened that run's detail page, which put the whole analysis
// down: the one gesture for "which run is this?" cost the comparison it was
// asked from, and getting back meant reopening Analyze and rebuilding the set.
// The question a dot raises is *identity*, not "show me everything about this
// run" — so the click answers it in place, in a card under the chart, and
// offers the navigation as one of three things you might then want.
//
// The hover tooltip carries the name too. A tooltip that reads
// `lr=0.01  loss=1.8298` describes a point that is already plotted at those
// coordinates and never says whose it is.
let _fxPicked = null;      // {key, id} — the point identified, per parameter panel

// ── Finding a run on the charts ──────────────────────────────────────────────
// Hover answers "which run is this point?", and it is the only direction that
// worked. The reverse — "where is *this run* on these charts?" — had no gesture
// at all, and hover is a poor substitute for it: the points of a sweep overlap
// (four runs at one `lr` land within a few pixels), so finding one specific run
// meant hovering each of them in turn and reading a long auto-generated name off
// a tooltip that changes as the cursor moves.
//
// So the *selection* drives a highlight. Ticking a run in the table — the
// gesture that already exists, and the one the compare actions read — lights
// its point up in every parameter panel at once, which also answers the
// question the panels are laid side by side to ask: this run is best on `lr`,
// so where does it sit on `epochs`? The point identified by a click joins the
// same set, so clicking a dot in one panel shows you the same run in all of
// them.
//
// With nothing selected, nothing is dimmed: a highlight that is always on is a
// filter, and this view already has one.
const FX_POINT_R = 5;
const FX_POINT_R_HI = 9;
const FX_POINT_R_DIM = 4;

function _fxHighlightSet() {
  const hi = new Set(_matrixSelected);
  if (_fxPicked) hi.add(_fxPicked.id);
  return hi;
}

// Per-point style arrays for one run dataset. Chart.js takes an array in place
// of a scalar for each of these, so a highlight is a data update rather than a
// second dataset that would need its own legend entry and its own click target.
function _fxPointStyle(ds, hi, base) {
  const on = pt => hi.has(pt._id);
  ds.pointRadius = ds.data.map(pt => hi.size ? (on(pt) ? FX_POINT_R_HI : FX_POINT_R_DIM)
                                             : FX_POINT_R);
  ds.pointHoverRadius = ds.pointRadius.map(r => r + 3);
  ds.backgroundColor = ds.data.map(pt => (!hi.size || on(pt)) ? base : CHART_MUTED);
  ds.borderColor = ds.data.map(pt => (hi.size && on(pt)) ? 'rgba(255,255,255,0.9)' : 'transparent');
  ds.borderWidth = ds.data.map(pt => (hi.size && on(pt)) ? 2 : 0);
}

// Repaint the highlight on every open effect chart without rebuilding them:
// these are live Chart.js instances, and re-rendering the section to move a
// highlight would destroy and recreate every one.
function _refreshEffectHighlights() {
  const hi = _fxHighlightSet();
  _effectsCharts.forEach(ch => {
    (ch.data.datasets || []).forEach(ds => {
      if (!ds._runsBase) return;
      _fxPointStyle(ds, hi, ds._runsBase);
    });
    try { ch.update('none'); } catch (e) { void e; }
  });
}


function _matrixRunById(id) {
  return ((_matrixData || {}).rows || []).find(r => r.id === id) || null;
}

function _fxRunName(id) {
  const r = _matrixRunById(id);
  return (r && r.name) || String(id).slice(0, 8);
}

function pickEffectPoint(key, id) {
  _fxPicked = (_fxPicked && _fxPicked.id === id && _fxPicked.key === key)
    ? null : {key: key, id: id};
  _renderEffectPick(key);
  _refreshEffectHighlights();
}

function closeEffectPick(key) {
  _fxPicked = null;
  _renderEffectPick(key);
  _refreshEffectHighlights();
}

// Repainting only this panel's card, never the section: the charts are live
// Chart.js instances and rebuilding the section's HTML would destroy and
// recreate every one of them to fill in a card underneath one.
function _renderEffectPick(key) {
  document.querySelectorAll('.mx-fx-pick').forEach(el => {
    if (el.dataset.key === key) el.innerHTML = _effectPickHtml(key);
    else if (el.innerHTML) el.innerHTML = '';
  });
}

function _effectPickHtml(key) {
  if (!_fxPicked || _fxPicked.key !== key) return '';
  const id = _fxPicked.id;
  const row = _matrixRunById(id);
  const d = _matrixData || {};
  const cols = (d.varying || []).map(c => c.key);
  const chips = row
    ? cols.filter(k => Object.prototype.hasOwnProperty.call(row.params || {}, k))
          .map(k => '<span class="mx-fx-pick-chip">' + esc(k) + '=' +
                    esc(_fmtParam(row.params[k])) + '</span>').join('')
    : '';
  const metric = row ? _metricCell(row) : '';
  const picked = _matrixSelected.has(id);
  return '<div class="mx-fx-pick-card">' +
    '<div class="mx-fx-pick-head">' +
      '<span class="mx-fx-pick-name">' + esc(_fxRunName(id)) + '</span>' +
      '<span class="mx-fx-pick-id">' + esc(String(id).slice(0, 8)) + '</span>' +
      '<span class="mx-ctl-spacer"></span>' +
      '<button class="btn-sm btn-ghost" onclick="closeEffectPick(\'' +
        escJsAttr(key) + '\')" title="Close">&times;</button>' +
    '</div>' +
    (chips ? '<div class="mx-fx-pick-params">' + chips + '</div>' : '') +
    (metric ? '<div class="mx-fx-pick-metric">' + metric + '</div>' : '') +
    '<div class="mx-fx-pick-actions">' +
      '<button class="btn-sm" onclick="toggleMatrixSelectFromChart(\'' +
        escJsAttr(id) + '\',\'' + escJsAttr(key) + '\')">' +
        (picked ? '&minus; Remove from selection' : '+ Add to selection') + '</button>' +
      '<button class="btn-sm btn-ghost" onclick="openFromMatrix(\'' + escJsAttr(id) +
        '\')">Open this run</button>' +
    '</div></div>';
}

// Ticking the row from the chart, without rebuilding the section: the row's own
// checkbox and the floating bar are the two things that have to agree with the
// set, and both are outside this panel.
function toggleMatrixSelectFromChart(id, key) {
  toggleMatrixSelect(id);
  const cb = document.querySelector(
    '#matrix-view tr[data-id="' + CSS.escape(id) + '"] .mx-td-cb input');
  if (cb) cb.checked = _matrixSelected.has(id);
  _renderEffectPick(key);
}

// The value that scored best for this parameter, by the metric's own direction.
// Values with no scored run have `best === null` and cannot win.
function _effectBestValue(p, d) {
  const lower = (d.metric || {}).goal === 'min';
  let out = null;
  (p.values || []).forEach(v => {
    if (v.best === null || v.best === undefined) return;
    if (!out || (lower ? v.best < out.v.best : v.best > out.v.best)) out = {v: v, tied: []};
  });
  if (!out) return null;
  // `metricMoved` is the shared epsilon, so two values that print the same
  // number are not reported as a winner and a loser — the same rule the compare
  // table's best/worst tint follows.
  out.tied = (p.values || []).filter(v =>
    v !== out.v && v.best !== null && v.best !== undefined &&
    !metricMoved(v.best, out.v.best));
  return out;
}

// One sentence per parameter, above the chart. A scatter of six points and a
// four-column table both *contain* the answer to "which value should I use";
// neither states it, so every panel was a small reading exercise repeated once
// per parameter. The caveats stay attached to the claim rather than being
// collected in a caption far from it: a "best" drawn from one run is a single
// number, not a finding.
function _effectReadingHtml(p, d) {
  if (p.aliased_with && p.aliased_with.length) return '';
  const win = _effectBestValue(p, d);
  if (!win) return '';
  const v = win.v;
  const label = v.missing ? 'not set' : _fmtParam(v.value);
  const runs = v.n_scored === 1
    ? 'the single run that tried it'
    : v.n_scored + ' runs tried it';
  const tiedNames = win.tied.map(t =>
    '<code>' + esc(p.key) + '=' + esc(t.missing ? 'not set' : _fmtParam(t.value)) + '</code>');
  return '<p class="mx-fx-read">Best so far at <code>' + esc(p.key) + '=' +
    esc(label) + '</code> &mdash; <strong>' + esc(fmtMetricVal(v.best)) + '</strong> ' +
    esc((d.metric || {}).key || '') + ', ' + esc(runs) + '.' +
    (tiedNames.length
      ? ' <span class="mx-fx-caveat">Tied with ' + tiedNames.join(', ') +
        ' &mdash; this value is not ahead on the best run.</span>'
      : '') +
    (p.single_run_per_value
      ? ' <span class="mx-fx-caveat">Every value was tried once, so this is one ' +
        'run beating another, not a repeatable difference.</span>'
      : '') +
    '</p>';
}

// A grouping that puts every run in one bucket colours the whole chart one
// colour and looks exactly like a control that did nothing — which is the
// commonest outcome of "colour by script" in a single-script project. Say which
// it is, rather than leaving the user to conclude the picker is broken.
// A run's value for the current grouping, from the per-run map the payload
// carries for every groupable key. The client decides the grouping, so it also
// resolves it — the point's own `group` field is the server's answer for
// whatever it was last asked, and following that would put the colour a request
// behind the control.
function _fxGroupOf(d, id, groupBy) {
  if (!groupBy) return '';
  const m = (d.run_groups || {})[id];
  const v = m ? m[groupBy] : undefined;
  return (v === undefined || v === null || v === '') ? '—' : String(v);
}

// A grouped series' legend entry. Two things it must not do: print the raw
// pseudo-key (`_run=…`, which is an internal name), and run to the width of the
// panel — colouring by run makes every label a full auto-generated run name, so
// six of them would be the chart. The run name is self-describing, so it drops
// the `key=` prefix the parameter groupings need.
function _fxSeriesLabel(d, groupBy, value) {
  const v = midEllipsis(String(value), 26);
  return groupBy === '_run' ? v : (_fxGroupLabel(d, groupBy) + '=' + v);
}

function _fxGroupLabel(d, groupBy) {
  const hit = (d.groupable || []).find(g => g.key === groupBy);
  return (hit && hit.label) || d.group_by_label || groupBy;
}

function _effectsGroupNoteHtml(d) {
  if (!_effectsGroupBy) return '';
  const label = _fxGroupLabel(d, _effectsGroupBy);
  const groups = new Set();
  (d.params || []).forEach(p => (p.points || []).forEach(
    pt => groups.add(_fxGroupOf(d, pt.id, _effectsGroupBy))));
  if (groups.size > 1) {
    return '<p class="mx-fx-groupnote">Points coloured by <code>' + esc(label) +
      '</code> &mdash; ' + groups.size + ' value' + (groups.size === 1 ? '' : 's') +
      ' across these runs.</p>';
  }
  return '<p class="mx-fx-groupnote mx-fx-groupnote-flat">Every run in this set has ' +
    'the same <code>' + esc(label) + '</code>' +
    (groups.size ? ' (<code>' + esc([...groups][0]) + '</code>)' : '') +
    ', so colouring by it separates nothing.</p>';
}

function _effectPanel(p, d, i) {
  const lower = d.metric.goal === 'min';
  let html = '<div class="mx-fx-panel"><div class="mx-fx-title">' +
    '<span class="mx-fx-key">' + esc(p.key) + '</span>' +
    '<span class="mx-fx-kind">' + esc(p.kind) + '</span>';
  if (p.aliased_with && p.aliased_with.length) {
    html += '<span class="mx-fx-flag mx-fx-flag-alias" title="' + esc(
      'These parameters changed together on every run, so this data cannot ' +
      'separate their effects.') + '">confounded with ' +
      esc(p.aliased_with.join(', ')) + '</span>';
  }
  if (p.single_run_per_value) {
    html += '<span class="mx-fx-flag" title="' + esc(
      'Every value was tried exactly once, so "best" and "median" are that one ' +
      'run — there is no distribution here.') + '">one run per value</span>';
  }
  html += '</div>';
  html += _effectReadingHtml(p, d);

  // The chart is suppressed, not merely captioned, when the parameter is
  // perfectly confounded: a scatter titled "lr vs val_acc" reads as an answer
  // no matter what the caption says.
  if (p.aliased_with && p.aliased_with.length) {
    html += '<div class="mx-fx-blocked">No chart: ' + esc(p.key) + ' and ' +
      esc(p.aliased_with.join(', ')) + ' were changed together on every run, ' +
      'so any apparent effect belongs to the pair, not to ' + esc(p.key) +
      '. Vary one of them on its own to separate them.</div>';
  } else {
    html += '<div class="mx-fx-chart"><canvas id="mx-fx-canvas-' + i + '"></canvas></div>' +
      '<div class="mx-fx-pick" data-key="' + esc(p.key) + '"></div>';
  }

  const winner = _effectBestValue(p, d);
  html += '<table class="mx-fx-table"><thead><tr><th>Value</th><th>Runs</th>' +
    '<th>' + (lower ? 'Lowest' : 'Best') + '</th><th>Median</th></tr></thead><tbody>';
  (p.values || []).forEach(v => {
    const label = v.missing ? '<span class="mx-missing">not set</span>' : esc(_fmtParam(v.value));
    // The winning row is marked in the table as well as stated above it: the
    // table is what gets read when the chart is a handful of points, and
    // finding the best number in a column by eye is the work the panel exists
    // to remove.
    const won = winner && (winner.v === v || winner.tied.indexOf(v) !== -1);
    html += '<tr' + (won ? ' class="mx-fx-win"' : '') +
      '><td class="mx-fx-val">' + label + '</td>' +
      '<td class="mx-fx-n">' + v.count +
        (v.n_scored !== v.count ? ' <span class="mx-fx-unscored" title="' +
          esc((v.count - v.n_scored) + ' of these runs have no value for this metric') +
          '">(' + v.n_scored + ' scored)</span>' : '') + '</td>' +
      '<td class="mx-fx-num">' + (v.best === null || v.best === undefined
        ? '<span class="mx-missing">—</span>' : esc(fmtMetricVal(v.best))) + '</td>' +
      '<td class="mx-fx-num">' + (v.median === null || v.median === undefined
        ? '<span class="mx-missing">—</span>'
        : (p.single_run_per_value ? '<span class="mx-fx-weak" title="' +
            esc('single run — not a distribution') + '">' + esc(fmtMetricVal(v.median)) +
            '</span>' : esc(fmtMetricVal(v.median)))) + '</td></tr>';
  });
  html += '</tbody></table></div>';
  return html;
}

// Reuses the Charts tab's series palette rather than adding a third one — a
// theme or contrast change should not have to find every hardcoded list.
// Capped deliberately: past a handful of groups the colours stop
// distinguishing anything.
const _FX_MAX_GROUPS = 6;

// A sweep tries a handful of values, and they are almost never evenly spaced:
// `lr` over 0.0001, 0.001, 0.01 on a linear axis puts two of the three values
// inside the first 10% of the plot and leaves 90% of it empty — every point
// stacked against one edge or the other, which is exactly the chart the user
// cannot read. Log scaling fixes that case and breaks the ones with a zero or a
// negative value in the sweep.
//
// So a numeric parameter with few distinct values is drawn on **evenly spaced
// ticks labelled with its actual values** — the same reading the table below
// gives, where what matters is which of the three settings won, not that one is
// a hundredth of another. A parameter with many distinct values is a real
// continuous sweep, and there the spacing carries the meaning, so it keeps a
// linear axis.
const EFFECT_CATEGORICAL_MAX = 8;

function _drawEffectChart(p, d, i) {
  if (p.aliased_with && p.aliased_with.length) return;
  const canvas = document.getElementById('mx-fx-canvas-' + i);
  if (!canvas || typeof Chart === 'undefined') return;
  const pts = p.points || [];
  if (!pts.length) return;

  const labels = [];
  (p.values || []).forEach(v => {
    const t = v.missing ? '—' : _fmtParam(v.value);
    if (!labels.includes(t)) labels.push(t);
  });
  const isNumeric = p.kind === 'numeric' && pts.every(pt => pt.numeric);
  const spaced = !isNumeric || labels.length <= EFFECT_CATEGORICAL_MAX;
  // On the spaced axis the x value *is* the label — Chart.js's category scale
  // maps it to a tick itself. Passing an index into a linear scale with
  // half-integer bounds generated ticks at -0.5, 0.5, 1.5 …, none of which
  // indexed the label array, so the axis came out with no value labels at all.
  const xOf = pt => spaced ? String(pt.x) : pt.x;

  // Colouring the `lr` panel by `lr` just repeats its own x axis, so the
  // grouping is dropped for that one panel. This is the rule the *server* used
  // to enforce by removing the selected key from the picker's own option list —
  // a per-panel rule applied section-wide, which left the control unable to
  // show what it was set to.
  const groupBy = (_effectsGroupBy && _effectsGroupBy !== p.key) ? _effectsGroupBy : '';
  const groupOf = pt => groupBy ? _fxGroupOf(d, pt.id, groupBy) : '';
  const groups = [];
  pts.forEach(pt => {
    const g = groupOf(pt);
    if (!groups.includes(g)) groups.push(g);
  });
  // Past a handful of groups the colours stop distinguishing anything, so only
  // the first few get one — but the rest are drawn in a muted overflow series,
  // never dropped. `groups.slice(0, N)` alone built datasets from the first few
  // only, so with more groups than colours (`colour by run`, and any sweep over
  // a many-valued parameter) the extra runs silently *vanished from the chart*:
  // a scatter quietly missing most of its points, with nothing saying so.
  const shown = groups.slice(0, _FX_MAX_GROUPS);
  const overflow = groups.slice(_FX_MAX_GROUPS);

  const hi = _fxHighlightSet();
  const datasets = shown.map((g, gi) => {
    const base = CHART_COLORS[gi % CHART_COLORS.length];
    const ds = {
      label: groupBy ? _fxSeriesLabel(d, groupBy, g) : 'each run',
      data: pts.filter(pt => groupOf(pt) === g).map(pt => ({
        x: xOf(pt), y: pt.y, _id: pt.id,
      })),
      // A generous hit radius: the points of a sweep overlap, and needing pixel
      // precision to read a tooltip is most of why hovering was the wrong tool
      // for finding a particular run.
      pointHitRadius: 14,
      order: 2,
      _runsBase: base,
    };
    _fxPointStyle(ds, hi, base);
    return ds;
  });

  if (overflow.length) {
    const rest = pts.filter(pt => overflow.indexOf(groupOf(pt)) !== -1);
    const ds = {
      label: overflow.length + ' more (uncoloured)',
      data: rest.map(pt => ({x: xOf(pt), y: pt.y, _id: pt.id})),
      pointHitRadius: 14,
      order: 3,
      _runsBase: CHART_MUTED,
    };
    _fxPointStyle(ds, hi, CHART_MUTED);
    datasets.push(ds);
  }

  // The best score at each value, joined up. Individual runs scatter — two runs
  // at the same setting land a visible distance apart — so the shape of the
  // answer ("it improves to 0.01 and then stops") is not readable from the
  // points alone. Drawn behind them, in the muted series colour, because it is
  // a summary of the points rather than more data. Only when the values are
  // evenly spaced: on a real continuous axis this line would imply the
  // parameter was swept densely enough to interpolate.
  const bestLine = spaced ? (p.values || []).map(v => ({
    x: v.missing ? '—' : _fmtParam(v.value),
    y: (v.best === null || v.best === undefined) ? null : v.best,
  })).filter(pt => pt.y !== null) : [];
  if (bestLine.length > 1) {
    datasets.push({
      label: ((d.metric || {}).goal === 'min' ? 'lowest' : 'best') + ' at each value',
      data: bestLine, type: 'line', showLine: true, spanGaps: true,
      borderColor: CHART_MUTED, backgroundColor: CHART_MUTED,
      borderWidth: 2, pointRadius: 0, tension: 0, order: 1,
    });
  }

  const metricLabel = (d.metric || {}).key +
    ((d.metric || {}).goal === 'min' ? ' (lower is better)' : ' (higher is better)');

  const chart = new Chart(canvas, {
    type: 'scatter',
    data: {datasets: datasets},
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      // One point per tooltip. The default groups everything near the cursor,
      // so a tooltip titled with one run's name listed two runs' values
      // underneath it — the exact ambiguity the title was added to remove.
      interaction: {mode: 'nearest', intersect: true},
      plugins: {
        // The legend is on whenever there is more than one series to tell
        // apart, which now includes the summary line — an unexplained grey line
        // through a scatter is a worse chart than no line.
        legend: {display: !!groupBy || datasets.length > 1, position: 'bottom',
                 labels: {boxWidth: 10, font: {size: 10},
                          // Per-point colours make `backgroundColor` an array,
                          // and the legend reads element 0 of it — so with a
                          // highlight active the swatch took the colour of
                          // whichever run happened to be first, usually a
                          // dimmed grey. The series' own base colour is what
                          // the legend is naming.
                          generateLabels: (chart) => chart.data.datasets.map((ds, di) => ({
                            text: ds.label,
                            fillStyle: ds._runsBase || ds.borderColor,
                            strokeStyle: ds._runsBase || ds.borderColor,
                            lineWidth: 1,
                            hidden: !chart.isDatasetVisible(di),
                            datasetIndex: di,
                          }))}},
        tooltip: {callbacks: {
          // The run's name first. `lr=0.01  loss=1.8298` describes a point
          // already plotted at those coordinates and never says whose it is.
          title: (items) => {
            const raw = items[0] && items[0].raw;
            return (raw && raw._id) ? midEllipsis(_fxRunName(raw._id), 40) : '';
          },
          label: (ctx) => {
            const xv = spaced ? (labels[ctx.parsed.x] !== undefined
                                 ? labels[ctx.parsed.x] : ctx.parsed.x)
                              : ctx.parsed.x;
            return p.key + '=' + xv + '  ' + d.metric.key + '=' + fmtMetricVal(ctx.parsed.y);
          },
        }},
      },
      scales: {
        x: spaced
          ? {type: 'category', labels: labels, offset: true,
             title: {display: true, text: p.key, font: {size: 11}},
             ticks: {autoSkip: false, font: {size: 11}}}
          : {title: {display: true, text: p.key, font: {size: 11}}},
        y: {title: {display: true, text: metricLabel, font: {size: 11}}},
      },
      onClick: (evt, els) => {
        if (!els || !els.length) return;
        const ds = datasets[els[0].datasetIndex];
        const pt = ds && ds.data[els[0].index];
        if (pt && pt._id) pickEffectPoint(p.key, pt._id);
      },
    },
  });
  _effectsCharts.push(chart);
}
