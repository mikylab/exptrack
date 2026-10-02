// Run detail Overview: metrics, params, notes, reproduce and run cards.

// Two columns of cards, each sized to its content (`align-items: start`), with
// the one section that can run for pages — params — capped. The old Overview
// paired unrelated stacks side by side, so whichever was longer left a tall
// empty gap beside it.

// ── Params card ──────────────────────────────────────────────────────────────
// About a screenful, changed-vs-previous first. A long sweep config made
// Overview scroll for pages. Expanded/filter state is module-level so a live
// run's 5 s rebuild keeps it; moving to another run resets it.
const _PARAMS_CAP = 14;
let _paramsExpanded = false;
let _paramsFilter = '';

function _paramFilterMatch(key, value, q) {
  if (!q) return true;
  const n = String(q).toLowerCase();
  return String(key).toLowerCase().includes(n) || String(value).toLowerCase().includes(n);
}

function _paramsCardHtml(exp, paramRows, addParamForm, count) {
  const id = escJsAttr(exp.id);
  const filter = count > _PARAMS_CAP
    ? '<input type="search" id="ov-params-filter" class="params-filter" placeholder="filter" value="' + esc(_paramsFilter)
      + '" oninput="filterParamsCard(this.value)">' : '';
  const more = count > _PARAMS_CAP
    ? '<button class="params-more" onclick="toggleParamsCard()">'
      + (_paramsExpanded ? 'Show fewer ▴' : 'Show all ' + count + ' ▾') + '</button>' : '';
  return '<div class="ov-card ov-params" id="ov-params">'
    + '<h2 class="ov-card-head">Params (' + count + ')' + filter
    + '<span class="section-actions"><button class="copy-btn" onclick="copyExportFmt(\'' + id + '\',\'params-md\')"'
    + ' title="Copy as a markdown table — pastes into lab notebooks, Obsidian, GitHub, Jupyter markdown cells">Copy</button></span></h2>'
    + (paramRows
      ? '<table class="params-table" id="ov-params-table"><tr><th>Key</th><th>Value</th><th>Source</th></tr>' + paramRows + '</table>'
      : '<p class="muted-note">No params yet.</p>')
    + more + addParamForm + '</div>';
}

// Cap and filter applied to the rows in place — no rebuild, so an inline edit
// open elsewhere on the page is untouched.
function _applyParamsCap() {
  const rows = document.querySelectorAll('#ov-params-table tr.param-row');
  let shown = 0;
  rows.forEach(r => {
    const ok = _paramFilterMatch(r.dataset.pkey, r.dataset.pval, _paramsFilter);
    const visible = ok && (_paramsExpanded || !!_paramsFilter || shown < _PARAMS_CAP);
    r.style.display = visible ? '' : 'none';
    if (visible) shown++;
  });
}

function toggleParamsCard() {
  _paramsExpanded = !_paramsExpanded;
  const card = document.getElementById('ov-params');
  const btn = card && card.querySelector('.params-more');
  if (btn) {
    btn.textContent = _paramsExpanded ? 'Show fewer ▴'
      : 'Show all ' + card.querySelectorAll('tr.param-row').length + ' ▾';
  }
  _applyParamsCap();
}

function filterParamsCard(q) {
  _paramsFilter = q || '';
  _applyParamsCap();
}

// Rows for params that moved since the previous run go first, marked — they
// are what this run is about. Called once the async run-delta lands.
function _markChangedParams(keys) {
  const table = document.getElementById('ov-params-table');
  if (!table || !keys || !keys.length) return;
  const header = table.querySelector('tr');
  const set = new Set(keys);
  const changed = [...table.querySelectorAll('tr.param-row')].filter(r => set.has(r.dataset.pkey));
  for (const r of changed.reverse()) {
    r.classList.add('param-changed');
    r.title = 'Changed since the previous run';
    header.after(r);
  }
  _applyParamsCap();
}

// ── Overview layout ──────────────────────────────────────────────────────────

// The small facts about a run, in one card. Host and Python moved to
// Code › Env; Uncommitted is a one-line pointer to Code › Changes.
function _runCardHtml(exp, p) {
  const id = escJsAttr(exp.id);
  const uncommitted = p.diffData.diff
    ? '<a href="#" onclick="switchDetailTab(\'code\',\'' + id + '\');switchDetailView(\'code\',\'changes\',\'' + id + '\');return false">'
      + (p.diffCompacted ? 'compacted' : esc(String(exp.diff_lines)) + ' lines') + ' →</a>'
    : '<span class="muted-note">none (all changes were committed)</span>';
  const stage = exp.stage != null
    ? esc(String(exp.stage)) + (exp.stage_name ? ' (' + esc(exp.stage_name) + ')' : '')
    : '<span class="muted-note">click to set stage</span>';
  return '<div class="ov-card ov-run"><h2 class="ov-card-head">Run</h2><div class="info-grid">'
    + '<span class="label">ID</span><span>' + esc(exp.id) + '</span>'
    + '<span class="label">Script</span><span id="detail-script" class="editable-hint" ondblclick="startDetailScriptEdit(\''
    + id + '\',this)" title="Double-click to edit">' + esc(exp.script || '--') + '</span>'
    + '<span class="label">Tags</span><span class="tag-list" id="detail-tags">' + p.tagsHtml + '</span>'
    + '<span class="label">Studies</span><span class="tag-list" id="detail-studies">' + p.studiesHtml + '</span>'
    + '<span class="label">Stage</span><span id="detail-stage" class="editable-hint" onclick="startDetailStageEdit(\''
    + id + '\',this)" title="Click to edit stage">' + stage + '</span>'
    + '<span class="label">Uncommitted</span><span>' + uncommitted + '</span>'
    + '</div></div>';
}

// p: {whatChangedHtml, metricRows, logResultForm, reproHtml, paramsCard,
//     tagsHtml, studiesHtml, diffData, diffCompacted}
// "What changed" heads the page, full width: what was tried differently since
// the last run of this script, with its code diff one click away. It spans both
// columns, so however long it runs it leaves no gap beside it.
function _overviewHtml(exp, p) {
  return (p.whatChangedHtml || '')
    + '<div class="ov-grid">'
    + '<div class="ov-col">'
    +   '<div class="ov-card ov-metrics"><h2 class="ov-card-head">Metrics (' + exp.metrics.length + ')</h2>'
    +     (p.metricRows || '<p class="muted-note">No metrics yet.</p>') + p.logResultForm
    +     '<div id="overview-chart-preview" class="ov-chart-preview"></div></div>'
    +   '<div class="ov-card ov-notes">' + notesSectionHtml(exp) + '</div>'
    +   '<div class="ov-card ov-repro">' + p.reproHtml + '</div>'
    + '</div>'
    + '<div class="ov-col">' + p.paramsCard + _runCardHtml(exp, p) + '</div>'
    + '</div>';
}

// "more ▾" under the notes only when they overflow the cap.
function _syncNotesCap() {
  const nc = document.getElementById('notes-capped');
  const btn = nc && nc.nextElementSibling;
  if (btn && btn.classList.contains('notes-more')) {
    btn.style.display = nc.classList.contains('open') || nc.scrollHeight > nc.clientHeight + 2 ? '' : 'none';
  }
}

// What changed with nothing to compare against: one folded line that says so.
// The card used to be absent for a script's first run and for notebooks, so
// Show code changes and Copy diff appeared on some runs and not others with no
// reason given.
function _whatChangedEmptyHtml(exp) {
  const script = String(exp.script || '').split(/[\\/]/).pop() || 'this script';
  const why = _isNotebookRun(exp)
    ? 'no earlier run of ' + esc(script) + ', nothing to compare against — tick runs in the list and press Compare'
    : 'first run of ' + esc(script) + ', nothing to compare against';
  return '<div class="what-changed-card wc-empty"><h2 class="wc-empty-head">What changed'
    + ' <span class="wc-empty-why">— ' + why + '</span></h2></div>';
}
