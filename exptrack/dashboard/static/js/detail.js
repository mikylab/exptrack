

// Shared wrapper for the three "there is no diff body here" notices (compacted
// / capture failed / body unavailable), so the styling lives in one place.
// `msg` is pre-escaped by the caller; `note` is the parenthesised aside.
function _diffNotice(msg, note) {
  return '<div style="padding:16px;color:var(--yellow,#e8a735);font-style:italic">' + msg
    + (note ? ' <span style="color:var(--muted);font-size:12px">(' + note + ')</span>' : '')
    + '</div>';
}

async function _openPairCompare(id1, id2) {
  owlSpeak('compare');
  showCompareView();
  document.getElementById('compare-pair-tab').classList.add('active');
  document.getElementById('compare-multi-tab').classList.remove('active');
  document.getElementById('compare-pair-content').style.display = '';
  document.getElementById('compare-multi-content').style.display = 'none';
  await populateCompareDropdowns();
  document.getElementById('cmp-id1').value = id1;
  document.getElementById('cmp-id2').value = id2;
  doCompare();
}

async function compareSelected() {
  if (selectedIds.size < 2) return;
  const ids = [...selectedIds];
  if (ids.length === 2) {
    await _openPairCompare(ids[0], ids[1]);
  } else {
    // Multi compare
    owlSpeak('compare');
    showCompareView();
    document.getElementById('compare-pair-tab').classList.remove('active');
    document.getElementById('compare-multi-tab').classList.add('active');
    document.getElementById('compare-pair-content').style.display = 'none';
    document.getElementById('compare-multi-content').style.display = '';
    await populateMultiCompareSelector();
    doMultiCompare(ids);
  }
}

async function compareWithPrevious(prevId, curId) {
  await _openPairCompare(prevId, curId);
}

function filterExps(status) {
  if (status) owlSpeak('filter');
  currentFilter = status;
  renderStatusChips();
  loadExperiments();
}

// Runs available to the Compare pickers. Cached so the filter box can re-narrow
// the options without a round-trip, and so switching Compare tabs doesn't refetch
// the whole list. Each entry carries its pre-built option label (`lbl`) and a
// lowercased copy for matching, so filtering and rendering don't rebuild it.
let _cmpExps = [];
let _cmpTotal = 0;
let _cmpHasMore = false;

// Auto-named runs differ only in a tail the <option> used to cut off, so a
// hundred-entry dropdown read as a hundred copies of the same line. Keep the
// full name and append the run's distinguishing params, so the options are
// actually distinguishable, and let the filter box below narrow them.
function _cmpOptionLabel(e) {
  const bits = [e.id.slice(0, 6), e.name];
  const ps = Object.entries(e.params || {})
    .filter(([k]) => isUserParamKey(k))
    .slice(0, 3)
    .map(([k, v]) => paramColLabel(k) + '=' + v);
  if (ps.length) bits.push(ps.join(' '));
  bits.push(e.status, fmtDt(e.created_at));
  return bits.join('  |  ');
}

function _cmpEntries(exps) {
  return exps.map(e => {
    const lbl = _cmpOptionLabel(e);
    return {id: e.id, lbl: lbl, hay: lbl.toLowerCase()};
  });
}

// The one place an <option> is emitted. `keepId` is force-included even when the
// query excludes it, so narrowing the filter never silently drops the current
// pick; `selectedSet` marks the multi-list's selections.
function _cmpOptsHtml(q, placeholder, selectedSet, keepId) {
  const rows = _cmpExps.filter(e => (!q || e.hay.includes(q)) || e.id === keepId);
  const opts = rows.map(e => '<option value="' + esc(e.id) + '"'
    + (selectedSet && selectedSet.has(e.id) ? ' selected' : '') + '>'
    + esc(e.lbl) + '</option>').join('');
  if (!placeholder) return opts;
  const head = rows.length === _cmpExps.length
    ? placeholder
    : placeholder + ' (' + rows.length + ' of ' + _cmpExps.length + ' shown)';
  return '<option value="">' + esc(head) + '</option>' + opts;
}

// Same honesty rule as the main table's truncation notice: a filter box that
// searches a partial set must say so, or "not found" reads as "doesn't exist".
function _renderCmpTruncNotice() {
  const el = document.getElementById('cmp-trunc');
  if (!el) return;
  if (!_cmpHasMore) { el.innerHTML = ''; el.style.display = 'none'; return; }
  const of = _cmpTotal > _cmpExps.length ? ' of ' + _cmpTotal.toLocaleString() : '';
  el.innerHTML = 'Filtering the ' + _cmpExps.length.toLocaleString()
    + ' most recent runs' + of + '. '
    + '<button class="action-btn" onclick="loadAllCompareRuns()">Load all runs</button>';
  el.style.display = 'flex';
}

// Fetch the picker list once per Compare visit. `force` re-fetches; `limit`
// overrides the page size for the "load all" path.
async function _loadCmpExps(force, limit) {
  if (_cmpExps.length && !force) return true;
  const cap = limit || EXP_PAGE_SIZE;
  const exps = await api('/api/experiments?limit=' + cap);
  if (!Array.isArray(exps)) return false;
  _cmpExps = _cmpEntries(exps);
  _cmpTotal = Math.max(expTotal, exps.length);
  _cmpHasMore = exps.length >= cap && _cmpTotal > exps.length;
  _renderCmpTruncNotice();
  return true;
}

async function loadAllCompareRuns() {
  const btn = document.querySelector('#cmp-trunc button');
  if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
  if (await _loadCmpExps(true, Math.max(_cmpTotal, EXP_PAGE_SIZE) + 1)) filterCompareOptions();
}

// Re-narrow both pair selects and the multi list from the cached runs,
// preserving whatever is already picked.
function filterCompareOptions() {
  const box = document.getElementById('cmp-filter');
  const q = box ? box.value.trim().toLowerCase() : '';
  for (const id of ['cmp-id1', 'cmp-id2']) {
    const sel = document.getElementById(id);
    if (!sel) continue;
    const keep = sel.value;
    sel.innerHTML = _cmpOptsHtml(q, '-- Select experiment --', null, keep);
    sel.value = keep;
  }
  const multi = document.getElementById('cmp-multi-select');
  if (multi) {
    const picked = new Set([...multi.selectedOptions].map(o => o.value));
    multi.innerHTML = _cmpOptsHtml(q, '', picked.size ? picked : selectedIds);
  }
}

// Rebuilding up to three option lists per keystroke over a thousand runs is the
// same cost the main search box debounces (js/core.py), so share the treatment.
const onCompareFilter = debounce(filterCompareOptions, 150);

async function populateCompareDropdowns() {
  if (!await _loadCmpExps()) return;
  const sel1 = document.getElementById('cmp-id1');
  const sel2 = document.getElementById('cmp-id2');
  const prev1 = sel1.value, prev2 = sel2.value;
  const box = document.getElementById('cmp-filter');
  const q = box ? box.value.trim().toLowerCase() : '';
  sel1.innerHTML = _cmpOptsHtml(q, '-- Select base experiment --', null, prev1);
  sel2.innerHTML = _cmpOptsHtml(q, '-- Select compare experiment --', null, prev2);
  if (prev1) sel1.value = prev1;
  if (prev2) sel2.value = prev2;
  if (!prev1 && !prev2 && selectedIds.size === 2) {
    const ids = [...selectedIds];
    sel1.value = ids[0];
    sel2.value = ids[1];
  }
}

function artifactTypeBadge(path) {
  const ext = (path || '').split('.').pop().toLowerCase();
  if (['png','jpg','jpeg','svg','gif','bmp','tiff'].includes(ext)) return '<span class="artifact-type-badge img">image</span>';
  if (['pt','pth','h5','hdf5','onnx','pkl','joblib','safetensors'].includes(ext)) return '<span class="artifact-type-badge model">model</span>';
  if (['csv','json','jsonl','parquet','tsv','npy','npz'].includes(ext)) return '<span class="artifact-type-badge data">data</span>';
  if (['log','txt','out','err'].includes(ext)) return '<span class="artifact-type-badge log">log</span>';
  if (!ext || path.indexOf('.') === -1) return '<span class="artifact-type-badge dir">dir</span>';
  return '<span class="artifact-type-badge">file</span>';
}

function showAllArtifacts(expId) {
  const table = document.getElementById('artifact-table-' + expId);
  if (!table) return;
  table.classList.remove('truncated');
  const notice = document.getElementById('art-truncate-' + expId);
  if (notice) notice.remove();
}

function filterArtifacts(expId, query) {
  const table = document.getElementById('artifact-table-' + expId);
  if (!table) return;
  if (query) showAllArtifacts(expId);
  const q = (query || '').trim().toLowerCase();
  const rows = table.querySelectorAll('tr[data-artifact-search]');
  let visible = 0;
  rows.forEach(r => {
    const match = !q || (r.dataset.artifactSearch || '').includes(q);
    r.classList.toggle('filter-hidden', !match);
    if (match) visible++;
  });
  let hint = table.querySelector('tr.artifact-filter-hint');
  if (q && visible === 0) {
    if (!hint) {
      const tbody = table.querySelector('tbody') || table;
      tbody.insertAdjacentHTML('beforeend', '<tr class="artifact-filter-hint"><td colspan="3" style="color:var(--muted);font-size:12px;text-align:center;padding:8px">No artifacts match filter.</td></tr>');
    }
  } else if (hint) {
    hint.remove();
  }
}

async function showDetail(id) {
  // Toggle (clicking the open experiment deselects it) ONLY when that
  // experiment's detail is the view actually on screen. While the Sessions or
  // Trash tab overlays the canvas — e.g. right after promoting a node, when
  // currentDetailId may still equal `id` from an earlier visit — the detail
  // view is hidden, so a plain equality check would read the click as "close"
  // and the user would have to click a second time to actually open it. Guard
  // on real visibility so the first click lands.
  const detailEl = document.getElementById('detail-view');
  const detailVisible = detailEl && detailEl.style.display !== 'none' &&
    !document.body.classList.contains('sessions-active') &&
    !document.body.classList.contains('trash-active');
  if (currentDetailId === id && detailVisible) {
    showWelcome();
    return;
  }
  return refreshDetail(id);
}

// ── Detail loading / error states ───────────────────────────────────────────

function _detailLoadingHtml() {
  return '<div class="detail-loading">' +
    '<div class="skel skel-title"></div>' +
    '<div class="skel skel-bar" style="width:92%"></div>' +
    '<div class="skel skel-bar" style="width:70%"></div>' +
    '<div class="skel skel-bar" style="width:84%"></div>' +
    '<div class="skel skel-bar" style="width:58%"></div>' +
    '<div class="skel skel-bar" style="width:78%"></div>' +
    '</div>';
}

function _detailErrorHtml(id, msg) {
  return '<div class="detail-error">' +
    '<div style="font-size:32px">⚠️</div>' +
    '<div style="margin-top:8px;font-weight:600">' + esc(msg) + '</div>' +
    '<div><button class="action-btn retry-btn" onclick="refreshDetail(\'' + escJsAttr(id) + '\')">Retry</button> ' +
    '<button class="action-btn retry-btn" onclick="showWelcome()">Back to list</button></div>' +
    '</div>';
}

// ── Detail section builders (kept out of the big refreshDetail template) ──────

function _buildCodeSection(codeChanges) {
  if (!Object.keys(codeChanges).length) return '';
  let html = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Code Changes</h2><div class="section-body"><div class="code-changes">';
  for (const [k, v] of Object.entries(codeChanges)) {
    const label = k === '_code_changes' ? 'Script diff vs. last commit' : k.replace('_code_change/', 'Cell ');
    html += '<div class="change-item"><div class="change-label">' + esc(label) + '</div>' + _renderCodeChangeParts(v) + '</div>';
  }
  return html + '</div></div>';
}

function _buildVarSection(varChanges) {
  if (!Object.keys(varChanges).length) return '';
  const scalars = {}, arrays = {}, other = {};
  for (const [k, v] of Object.entries(varChanges)) {
    const sv = String(v);
    if (sv.startsWith('ndarray(') || sv.startsWith('Tensor(') || sv.startsWith('DataFrame(') || sv.startsWith('Series(')) {
      arrays[k] = v;
    } else if (sv.startsWith("'") || sv.startsWith('"') || !isNaN(Number(sv)) || sv === 'True' || sv === 'False') {
      scalars[k] = v;
    } else {
      other[k] = v;
    }
  }
  let html = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Variables (' + Object.keys(varChanges).length + ')</h2><div class="section-body"><div class="var-changes">';
  const renderGroup = (title, vars) => {
    if (!Object.keys(vars).length) return '';
    let h = '<div class="var-section-title">' + title + ' (' + Object.keys(vars).length + ')</div><table>';
    for (const [k, v] of Object.entries(vars)) {
      let displayVal = String(v);
      if (displayVal.startsWith(k + ' = ')) displayVal = displayVal.slice(k.length + 3);
      h += '<tr><td class="var-name">' + esc(k) + '</td><td>= ' + esc(displayVal) + '</td></tr>';
    }
    return h + '</table>';
  };
  html += renderGroup('Scalars', scalars);
  html += renderGroup('Arrays & Tensors', arrays);
  html += renderGroup('Other', other);
  return html + '</div></div>';
}

function _buildDatasetsSection(datasets) {
  const keys = Object.keys(datasets || {});
  if (!keys.length) return '';
  let html = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Datasets (' + keys.length + ') <span class="help-icon" title="Fingerprints of dataset files/dirs passed as params, captured at run end. A changed hash means the input data changed between runs.">?</span></h2><div class="section-body"><table class="params-table"><tr><th>Param</th><th>Path</th><th>Size</th><th>Fingerprint</th></tr>';
  for (const k of keys) {
    const m = datasets[k] || {};
    const info = m.kind === 'dir' ? (m.n_files + ' files' + (m.truncated ? '+' : '')) : 'file';
    const full = m.hash || '';
    const isPartial = full.startsWith('partial:');
    const hash = full.replace('partial:', '').slice(0, 12);
    html += '<tr><td>' + esc(k) + '</td>' +
      '<td class="artifact-path-cell" title="' + esc(m.path || '') + '">' + esc(m.path || '') +
      ' <span style="color:var(--muted);font-size:11px">(' + info + ')</span></td>' +
      '<td>' + fmtBytes(m.size || 0) + '</td>' +
      '<td title="' + esc(full) + '" style="font-family:var(--font-mono);font-size:11px">' + esc(hash) +
      (isPartial ? ' <span style="color:var(--muted)" title="partial hash (large file)">~</span>' : '') + '</td></tr>';
  }
  return html + '</table></div>';
}

// The previous-same-script experiment can only change by a *new* run being
// created for that script — never by editing metrics/params/tags on the run
// currently being viewed. refreshDetail runs on every such edit and on every
// auto-refresh poll, so this single-slot cache (keyed by experiment id) keeps
// those from re-querying it every time.
let _prevByScriptCache = { id: null, data: null };

async function refreshDetail(id, opts) {
  // Only auto-expand the sidebar when transitioning to a different experiment
  // (or entering detail view from welcome/compare). On in-place refreshes from
  // logging a metric / adding a param / etc, leave the sidebar in whatever
  // state the user left it. Filmstrip navigation (opts.keepSidebar) is a lateral
  // move between already-open runs, so it also leaves the sidebar untouched.
  const keepSidebar = opts && opts.keepSidebar;
  const isInitialEntry = currentDetailId !== id ||
    document.getElementById('detail-view').style.display === 'none';
  currentDetailId = id;
  showDetailView();
  if (isInitialEntry && !keepSidebar) {
    document.getElementById('exp-sidebar').classList.remove('collapsed');
  }
  renderExpList();

  // Show a loading skeleton only on first entry to this experiment, so an
  // in-place refresh (logging a metric, auto-poll) doesn't flicker the panel.
  const _panel = document.getElementById('detail-panel');
  if (_panel && isInitialEntry) _panel.innerHTML = _detailLoadingHtml();

  const needsPrevFetch = _prevByScriptCache.id !== id;
  let exp, metricsData, diffData, prevByScript;
  try {
    [exp, metricsData, diffData, prevByScript] = await Promise.all([
      api('/api/experiment/' + id),
      api('/api/metrics/' + id),
      api('/api/diff/' + id),
      needsPrevFetch ? api('/api/experiment/' + id + '/prev-by-script') : Promise.resolve(_prevByScriptCache.data),
    ]);
    if (needsPrevFetch) _prevByScriptCache = { id, data: prevByScript };
  } catch (err) {
    // User navigated to another experiment while we were fetching — don't
    // clobber the panel they're now looking at.
    if (currentDetailId !== id) return;
    if (_panel) _panel.innerHTML = _detailErrorHtml(id, 'Could not load experiment (network error).');
    return;
  }
  // The fetches above are async; a later click may have changed currentDetailId
  // before our responses landed. Bail before any DOM write so a slow response
  // for experiment A can't overwrite the panel now showing experiment B.
  if (currentDetailId !== id) return;
  if (!exp || exp.error) {
    if (_panel) _panel.innerHTML = _detailErrorHtml(id, (exp && exp.error) || 'Experiment not found.');
    return;
  }

  const regularParams = {};
  const codeChanges = {};
  const varChanges = {};
  let cellsRan = null;
  for (const [k, v] of Object.entries(exp.params)) {
    if (k === '_code_changes' || k.startsWith('_code_change/')) {
      codeChanges[k] = v;
    } else if (k.startsWith('_var/')) {
      varChanges[k.slice(5)] = v;
    } else if (k.startsWith('_result:')) {
      // Legacy _result:* params — skip (migrated to metrics table)
    } else if (k === '_script_hash' || k === '_cells_ran' || k === '_result_source') {
      if (k === '_cells_ran') cellsRan = v;
    } else if (isUserParamKey(k)) {
      regularParams[k] = v;
    }
    // Anything else is `_`-prefixed bookkeeping with a home of its own
    // (`_tags` → the tag list, `_code_snapshot` → the Code changes panel,
    // `_dataset_manifest` → Datasets) and is not a param the user set.
  }

  const paramSources = exp.param_sources || {};
  const paramRows = Object.entries(regularParams).map(([k,v]) => {
    const src = paramSources[k] || 'auto';
    const isManual = src === 'manual';
    const keyColor = isManual ? 'var(--tl-metric)' : 'var(--blue)';
    const keyAttrs = isManual
      ? ` class="editable-hint" ondblclick="startParamRename('${exp.id}','${escJsAttr(k)}',this)" title="Double-click to rename"`
      : '';
    const valAttrs = isManual
      ? ` class="editable-hint" ondblclick="startParamEdit('${exp.id}','${escJsAttr(k)}',this)" title="Double-click to edit"`
      : '';
    const delBtn = isManual
      ? `<span class="result-del-x" onclick="event.stopPropagation();deleteParam('${exp.id}','${escJsAttr(k)}')" title="Delete">&times;</span>`
      : '';
    return `<tr><td style="color:${keyColor}"${keyAttrs}>${esc(k)}</td><td${valAttrs}>${esc(JSON.stringify(v))}</td><td><span class="source-badge ${src}">${src}</span> ${delBtn}</td></tr>`;
  }).join('');

  // "What changed" card — auto-diffs params against the previous run of the
  // same script, so a run left with its auto-generated name still shows what
  // was actually tried differently (no rename required).
  let whatChangedHtml = '';
  if (prevByScript && prevByScript.id) {
    const prevParams = prevByScript.params || {};
    const changeKeys = [...new Set([...Object.keys(regularParams), ...Object.keys(prevParams)])]
      .filter(isUserParamKey).sort();
    const changedRows = changeKeys.map(k => paramDiffRow(k, prevParams, regularParams))
      .filter(r => r.differs).map(r => r.html);
    const paramsBody = changeTableHtml(['Param', 'Previous', 'This run'], changedRows,
      'No parameter changes since the previous run — same config, different attempt.');

    const prevMetrics = prevByScript.metrics || {};
    // exp.metrics is already fetched for this page load — reuse it for the
    // current run's last-per-key values instead of a second server round trip
    // (shares latestMetricsMap with compare.js's m1/m2 derivation).
    const curMetrics = latestMetricsMap(exp.metrics);
    const metricKeys = [...new Set([...Object.keys(curMetrics), ...Object.keys(prevMetrics)])].sort();
    const metricRows = metricKeys.map(k => {
      const before = prevMetrics[k], after = curMetrics[k];
      // A metric present on only one run isn't a value change — it was simply
      // not measured on the other side. Skip it so the card doesn't flood with
      // "—→value" rows when the previous run logged no (or different) metrics.
      if (before === undefined || after === undefined) return null;
      const { differs, html: delta } = metricDelta(before, after, k);
      if (!differs) return null;
      const [sb, sa] = fmtMetricPair(before, after);
      return `<tr><td>${esc(abbrevMetric(k))}</td><td>${esc(sb)}</td><td>${esc(sa)}</td><td>${delta}</td></tr>`;
    }).filter(Boolean);
    const metricsBody = changeTableHtml(['Metric', 'Previous', 'This run', 'Delta'], metricRows);

    // How much earlier, not just when: a minute-resolution timestamp doesn't say
    // which of the two runs came first (see relEarlier).
    const prevAge = relEarlier(prevByScript.created_at, exp.created_at);
    const prevWhen = prevAge || fmtDt(prevByScript.created_at);
    whatChangedHtml = `<div class="what-changed-card">
      <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">What changed <span style="font-weight:normal;font-size:12px;color:var(--muted)" title="Started ${esc(fmtDtFull(prevByScript.created_at))}">vs "${esc(prevByScript.name)}" — ${esc(prevWhen)}</span>${_baselineFailedTag(prevByScript.status)}
        <span class="section-actions" onclick="event.stopPropagation()"><button class="copy-btn" onclick="compareWithPrevious('${prevByScript.id}','${exp.id}')" title="Open full side-by-side compare">Compare</button></span>
      </h2>
      <div class="section-body">${_baselineFailedNote(prevByScript.status, metricRows.length)}${paramsBody}${metricsBody}
        <div class="wc-code" id="wc-code-${esc(exp.id)}">
          <button class="copy-btn" onclick="loadWhatChangedCode('${escJsAttr(prevByScript.id)}','${escJsAttr(exp.id)}',this)"
            title="Diff this run's code against the previous run's — the script snapshot, or the notebook cells that differ">Show code changes</button>
        </div>
      </div>
    </div>`;
  }

  const addParamForm = `<div class="artifact-add-form" style="margin-top:8px" id="add-param-form-${exp.id}">
    <input type="text" id="param-key-${exp.id}" placeholder="Key" style="width:160px" onkeydown="if(event.key==='Enter')addParam('${exp.id}')">
    <input type="text" id="param-val-${exp.id}" placeholder="Value (JSON or text)" style="width:200px" onkeydown="if(event.key==='Enter')addParam('${exp.id}')">
    <button onclick="addParam('${exp.id}')">+ Add Param</button>
  </div>`;

  // Build unified metrics rows grouped by prefix (train/*, test/*, val/*, etc.)
  function buildMetricRow(m, showFullKey) {
    const src = m.source || 'auto';
    const isManual = src === 'manual';
    const keyColor = isManual ? 'var(--tl-metric)' : 'var(--green)';
    const delBtn = `<span class="result-del-x" onclick="event.stopPropagation();deleteMetric('${exp.id}','${escJsAttr(m.key)}')" title="Delete all">&times;</span>`;
    const editAttr = isManual ? ` class="editable-hint" ondblclick="startResultEdit('${exp.id}','${escJsAttr(m.key)}',this)" title="Double-click to edit"` : '';
    const displayKey = showFullKey ? abbrevMetric(m.key) : abbrevMetric(m.key.includes('/') ? m.key.split('/').slice(1).join('/') : m.key);
    const sMin = m.step_min, sMax = m.step_max;
    const stepStr = sMin == null ? '--' : (sMin === sMax ? String(sMin) : sMin + '-' + sMax);
    return `<tr><td style="color:${keyColor}" class="editable-hint" ondblclick="startMetricRename('${exp.id}','${escJsAttr(m.key)}',this)" title="${esc(m.key)} — double-click to rename">${esc(displayKey)}</td><td${editAttr}>${m.last?.toFixed(4) ?? '--'}</td><td>${m.min?.toFixed(4) ?? '--'}</td><td>${m.max?.toFixed(4) ?? '--'}</td><td style="font-size:12px;color:var(--muted)">${stepStr}</td><td><span class="source-badge ${src}">${src}</span> ${delBtn}</td></tr>`;
  }
  // Group metrics by prefix
  const metricGroups = {};
  for (const m of exp.metrics) {
    const slashIdx = m.key.indexOf('/');
    const group = slashIdx > 0 ? m.key.slice(0, slashIdx) : '';
    (metricGroups[group] = metricGroups[group] || []).push(m);
  }
  const groupKeys = Object.keys(metricGroups).sort((a, b) => a === '' ? 1 : b === '' ? -1 : a.localeCompare(b));
  let metricRows = '';
  const thead = '<tr><th>Key</th><th>Last</th><th>Min</th><th>Max</th><th>Steps</th><th>Source</th></tr>';
  if (groupKeys.length <= 1) {
    // No grouping needed — single flat table, show abbreviated full key
    metricRows = exp.metrics.map(m => buildMetricRow(m, true)).join('');
    if (metricRows) metricRows = '<table class="metrics-table">' + thead + metricRows + '</table>';
  } else {
    // Grouped tables with prefix headers
    for (const g of groupKeys) {
      const label = g || 'Other';
      const items = metricGroups[g];
      metricRows += '<div class="metric-group"><h3 class="metric-group-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">' + esc(label) + ' <span style="font-weight:normal;font-size:12px">(' + items.length + ')</span></h3>';
      metricRows += '<table class="metrics-table">' + thead;
      for (const m of items) metricRows += buildMetricRow(m);
      metricRows += '</table></div>';
    }
  }

  const ARTIFACT_TRUNCATE_THRESHOLD = 50;
  const artTotal = exp.artifacts.length;
  const artTruncated = artTotal > ARTIFACT_TRUNCATE_THRESHOLD;
  const artRows = exp.artifacts.map((a, i) => {
    const ext = (a.path || '').split('.').pop().toLowerCase();
    const isLog = ['log', 'txt', 'out', 'err'].includes(ext);
    const isData = ['csv', 'json', 'jsonl'].includes(ext);
    const viewBtn = (isLog || isData)
      ? `<button onclick="viewLogFile('${escJsAttr(a.path)}','${escJsAttr(a.label)}')" title="View contents">view</button>`
      : '';
    const searchKey = ((a.label || '') + ' ' + (a.path || '')).toLowerCase();
    const overflow = i >= ARTIFACT_TRUNCATE_THRESHOLD ? ' overflow' : '';
    return `<tr data-artifact-search="${esc(searchKey)}" class="artifact-row-tr${overflow}"><td><div class="artifact-row">${artifactTypeBadge(a.path)} ${esc(a.label)}</div></td><td class="artifact-path-cell" title="${esc(a.path)}">${esc(a.path)}</td><td><div class="artifact-actions">${viewBtn}<button onclick="editArtifact('${exp.id}','${escJsAttr(a.label)}','${escJsAttr(a.path)}')">edit</button><button class="art-del" onclick="deleteArtifact('${exp.id}','${escJsAttr(a.label)}','${escJsAttr(a.path)}')">del</button></div></td></tr>`;
  }).join('');
  const artFilterHtml = artTotal > 10
    ? `<div style="margin-bottom:6px"><input type="text" class="artifact-filter-input" id="art-filter-${exp.id}" placeholder="Filter artifacts..." oninput="filterArtifacts('${exp.id}', this.value)"></div>`
    : '';
  const artTruncateNotice = artTruncated
    ? `<div class="artifact-truncate-notice" id="art-truncate-${exp.id}">
         <span>Showing ${ARTIFACT_TRUNCATE_THRESHOLD} of ${artTotal} artifacts.</span>
         <button onclick="showAllArtifacts('${exp.id}')">Show all ${artTotal}</button>
       </div>`
    : '';
  const artTableClass = artTruncated ? 'params-table truncated' : 'params-table';

  const addArtifactForm = `<div class="artifact-add-form" id="add-artifact-form-${exp.id}">
    <input type="text" id="art-label-${exp.id}" placeholder="Label (e.g. model_v2)" style="width:210px">
    <input type="text" id="art-path-${exp.id}" placeholder="Path (e.g. outputs/model.pt)" style="width:280px">
    <button onclick="addArtifact('${exp.id}')">+ Add Artifact</button>
  </div>`;

  const logResultForm = `<div class="artifact-add-form" style="margin-top:8px;align-items:center;gap:4px" id="log-result-form-${exp.id}">
    <input type="text" id="result-key-${exp.id}" list="metric-suggestions-${exp.id}" placeholder="Metric key" style="width:150px" autocomplete="off">
    <datalist id="metric-suggestions-${exp.id}"></datalist>
    <input type="text" id="result-val-${exp.id}" placeholder="Value" style="width:80px" onkeydown="if(event.key==='Enter')logMetric('${exp.id}')">
    <input type="text" id="result-step-${exp.id}" placeholder="Step" style="width:55px;font-size:12px" title="Optional step number">
    <button onclick="logMetric('${exp.id}')">+ Log</button>
    <button onclick="openManageResultTypes()" style="background:transparent;color:var(--muted);border:none;font-size:16px;padding:0 4px;cursor:pointer;line-height:1" title="Manage metric types">&#9881;</button>
  </div>`;

  // Section blocks (built by dedicated helpers to keep this function readable)
  const codeHtml = _buildCodeSection(codeChanges);
  const varHtml = _buildVarSection(varChanges);
  const datasetsHtml = _buildDatasetsSection(exp.datasets);

  // Diff. `diffData.sentinel` is the server's classification ('compacted',
  // 'capture_failed', 'unavailable') — a marker is a status, never diff text.
  let diffHtml = '';
  const diffCompacted = diffData.sentinel === 'compacted';
  if (diffData.diff) {
    if (diffCompacted) {
      diffHtml = _diffNotice(esc(diffData.diff), diffData.commit
        ? 'To recover: git diff ' + esc(diffData.commit) + '~1 ' + esc(diffData.commit)
        : '');
    } else if (diffData.sentinel === 'capture_failed') {
      diffHtml = _diffNotice('Uncommitted changes could not be captured for this run',
        'git diff failed at capture time — not the same as a clean tree');
    } else if (diffData.sentinel === 'unavailable') {
      diffHtml = _diffNotice('The stored diff for this run is no longer available',
        'its deduplicated body was removed — not the same as a clean tree');
    } else {
      diffHtml = _renderUnifiedDiff(diffData.diff);
    }
  }

  // Reproduce box — show the command in the user's preferred form (plain
  // `python …` vs tracked `exptrack run …`) with a toggle when both apply.
  let reproHtml;
  if (exp.command) {
    const reproCmd = _preferredReproForm(exp.command);
    const alt = _reproFormAlt(reproCmd);
    const toggleBtn = alt
      ? '<button class="copy-btn" onclick="toggleReproduceForm()" title="Switch between plain python and tracked exptrack run">⇄ ' + (_reproIsTracked(reproCmd) ? 'python' : 'exptrack') + '</button>'
      : '';
    reproHtml = '<div class="reproduce-box"><div class="reproduce-header"><span class="label">Reproduce</span><span>'
      + toggleBtn
      + '<button class="copy-btn" onclick="saveReproduceToCommands(\'' + exp.id + '\')" title="Save to Commands notepad">&gt;_ Save</button>'
      + '<button class="copy-btn" data-cmd="' + esc(reproCmd).replace(/"/g, '&quot;') + '" onclick="navigator.clipboard.writeText(this.dataset.cmd).then(()=>owlSay(\'Copied!\'))">Copy</button>'
      + '</span></div><code class="reproduce-cmd editable-hint" id="detail-command" ondblclick="startDetailCommandEdit(\'' + exp.id + '\')" title="Double-click to edit">'
      + esc(reproCmd) + '</code></div>';
  } else {
    reproHtml = '<div class="reproduce-box"><div class="reproduce-header"><span class="label">Reproduce</span></div><code class="reproduce-cmd editable-hint" id="detail-command" ondblclick="startDetailCommandEdit(\'' + exp.id + '\')" title="Double-click to add command" style="color:var(--muted);cursor:pointer">double-click to add command</code></div>';
  }

  const expTags = exp.tags || [];
  const tagsHtml = '<span class="detail-tags-inline" id="detail-tags-area">' +
    (expTags.length
      ? expTags.map(t => '<span class="tag-removable">#' + esc(t) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteTagInline(\'' + exp.id + '\',\'' + escJsAttr(t) + '\')" title="Remove tag from this experiment">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-tag-input-area"></span>' +
    '</span>';

  const expStudies = exp.studies || [];
  const studiesDetailHtml = '<span class="detail-tags-inline" id="detail-studies-area">' +
    (expStudies.length
      ? expStudies.map(g => '<span class="tag-removable" style="background:rgba(44,90,160,0.1);color:var(--blue)">' + esc(g) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteStudyInline(\'' + exp.id + '\',\'' + escJsAttr(g) + '\')" title="Remove study">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-study-input-area"></span>' +
    '</span>';

  // Session origin back-link: when a run came from (or is linked to) a Session
  // Trees node, show a breadcrumb back to the session/checkpoint/branch so the
  // run can be traced to its exploratory context (link was tree→exp only).
  const so = exp.session_origin;
  const sessionOriginHtml = so ? (
    '<div class="session-origin-banner" onclick="openSessionNode(\'' +
      escJsAttr(so.session_id) + '\',\'' + escJsAttr(so.node_id) + '\')" ' +
      'title="Open this run&#39;s session node">' +
      '<span class="so-icon">☰</span>' +
      '<span class="so-text">From session <strong>' + esc(so.session_name) + '</strong>' +
      // The session can be in the Trash while this run stays live — it's then
      // absent from the sessions list, so without this the banner points at
      // something the user can't otherwise reach or account for.
      (so.session_deleted ? ' <span class="so-trashed">in Trash</span>' : '') +
      (so.node_type && so.node_type !== 'root' ? ' · <span class="so-type">' + esc(so.node_type) + '</span>' : '') +
      (so.lineage && so.lineage.length ? ' · ' + so.lineage.map(esc).join(' → ') : '') +
      '</span><span class="so-go">view tree →</span></div>'
  ) : '';

  // Branch context: the other experiments tried from the same parent checkpoint,
  // with their captured results — so a promoted run keeps the exploratory
  // context it came out of (what else was tried, how it compared).
  const _sibs = (so && so.siblings) || [];
  const branchContextHtml = (so && _sibs.filter(x => !x.is_this).length) ? (
    '<div class="branch-context">' +
      '<div class="bc-title">Branches tried from the same checkpoint</div>' +
      _sibs.map(s => {
        const cls = 'bc-sib' + (s.is_this ? ' this' : '');
        const nameL = '<a class="bc-sib-name" onclick="openSessionNode(\'' +
          escJsAttr(so.session_id) + '\',\'' + escJsAttr(s.node_id) + '\');return false">' +
          esc(s.label || '(unlabeled)') + '</a>';
        const tag = s.is_this ? '<span class="bc-sib-tag this">this run</span>'
          : (s.node_type === 'abandoned' ? '<span class="bc-sib-tag ab">abandoned</span>' : '');
        const res = s.result ? '<span class="bc-sib-res" title="' + esc(s.result) + '">⤷ ' + esc(s.result) + '</span>' : '';
        const expL = s.exp_id ? '<a class="bc-sib-exp" onclick="showDetail(\'' +
          escJsAttr(s.exp_id) + '\');return false">→ exp ' + esc(s.exp_id.slice(0, 8)) + '</a>' : '';
        return '<div class="' + cls + '">' + nameL + tag + res + expL + '</div>';
      }).join('') +
    '</div>'
  ) : '';

  // Failure traceback: when a run failed, show the full captured traceback
  // (file + line) in a prominent panel so the cause is visible without
  // digging through the params table or the stderr.log file.
  const errorHtml = (exp.status === 'failed' && exp.error) ? (
    '<div class="error-panel"><div class="error-panel-head">' +
      '<span class="error-panel-icon">✕</span> Run failed' +
      '<button class="copy-btn" data-tb="' + esc(exp.error).replace(/"/g,'&quot;') +
      '" onclick="navigator.clipboard.writeText(this.dataset.tb).then(()=>owlSay(\'Copied!\'))">Copy</button>' +
      '</div><pre class="error-panel-tb">' + esc(exp.error) + '</pre></div>'
  ) : '';

  const _restoreRename = _preserveActiveRename();
  document.getElementById('detail-panel').innerHTML = `
    <div class="detail" style="border:none;padding:4px 16px;margin:0">
      <!-- Filmstrip: flip through runs in the current list -->
      <div id="detail-filmstrip" class="detail-filmstrip"></div>

      <!-- Summary bar -->
      <div class="detail-summary">
        <span class="sum-item"><strong class="status-${exp.status}">${exp.status}</strong>${exp.status === 'running' ? ' <span class="live-badge" id="live-badge"><span class="live-dot"></span>live</span>' : ''}</span>
        <span class="sum-sep">|</span>
        <span class="sum-item">Branch: <strong>${esc(exp.git_branch||'--')}</strong></span>
        <span class="sum-item">Commit: <strong>${esc((exp.git_commit||'--').slice(0,7))}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">Started: <strong>${fmtDt(exp.created_at)}</strong></span>
        <span class="sum-item">Duration: <strong>${fmtDur(exp.duration_s)}</strong></span>
        <span class="sum-sep">|</span>
        <span class="sum-item">${Object.keys(regularParams).length} params</span>
        <span class="sum-item">${exp.metrics.length} metrics</span>
        <span class="sum-item">${exp.artifacts.length} artifacts</span>
      </div>

      <!-- "What changed vs the previous run of this script" strip (L2) -->
      <div id="vs-prev-strip" class="vs-prev-strip" style="display:none"></div>

      <!-- Header with name + actions -->
      <div class="detail-header">
        <h2 id="detail-name" class="editable-hint" data-rename-slot="${exp.id}" ondblclick="startInlineRename('${exp.id}',this)" title="Double-click to rename">${esc(exp.name)}</h2>
        <div class="detail-actions">
          ${exp.status === 'running' ? `<button class="action-btn primary" onclick="finishExp('${exp.id}')">Finish Run</button>` : ''}
          <span style="position:relative;display:inline-block">
            <button class="action-btn primary" onclick="toggleDetailExport(this)">Export ▼</button>
            <div class="export-dropdown-menu" style="display:none">
              <button class="action-btn" onclick="closeDetailExport(this);downloadExportFmt('${exp.id}','json')">JSON</button>
              <button class="action-btn" onclick="closeDetailExport(this);downloadExportFmt('${exp.id}','markdown')">Markdown</button>
              <button class="action-btn" onclick="closeDetailExport(this);downloadExportFmt('${exp.id}','csv')">CSV</button>
              <button class="action-btn" onclick="closeDetailExport(this);downloadExportFmt('${exp.id}','tsv')">TSV</button>
              <button class="action-btn" onclick="closeDetailExport(this);downloadExportFmt('${exp.id}','plain')">Plain Text</button>
            </div>
          </span>
          <span style="position:relative;display:inline-block">
            <button class="action-btn" onclick="toggleDetailExport(this)">Copy ▼</button>
            <div class="export-dropdown-menu" style="display:none">
              <button class="action-btn" onclick="closeDetailExport(this);copyExportFmt('${exp.id}','json')">JSON</button>
              <button class="action-btn" onclick="closeDetailExport(this);copyExportFmt('${exp.id}','markdown')">Markdown</button>
              <button class="action-btn" onclick="closeDetailExport(this);copyExportFmt('${exp.id}','plain')">Plain Text</button>
            </div>
          </span>
          ${diffData.diff && !diffCompacted ? `<button class="action-btn" onclick="exportDiff('${exp.id}')">Export Diff</button>` : ''}
          ${_compactBtnHtml(exp)}
          <button class="action-btn danger" onclick="deleteExp('${exp.id}','${escJsAttr(exp.name)}')">Delete</button>
          <button class="close-btn" onclick="showWelcome()" title="Back to list">&times;</button>
        </div>
      </div>

      ${sessionOriginHtml}
      ${branchContextHtml}
      ${errorHtml}

      <div class="tabs" id="detail-tabs">
        <button class="tab active" onclick="switchDetailTab('overview','${exp.id}')">Overview</button>
        <button class="tab" onclick="switchDetailTab('timeline','${exp.id}')">Timeline</button>
        <button class="tab" onclick="switchDetailTab('charts','${exp.id}')">Charts</button>
        <button class="tab" onclick="switchDetailTab('images','${exp.id}')">Images</button>
        <button class="tab" onclick="switchDetailTab('logs','${exp.id}')">Data Files</button>
        <button class="tab" onclick="switchDetailTab('compare-within','${exp.id}')">Compare Within</button>
        <button class="tab" onclick="switchDetailTab('confusion','${exp.id}')" title="Calculate accuracy, precision, recall, F1 from a confusion matrix">Confusion Matrix</button>
      </div>

      <div id="detail-tab-overview">
        ${whatChangedHtml}
        <!-- Two-column grid -->
        <div class="detail-grid">
          <!-- Left column: info + params -->
          <div>
            <div class="info-grid">
              <span class="label">ID</span><span>${exp.id}</span>
              <span class="label">Script</span><span id="detail-script" class="editable-hint" ondblclick="startDetailScriptEdit('${exp.id}',this)" title="Double-click to edit" style="font-size:12px">${esc(exp.script||'--')}</span>
              <span class="label">Host</span><span>${exp.hostname||'--'}</span>
              <span class="label">Python</span><span>${exp.python_ver||'--'}</span>
              <span class="label">Tags</span><span class="tag-list" id="detail-tags">${tagsHtml}</span>
              <span class="label">Studies</span><span class="tag-list" id="detail-studies">${studiesDetailHtml}</span>
              <span class="label">Stage</span><span id="detail-stage" class="editable-hint" ondblclick="startDetailStageEdit('${exp.id}',this)" title="Double-click to edit stage">${exp.stage != null ? esc(String(exp.stage)) + (exp.stage_name ? ' (' + esc(exp.stage_name) + ')' : '') : '<span style="color:var(--muted)">click to set stage</span>'}</span>
              <span class="label">Notes</span><span id="detail-notes" class="detail-notes-inline editable-hint" ondblclick="startDetailNoteEdit('${exp.id}',this)" title="Double-click to edit">${exp.notes ? esc(exp.notes) : '<span style="color:var(--muted)">double-click to add notes</span>'}</span>
              <span class="label">Uncommitted</span><span>${diffData.diff ? (diffCompacted ? '<span style="color:var(--yellow)">' + esc(diffData.diff.split(' — ')[1] || 'compacted') + '</span>' : '<span style="color:var(--green)">' + exp.diff_lines + ' lines</span> <button class="action-btn" style="font-size:11px;padding:1px 8px;margin-left:6px" onclick="exportDiff(\'' + exp.id + '\')">Export</button><button class="action-btn" style="font-size:11px;padding:1px 8px;margin-left:4px" onclick="compactDiff(\'' + exp.id + '\')">Compact</button>') : '<span style="color:var(--muted)">none (all changes were committed)</span>'}</span>
            </div>
            ${reproHtml}
            <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">Params (${Object.keys(regularParams).length})<span class="section-actions" onclick="event.stopPropagation()"><button class="copy-btn" title="Copy as a markdown table — pastes into lab notebooks, Obsidian, GitHub, Jupyter markdown cells" onclick="copyExportFmt('${exp.id}','params-md')">Copy</button></span></h2>
            <div class="section-body">
            ${paramRows ? '<table class="params-table"><tr><th>Key</th><th>Value</th><th>Source</th></tr>'+paramRows+'</table>' : '<p style="color:var(--muted);font-size:13px">No params yet.</p>'}
            ${addParamForm}
            </div>
            ${datasetsHtml}
            ${varHtml}
          </div>
          <!-- Right column: metrics + charts + artifacts -->
          <div>
            <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">Metrics (${exp.metrics.length})</h2>
            <div class="section-body">
            ${metricRows || '<p style="color:var(--muted);font-size:13px">No metrics yet.</p>'}
            ${logResultForm}
            <div id="overview-chart-preview" style="margin-top:12px"></div>
            </div>
            <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">Artifacts (${exp.artifacts.length})</h2>
            <div class="section-body">
            ${artTotal ? artFilterHtml + '<table class="' + artTableClass + '" id="artifact-table-' + exp.id + '"><thead><tr><th>File</th><th>Path</th><th style="width:80px"></th></tr></thead><tbody>' + artRows + '</tbody></table>' + artTruncateNotice : '<p style="color:var(--muted);font-size:13px">No artifacts yet.</p>'}
            ${addArtifactForm}
            </div>
          </div>
        </div>
        <!-- Full-width sections below the grid -->
        <div style="margin-top:20px">
          ${codeHtml}
          ${diffHtml ? '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">'+(diffCompacted ? 'Uncommitted Changes (compacted)' : 'Uncommitted Changes ('+exp.diff_lines+' lines)' + ' <span style="float:right;font-size:12px;font-weight:normal">' + '<button class="action-btn" style="padding:1px 8px" onclick="event.stopPropagation();exportDiff(\'' + exp.id + '\')">Export</button>' + '<button class="action-btn" style="padding:1px 8px;margin-left:4px" onclick="event.stopPropagation();compactDiff(\'' + exp.id + '\')">Compact</button>' + '</span>')+'</h2><div class="section-body"><div class="diff-view">'+diffHtml+'</div></div>' : ''}
        </div>
      </div>

      <div id="detail-tab-timeline" style="display:none"></div>
      <div id="detail-tab-charts" style="display:none"></div>
      <div id="detail-tab-images" style="display:none"></div>
      <div id="detail-tab-logs" style="display:none"></div>
      <div id="detail-tab-compare-within" style="display:none"></div>
      <div id="detail-tab-confusion" style="display:none"></div>
    </div>
  `;
  _restoreRename();

  // Filmstrip of the current run list, active card centered.
  renderFilmstrip(exp.id);

  // Populate the "vs previous run" strip (async; guarded against navigation).
  loadVsPrevious(exp.id);

  // Wire up inline tag input in detail view
  const tagInputArea = document.getElementById('detail-tag-input-area');
  if (tagInputArea) {
    const detailTags = [...(exp.tags || [])];
    const { wrapper, input } = createTagInput(exp.id, detailTags, null, () => {
      loadExperiments().then(() => refreshDetail(exp.id));
    }, { placeholder: '+ add tag', style: 'width:120px;font-size:13px;padding:4px 6px' });
    tagInputArea.appendChild(wrapper);
  }

  // Wire up inline study input in detail view
  const studyInputArea = document.getElementById('detail-study-input-area');
  if (studyInputArea) {
    const detailStudies = [...(exp.studies || [])];
    const { wrapper: sWrapper, input: sInput } = createStudyInput(exp.id, detailStudies, null, () => {
      loadExperiments().then(() => refreshDetail(exp.id));
    }, { placeholder: '+ add study', style: 'width:130px;font-size:13px;padding:4px 6px' });
    studyInputArea.appendChild(sWrapper);
  }

  // Cache metrics data for Charts tab and render overview preview
  _chartsMetricsData = metricsData;
  renderOverviewChartPreview(metricsData);

  // Populate result type dropdown
  populateResultTypeDropdown(exp.id);

  // Start auto-refresh if experiment is running
  if (exp.status === 'running') {
    startAutoRefresh(exp.id);
  } else {
    stopAutoRefresh();
  }
}

// ── Experiment filmstrip ─────────────────────────────────────────────────────
// A horizontal strip of the runs in the current filtered+sorted list, rendered
// at the top of the detail view so you can flip between runs without going back
// to the table. The open run is highlighted and centered; each card shows a
// primary-metric value + a delta vs its older neighbor so the change reads at a
// glance. Reuses getFilteredExperiments() (same order as the table/sidebar) and
// the shared metricDelta() helper — no new fetch.

// Primary metric key: the active "Sort by metric" key when set, else the first
// metric key present on any run in the list.
function _filmstripMetricKey(exps) {
  if (typeof sortCol === 'string' && sortCol.startsWith('metric:')) return sortCol.slice(7);
  for (const e of exps) {
    const keys = e.metrics ? Object.keys(e.metrics) : [];
    if (keys.length) return keys[0];
  }
  return null;
}

function _fsMetricValue(e, key) {
  if (!key || !e.metrics || !e.metrics[key]) return null;
  const v = Number(e.metrics[key].value);
  return isNaN(v) ? null : v;
}

// Compact delta badge for a filmstrip card (arrow + percent, or a short absolute
// delta when the baseline is 0). The full metricDelta() form used by Compare and
// the "What changed" card is too wide for a 150px card, so this trims it to fit.
// Direction/colour semantics come from the shared _deltaVisual(), so a
// lower-is-better metric (loss) colours the same here as everywhere else.
function _fsDeltaHtml(prev, val, key, dir) {
  const d = val - prev;
  if (d === 0) return '';
  const vis = _deltaVisual(key, d, dir);
  const txt = prev !== 0
    ? (d > 0 ? '+' : '') + (d / Math.abs(prev) * 100).toFixed(1) + '%'
    : (d > 0 ? '+' : '') + d.toFixed(3);
  return '<span style="color:' + vis.color + '" title="' + esc(vis.title) + '">'
    + vis.arrow + ' ' + txt + '</span>';
}

// The delta on each card is "vs the chronologically previous run", so the
// baseline must be picked by time — not by list position. `exps[i+1]` is only
// the older run under the default created_at-desc sort; with "Sort by metric"
// on (or any pin reordering the list) it becomes an arbitrary run while the
// badge still reads as a chronological delta. Resolve every run's predecessor in
// one time-ordered pass (a per-card scan would be O(N^2) over the whole list).
function _fsPrevByTime(exps) {
  const dated = [];
  for (const e of exps) {
    const d = expDate(e.created_at);
    if (d && !isNaN(d)) dated.push({exp: e, t: d.getTime()});
  }
  dated.sort((a, b) => a.t - b.t);
  const prev = new Map();
  for (let i = 1; i < dated.length; i++) {
    // Skip back over runs sharing this timestamp — the baseline must be strictly
    // older, or two runs logged in the same second would each be the other's.
    let j = i - 1;
    while (j >= 0 && dated[j].t === dated[i].t) j--;
    if (j >= 0) prev.set(dated[i].exp.id, dated[j].exp);
  }
  return prev;
}

function renderFilmstrip(currentId) {
  const strip = document.getElementById('detail-filmstrip');
  if (!strip) return;
  const exps = getFilteredExperiments();
  // A single run has nothing to flip through.
  if (exps.length < 2) { strip.innerHTML = ''; strip.style.display = 'none'; return; }
  strip.style.display = '';
  const mkey = _filmstripMetricKey(exps);
  const curIdx = exps.findIndex(e => e.id === currentId);
  // Every card shares one metric, so resolve its polarity (a localStorage read)
  // and each run's chronological predecessor once for the whole strip.
  const mdir = mkey ? metricGoodDirection(mkey) : 1;
  const prevByTime = mkey ? _fsPrevByTime(exps) : null;

  const cards = exps.map((e, i) => {
    const active = e.id === currentId;
    const val = _fsMetricValue(e, mkey);
    // Delta vs the chronologically previous run (not merely the next card —
    // list order changes with sorting/pinning, run order doesn't).
    let deltaHtml = '';
    if (mkey && val !== null) {
      const prevExp = prevByTime.get(e.id);
      const prev = prevExp ? _fsMetricValue(prevExp, mkey) : null;
      if (prev !== null) deltaHtml = _fsDeltaHtml(prev, val, mkey, mdir);
    }
    const metricLine = mkey
      ? '<span class="fs-metric">' + esc(abbrevMetric(mkey)) + ' ' + (val !== null ? fmtMetricVal(val) : '--') + '</span>'
      : '<span class="fs-metric fs-metric-none">no metrics</span>';
    return '<div class="fs-card' + (active ? ' active' : '') + '" data-fs-id="' + esc(e.id) + '"' +
      ' onclick="refreshDetail(\'' + escJsAttr(e.id) + '\',{keepSidebar:true})" title="' + escJsAttr(e.name) + '">' +
      '<div class="fs-card-top"><span class="status-dot status-' + esc(e.status) + '"></span>' +
      '<span class="fs-name">' + esc(e.name) + '</span></div>' +
      '<div class="fs-card-bot">' + metricLine +
        (deltaHtml ? '<span class="fs-delta">' + deltaHtml + '</span>' : '') + '</div>' +
      '</div>';
  }).join('');

  const counter = curIdx >= 0
    ? '<span class="fs-counter">' + (curIdx + 1) + ' / ' + exps.length + '</span>' : '';
  strip.innerHTML =
    '<button class="fs-nav" onclick="filmstripStep(-1)" title="Previous run (←)" aria-label="Previous run">‹</button>' +
    '<div class="fs-track" id="fs-track">' + cards + '</div>' +
    '<button class="fs-nav" onclick="filmstripStep(1)" title="Next run (→)" aria-label="Next run">›</button>' +
    counter;

  // Center the active card within the track only (no page scroll).
  const track = document.getElementById('fs-track');
  const activeEl = strip.querySelector('.fs-card.active');
  if (track && activeEl) {
    track.scrollLeft = activeEl.offsetLeft - (track.clientWidth - activeEl.clientWidth) / 2;
  }
}

// Step to the adjacent run in the current list. dir = -1 (previous/left) or
// +1 (next/right). No-op at either end.
function filmstripStep(dir) {
  const exps = getFilteredExperiments();
  const idx = exps.findIndex(e => e.id === currentDetailId);
  if (idx < 0) return;
  const next = idx + dir;
  if (next < 0 || next >= exps.length) return;
  refreshDetail(exps[next].id, {keepSidebar: true});
}

// ── "vs previous run" strip (L2) ─────────────────────────────────────────────

// The code diff behind the "What changed" card. The card answers "what did I do
// differently?" — params and metrics only got half of that, since the most
// common edit in the tweak-one-line loop is to the code itself. Fetched on
// demand (a run's snapshot can be hundreds of KB, and most visits don't open
// it) and rendered with the same word-level diff renderer the Compare view uses.
async function loadWhatChangedCode(prevId, curId, btn) {
  const box = btn.parentElement;
  const restore = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Loading…';
  const data = await api('/api/compare?id1=' + encodeURIComponent(prevId)
    + '&id2=' + encodeURIComponent(curId));
  if (!data || data.error) {
    btn.disabled = false;
    btn.textContent = restore;
    return;
  }
  // '' means neither run captured code to compare (no script snapshot, no
  // notebook cells) — say so rather than collapsing to an empty box.
  box.innerHTML = _renderCompareCodeDiff(data.code_diff)
    || '<p style="color:var(--muted);font-size:13px">No code captured for one of '
     + 'these runs, so there is nothing to diff. Scripts are snapshotted at run '
     + 'time; notebook runs compare their executed cells.</p>';
}

// The code chip. `source_changed` is this run's own code (the same snapshots and
// cells the Code-changes panel diffs); `code_changed` is the wider repository
// state, which moves when *any* tracked file differs. Reporting the wide one as
// "code changed" put an amber chip on a byte-identical rerun and contradicted
// the panel directly below it, so the two facts get two different chips.
function _vsCodeChip(d) {
  if (d.source_changed) {
    return '<span class="vs-chip vs-chip-code" title="This run\'s code differs from'
      + ' the previous run\'s — see Code changes below">code changed</span>';
  }
  if (!d.code_changed) return '';
  if (d.source_changed === false) {
    return '<span class="vs-chip vs-chip-repo" title="This run\'s own code is'
      + ' identical. Something else in the repository differed — another file, or a'
      + ' different commit.">repo changed elsewhere</span>';
  }
  // source_changed === null: neither run captured code to compare, so the
  // repository signal is all we have. Say only what it supports.
  return '<span class="vs-chip vs-chip-repo" title="The repository state differed.'
    + ' Neither run captured code, so exptrack cannot say whether this run\'s own'
    + ' code changed.">repo changed</span>';
}

// "Previous" means the next-older run of the same script — spelled out here
// because the newest-first list puts that run below the current one.
const _VS_PREV_LABEL = '<span class="vs-prev-label" title="Compared against the'
  + ' last run of this script started before this one">vs previous run</span>';

async function loadVsPrevious(id) {
  let d;
  try {
    d = await api('/api/run-delta/' + id);
  } catch (e) { return; }
  // Bail if the user navigated away while we were fetching.
  if (currentDetailId !== id) return;
  const strip = document.getElementById('vs-prev-strip');
  if (!strip) return;
  if (!d || d.error || !d.previous) { strip.style.display = 'none'; return; }
  const pcs = d.param_changes || [];
  const mcs = d.metric_changes || [];
  if (pcs.length === 0 && mcs.length === 0 && !d.code_changed) {
    strip.innerHTML = _VS_PREV_LABEL
      + '<span class="vs-prev-none">no params, code, or metrics changed</span>'
      + _vsPrevLink(d.previous, d.current_created_at);
    strip.style.display = '';
    return;
  }
  let chips = '';
  for (const c of pcs.slice(0, 6)) {
    chips += '<span class="vs-chip vs-chip-param">' + esc(c.key) + ' '
      + esc(_vsFmt(c.from)) + '→' + esc(_vsFmt(c.to)) + '</span>';
  }
  if (pcs.length > 6) chips += '<span class="vs-chip">+' + (pcs.length - 6) + ' params</span>';
  chips += _vsCodeChip(d);
  for (const c of mcs.slice(0, 6)) {
    // Colour by better/worse (polarity-aware), not by the sign of the change —
    // a rising loss is a regression and must not read green.
    let cls = 'vs-chip vs-chip-metric', arrow = '', title = '';
    if (c.delta != null && c.delta !== 0) {
      const vis = _deltaVisual(c.key, c.delta);
      cls += vis.better ? ' vs-chip-better' : ' vs-chip-worse';
      arrow = c.delta > 0 ? ' ▲' : ' ▼';
      title = ' title="' + esc(vis.title) + '"';
    }
    // Chips round to 4dp, which prints a genuine 1e-7 move as "0.5→0.5" next to
    // an arrow claiming it moved — widen just that chip until the two differ.
    const [sf, st] = _vsFmtPair(c.from, c.to);
    chips += '<span class="' + cls + '"' + title + '>' + esc(c.key) + ' '
      + esc(sf) + '→' + esc(st) + arrow + '</span>';
  }
  strip.innerHTML = _VS_PREV_LABEL + chips
    + _vsPrevLink(d.previous, d.current_created_at);
  strip.style.display = '';
}

// A failed baseline is still the right baseline — "it broke, I fixed it, what
// changed?" is the loop this card exists for — but its metrics stop wherever it
// crashed, so an unqualified "acc 0.41 → 0.87" reads as a result that was never
// measured. Both surfaces say so instead of hiding the comparison.
function _baselineFailedTag(status) {
  if (status !== 'failed') return '';
  return '<span class="wc-baseline-failed" title="The run being compared against'
    + ' failed. Its parameters and code are exact; its metrics stop where it'
    + ' crashed.">failed</span>';
}

function _baselineFailedNote(status, metricRowCount) {
  if (status !== 'failed' || !metricRowCount) return '';
  return '<p class="wc-baseline-warn">The previous run failed, so the metric'
    + ' values below are wherever it stopped — not a finished result. Parameter'
    + ' and code changes are unaffected.</p>';
}

// The baseline chip carries its start time, not just its name. "Previous" is
// ambiguous on its own: the run list is newest-first, so the run this compares
// against sits *below* the current row and reads as the next one — the date is
// what makes it checkable at a glance.
function _vsPrevLink(prev, curCreatedAt) {
  if (!prev || !prev.id) return '';
  const label = prev.name || prev.id.slice(0, 6);
  const when = relEarlier(prev.created_at, curCreatedAt);
  const full = prev.created_at ? ' (' + fmtDtFull(prev.created_at) + ')' : '';
  return '<a class="vs-prev-open" href="#" onclick="showDetail(\'' + escJsAttr(prev.id)
    + '\');return false" title="Open this run — the last run of this script started before'
    + ' the one you\'re viewing' + esc(full) + '">'
    + esc(label) + (when ? ' <span class="vs-prev-when">' + esc(when) + '</span>' : '')
    + _baselineFailedTag(prev.status)
    + '</a>';
}

// How much earlier the baseline ran, e.g. "2 min earlier", "2 days earlier".
// An absolute timestamp can't answer the question this needs to answer: `fmtDt`
// only resolves to the minute, so two runs launched seconds apart print the same
// string, and the newest-first list puts the older run *below* the current row —
// leaving no way to tell which direction the comparison runs. A relative age
// can't be misread.
function relEarlier(prevIso, curIso) {
  if (!prevIso || !curIso) return '';
  const a = expDate(prevIso), b = expDate(curIso);
  if (!a || !b || isNaN(a) || isNaN(b)) return '';
  const secs = Math.round((b.getTime() - a.getTime()) / 1000);
  if (secs < 0) return 'started LATER — not a previous run';   // never expected
  const units = [['day', 86400], ['hr', 3600], ['min', 60]];
  for (const [name, size] of units) {
    if (secs >= size) {
      const n = Math.round(secs / size);
      return n + ' ' + name + (n === 1 || name === 'min' || name === 'hr' ? '' : 's') + ' earlier';
    }
  }
  // Sub-second gaps ("0s earlier" reads as a contradiction) — back-to-back runs.
  return secs >= 1 ? secs + 's earlier' : 'just before';
}

// Both sides of a chip, at enough precision to differ (see fmtMetricPair).
function _vsFmtPair(a, b) {
  const sa = _vsFmt(a), sb = _vsFmt(b);
  if (sa !== sb || typeof a !== 'number' || typeof b !== 'number') return [sa, sb];
  return fmtMetricPair(a, b);
}

function _vsFmt(v) {
  if (v === null || v === undefined) return '∅';
  if (typeof v === 'number') return (Math.abs(v) >= 1e-4 && Math.abs(v) < 1e6)
    ? String(Math.round(v * 10000) / 10000) : v.toExponential(2);
  const s = String(v);
  return s.length <= 20 ? s : s.slice(0, 18) + '…';
}

// ── Auto-refresh for running experiments ────────────────────────────────────

let _autoRefreshExpId = null;
let _autoRefreshMetricCount = 0;

function startAutoRefresh(expId) {
  stopAutoRefresh();
  _autoRefreshExpId = expId;
  _autoRefreshMetricCount = 0;
  autoRefreshTimer = setInterval(() => _autoRefreshPoll(), 5000);
}

function stopAutoRefresh() {
  if (autoRefreshTimer) {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
  _autoRefreshExpId = null;
  const badge = document.getElementById('live-badge');
  if (badge) badge.remove();
}

// ── Param mutations (manual params only) ────────────────────────────────────

async function addParam(id) {
  const keyEl = document.getElementById('param-key-' + id);
  const valEl = document.getElementById('param-val-' + id);
  if (!keyEl || !valEl) return;
  const key = keyEl.value.trim();
  const value = valEl.value;
  if (!key) { owlSay('Enter a param key'); return; }
  const d = await postApi('/api/experiment/' + id + '/add-param', {key, value});
  if (d.ok) {
    keyEl.value = ''; valEl.value = '';
    refreshDetail(id);
    loadExperiments();
    owlSay('Added param ' + key);
  } else {
    alert(d.error || 'Failed to add param');
  }
}

async function deleteParam(id, key) {
  if (!confirm('Delete param "' + key + '"?')) return;
  const d = await postApi('/api/experiment/' + id + '/delete-param', {key});
  if (d.ok) { refreshDetail(id); loadExperiments(); }
  else alert(d.error || 'Failed to delete param');
}

function startParamEdit(id, key, td) {
  if (td.querySelector('input')) return;
  const savedHtml = td.innerHTML;
  // td contains JSON.stringify(value) — pull current text as the editing seed
  const currentText = td.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text';
  input.value = currentText;
  input.style.cssText = 'width:100%;font-size:13px;padding:2px 4px;font-family:inherit;box-sizing:border-box';
  td.innerHTML = '';
  td.appendChild(input);
  input.focus();
  input.select();
  const restore = () => { td.innerHTML = savedHtml; };
  const save = async () => {
    input.onblur = null;
    const val = input.value;
    if (val.trim() === currentText) { restore(); return; }
    const d = await postApi('/api/experiment/' + id + '/edit-param', {key, value: val});
    if (d.ok) { refreshDetail(id); loadExperiments(); }
    else { restore(); alert(d.error || 'Failed'); }
  };
  input.onblur = save;
  input.onkeydown = (e) => {
    if (e.key === 'Enter') { e.preventDefault(); save(); }
    else if (e.key === 'Escape') { input.onblur = null; restore(); }
  };
}

function startParamRename(id, key, td) {
  if (td.querySelector('input')) return;
  const savedHtml = td.innerHTML;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = key;
  input.style.cssText = 'width:100%;padding:2px 4px;font:inherit;border:1px solid var(--blue);border-radius:3px;background:var(--card-bg);color:var(--fg)';
  td.innerHTML = '';
  td.appendChild(input);
  input.focus();
  input.select();
  const finish = async (save) => {
    input.onblur = null;
    if (save) {
      const newKey = input.value.trim();
      if (newKey && newKey !== key) {
        const d = await postApi('/api/experiment/' + id + '/rename-param', {old_key: key, new_key: newKey});
        if (d.ok) { refreshDetail(id); loadExperiments(); owlSay('Renamed: ' + newKey); return; }
        else alert(d.error || 'Failed to rename');
      }
    }
    td.innerHTML = savedHtml;
  };
  input.onkeydown = e => { if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); };
  input.onblur = () => finish(false);
}

async function _autoRefreshPoll() {
  if (!_autoRefreshExpId || currentDetailId !== _autoRefreshExpId) {
    stopAutoRefresh();
    return;
  }
  try {
    const exp = await api('/api/experiment/' + _autoRefreshExpId);
    if (exp.error) return;

    // Check if experiment finished
    if (exp.status !== 'running') {
      stopAutoRefresh();
      refreshDetail(_autoRefreshExpId);
      return;
    }

    // Check if metrics or timeline changed — refresh relevant tabs
    const newMetricCount = exp.metrics.reduce((s, m) => s + (m.n || 1), 0);
    const metricsChanged = newMetricCount !== _autoRefreshMetricCount;
    _autoRefreshMetricCount = newMetricCount;

    if (metricsChanged) {
      // Refresh the active tab if it shows metrics
      if (currentDetailTab === 'overview' || currentDetailTab === 'charts') {
        refreshDetail(_autoRefreshExpId);
      }
    }
  } catch (e) {
    // Silently ignore poll errors
  }
}
