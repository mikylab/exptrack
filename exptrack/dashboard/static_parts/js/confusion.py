"""Confusion matrix calculator tab — multiple named matrices, compare, save server-side."""

JS_CONFUSION = r"""
// ── Confusion Matrix calculator ──────────────────────────────────────────────
//
// Supports multiple named matrices per experiment, persisted server-side as
// a single JSON-encoded manual param. Each matrix carries its own palette
// and intensity. Compare two matrices side-by-side with metric diffs.

const _CONF_PALETTES = [
  {id: 'blue',   label: 'Blue',   rgb: [44, 90, 160]},
  {id: 'green',  label: 'Green',  rgb: [45, 125, 70]},
  {id: 'purple', label: 'Purple', rgb: [124, 58, 237]},
  {id: 'orange', label: 'Orange', rgb: [200, 110, 30]},
  {id: 'teal',   label: 'Teal',   rgb: [20, 140, 140]},
  {id: 'red',    label: 'Red',    rgb: [192, 57, 43]},
  {id: 'grey',   label: 'Grey',   rgb: [110, 110, 110]},
];

const _confState = {};   // expId -> {matrices, activeId, compareIds, saveTimer, dirty}

function _confLegacyKey(expId) { return 'exptrack:confusion:' + expId; }

// Best-effort flush of any pending debounced save when the tab is hidden
// or the page is unloaded — prevents losing edits made <400ms before nav.
if (typeof document !== 'undefined' && !window._confVisListener) {
  window._confVisListener = true;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) for (const id in _confState) _confFlushSave(id);
  });
  window.addEventListener('pagehide', () => {
    for (const id in _confState) _confFlushSave(id);
  });
}

function _confNewId() { return 'm_' + Math.random().toString(36).slice(2, 9); }

function _confNewMatrix(name, n) {
  n = n || 2;
  const labels = []; for (let i = 0; i < n; i++) labels.push(i === 0 ? 'neg' : (i === 1 ? 'pos' : 'class ' + i));
  const matrix = []; for (let i = 0; i < n; i++) { const r = []; for (let j = 0; j < n; j++) r.push(0); matrix.push(r); }
  return {id: _confNewId(), name: name || 'Matrix', n, labels, matrix, palette: 'blue', intensity: 1.0};
}

function _confEnsureShape(m) {
  const n = m.n;
  if (!Array.isArray(m.labels)) m.labels = [];
  while (m.labels.length < n) m.labels.push('class ' + m.labels.length);
  m.labels.length = n;
  if (!Array.isArray(m.matrix)) m.matrix = [];
  while (m.matrix.length < n) m.matrix.push([]);
  m.matrix.length = n;
  for (let i = 0; i < n; i++) {
    if (!Array.isArray(m.matrix[i])) m.matrix[i] = [];
    while (m.matrix[i].length < n) m.matrix[i].push(0);
    m.matrix[i].length = n;
  }
  if (!m.palette) m.palette = 'blue';
  if (m.intensity == null) m.intensity = 1.0;
}

function _confActive(expId) {
  const s = _confState[expId];
  if (!s) return null;
  return s.matrices.find(m => m.id === s.activeId) || s.matrices[0] || null;
}

function _confScheduleSave(expId) {
  const s = _confState[expId];
  if (!s) return;
  s.dirty = true;
  if (s.saveTimer) clearTimeout(s.saveTimer);
  s.saveTimer = setTimeout(() => _confFlushSave(expId), 400);
}

async function _confFlushSave(expId) {
  const s = _confState[expId];
  if (!s) return;
  s.saveTimer = null;
  if (!s.dirty) return;
  s.dirty = false;
  const payload = s.matrices.map(m => ({
    id: m.id, name: m.name, n: m.n, labels: m.labels, matrix: m.matrix,
    palette: m.palette, intensity: m.intensity,
  }));
  try {
    await postApi('/api/experiment/' + expId + '/save-confusion', {matrices: payload});
  } catch (e) {
    s.dirty = true;  // retry next time
  }
}

async function loadConfusionTab(expId) {
  const container = document.getElementById('detail-tab-confusion');
  if (!container) return;
  container.innerHTML = '<div class="conf-wrap"><p class="conf-hint">Loading…</p></div>';

  // Fetch server-side matrices first; fall back to migrating legacy
  // localStorage state if the server has nothing.
  let matrices = [];
  try {
    const resp = await api('/api/confusion/' + expId);
    matrices = (resp && Array.isArray(resp.matrices)) ? resp.matrices : [];
  } catch (e) { matrices = []; }

  if (matrices.length === 0) {
    try {
      const raw = localStorage.getItem(_confLegacyKey(expId));
      if (raw) {
        const legacy = JSON.parse(raw);
        if (legacy && legacy.matrix) {
          const m = _confNewMatrix('Matrix', legacy.n || 2);
          m.n = legacy.n || 2;
          m.labels = (legacy.labels || []).slice();
          m.matrix = (legacy.matrix || []).map(r => r.slice());
          _confEnsureShape(m);
          matrices = [m];
        }
      }
    } catch (e) {}
  }

  if (matrices.length === 0) {
    matrices = [_confNewMatrix('Matrix 1', 2)];
  }
  matrices.forEach(m => { if (!m.id) m.id = _confNewId(); _confEnsureShape(m); });

  _confState[expId] = {matrices, activeId: matrices[0].id, compareIds: null, saveTimer: null, dirty: false};
  _confRenderTab(expId);
}

function _confRenderTab(expId) {
  const container = document.getElementById('detail-tab-confusion');
  if (!container) return;
  const s = _confState[expId];
  if (!s) return;

  let html = '<div class="conf-wrap">';
  html += _confRenderTabsBar(expId);

  if (s.compareIds) {
    html += _confRenderCompare(expId);
  } else {
    html += _confRenderEditor(expId);
  }

  html += '</div>';
  container.innerHTML = html;
}

function _confRenderTabsBar(expId) {
  const s = _confState[expId];
  let html = '<div class="conf-tabs">';
  for (const m of s.matrices) {
    const active = (!s.compareIds && m.id === s.activeId) ? ' active' : '';
    html += '<button class="conf-tab' + active + '" onclick="confSelect(\'' + expId + '\',\'' + m.id + '\')" '
         +  'ondblclick="confRename(\'' + expId + '\',\'' + m.id + '\')" '
         +  'title="Click to view, double-click to rename">' + esc(m.name) + '</button>';
  }
  html += '<button class="conf-tab conf-tab-new" onclick="confAdd(\'' + expId + '\')" title="Add a new confusion matrix">+ New</button>';
  if (s.matrices.length >= 2) {
    const compareActive = s.compareIds ? ' active' : '';
    html += '<button class="conf-tab conf-tab-compare' + compareActive + '" onclick="confEnterCompare(\'' + expId + '\')" '
         +  'title="Compare two matrices side by side">Compare…</button>';
  }
  html += '</div>';
  return html;
}

function _confRenderEditor(expId) {
  const s = _confState[expId];
  const m = _confActive(expId);
  if (!m) return '';
  _confEnsureShape(m);

  let html = '<div class="conf-controls">';
  html += '<label>Name: <input type="text" value="' + esc(m.name) + '" id="conf-name-' + m.id + '" '
       +  'oninput="confSetName(\'' + expId + '\',\'' + m.id + '\',this.value)" maxlength="60"></label>';
  html += '<label>Classes: <input type="number" min="2" max="20" value="' + m.n + '" '
       +  'id="conf-n-' + m.id + '" onchange="confResize(\'' + expId + '\')"></label>';
  html += '<label>Color: <select id="conf-palette-' + m.id + '" onchange="confSetPalette(\'' + expId + '\',this.value)">';
  for (const p of _CONF_PALETTES) {
    html += '<option value="' + p.id + '"' + (p.id === m.palette ? ' selected' : '') + '>' + p.label + '</option>';
  }
  html += '</select></label>';
  html += '<label title="Lighten (0.3) or darken (1.5) the heatmap">Intensity: '
       +  '<input type="range" min="0.3" max="1.5" step="0.05" value="' + m.intensity + '" '
       +  'oninput="confSetIntensity(\'' + expId + '\',this.value)" style="width:120px"></label>';
  html += '<button class="action-btn" onclick="confDuplicate(\'' + expId + '\')" title="Make a copy of this matrix">Duplicate</button>';
  html += '<button class="action-btn" onclick="confResetActive(\'' + expId + '\')" title="Zero out all cells">Reset</button>';
  if (s.matrices.length > 1) {
    html += '<button class="action-btn danger" onclick="confDeleteActive(\'' + expId + '\')" title="Delete this matrix">Delete</button>';
  }
  html += '<button class="action-btn" onclick="confSaveMetrics(\'' + expId + '\')" title="Save accuracy, macro precision/recall/F1 as manual metrics on this experiment">Save as metrics</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'png\')" title="Download matrix as a PNG image">Export PNG</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'csv\')" title="Download matrix as CSV">Export CSV</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'md\')" title="Copy matrix as a Markdown table">Copy Markdown</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'json\')" title="Copy matrix as JSON">Copy JSON</button>';
  html += '<span class="conf-hint">Rows = actual, columns = predicted. Edit a class name once — it applies to both axes. Auto-saves to this experiment.</span>';
  html += '</div>';
  html += '<div id="conf-matrix-area"></div>';
  html += '<div id="conf-results"></div>';

  // Defer rendering matrix grid until after innerHTML attaches
  setTimeout(() => _confRenderGrid(expId, m, 'conf-matrix-area', 'conf-results'), 0);
  return html;
}

function _confRenderGrid(expId, m, areaId, resultsId) {
  const area = document.getElementById(areaId);
  if (!area) return;
  _confEnsureShape(m);
  const n = m.n;

  let cellMax = 0;
  const rowSum = new Array(n).fill(0);
  const colSum = new Array(n).fill(0);
  let total = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const v = +m.matrix[i][j] || 0;
    if (v > cellMax) cellMax = v;
    rowSum[i] += v; colSum[j] += v; total += v;
  }

  const editable = areaId === 'conf-matrix-area';
  const isDark = document.body.classList.contains('dark');
  let html = '<table class="conf-matrix">';
  html += '<thead>';
  html += '<tr><th class="conf-corner" colspan="2" rowspan="2"></th>' +
          '<th class="conf-axis" colspan="' + n + '">Predicted</th>' +
          '<th class="conf-corner conf-total-corner" rowspan="2">Total</th></tr>';
  html += '<tr>';
  for (let j = 0; j < n; j++) {
    const labelCell = editable
      ? '<input class="conf-label" value="' + esc(m.labels[j]) + '" oninput="confSetLabel(\'' + expId + '\',' + j + ',this.value)">'
      : '<span class="conf-row-label-text">' + esc(m.labels[j]) + '</span>';
    html += '<th class="conf-col-head">' + labelCell + '</th>';
  }
  html += '</tr></thead><tbody>';
  for (let i = 0; i < n; i++) {
    html += '<tr>';
    if (i === 0) {
      html += '<th class="conf-actual-axis" rowspan="' + (n + 1) + '"><span>Actual</span></th>';
    }
    html += '<th class="conf-row-head"><span class="conf-row-label-text" title="' + esc(m.labels[i]) + '">' + esc(m.labels[i]) + '</span></th>';
    for (let j = 0; j < n; j++) {
      const v = +m.matrix[i][j] || 0;
      const isDiag = i === j;
      const intensity = cellMax > 0 ? (v / cellMax) * (m.intensity || 1) : 0;
      const bg = _confCellColor(intensity, m.palette, isDark);
      const fg = _confCellTextColor(intensity, isDark);
      const cls = 'conf-cell' + (isDiag ? ' conf-diag' : '');
      const inner = editable
        ? '<input type="text" inputmode="numeric" pattern="[0-9]*" class="' + cls + '" style="color:' + fg + '" value="' + v
          + '" oninput="confSetCell(\'' + expId + '\',' + i + ',' + j + ',this.value)"'
          + ' onblur="_confRefreshHeatmap(\'' + expId + '\')">'
        : '<div class="' + cls + '" style="color:' + fg + ';padding:8px 10px;text-align:right">' + v.toLocaleString() + '</div>';
      html += '<td class="conf-cell-td" style="background:' + bg + '">' + inner + '</td>';
    }
    html += '<td class="conf-total-cell" title="Row total (actual = ' + esc(m.labels[i]) + ')">' + rowSum[i].toLocaleString() + '</td>';
    html += '</tr>';
  }
  html += '<tr class="conf-totals-row"><th class="conf-row-head">Total</th>';
  for (let j = 0; j < n; j++) {
    html += '<td class="conf-total-cell" title="Column total (predicted = ' + esc(m.labels[j]) + ')">' + colSum[j].toLocaleString() + '</td>';
  }
  html += '<td class="conf-total-cell conf-grand-total" title="Total samples">' + total.toLocaleString() + '</td>';
  html += '</tr>';
  html += '</tbody></table>';
  area.innerHTML = html;

  if (resultsId) _confCompute(m, resultsId);
}

function _confCellColor(t, paletteId, isDark) {
  if (t <= 0) return 'transparent';
  const p = _CONF_PALETTES.find(p => p.id === paletteId) || _CONF_PALETTES[0];
  const tt = Math.max(0, Math.min(1, t));
  // Brighten + raise base alpha in dark mode so low-intensity fills survive
  // compositing onto the dark card background.
  const shift = isDark ? 60 : 0;
  const r = Math.min(255, p.rgb[0] + shift);
  const g = Math.min(255, p.rgb[1] + shift);
  const b = Math.min(255, p.rgb[2] + shift);
  const a = isDark ? 0.20 + 0.75 * tt : 0.10 + 0.85 * tt;
  return 'rgba(' + r + ',' + g + ',' + b + ',' + a.toFixed(3) + ')';
}

function _confCellTextColor(t, isDark) {
  if (t <= 0) return 'var(--fg)';
  if (isDark) return '#ffffff';
  return t > 0.55 ? '#ffffff' : 'var(--fg)';
}

function _confRefreshHeatmap(expId) {
  const m = _confActive(expId);
  if (!m) return;
  const active = document.activeElement;
  let coords = null;
  if (active && active.classList && active.classList.contains('conf-cell')) {
    const td = active.closest('td');
    const tr = td && td.parentElement;
    if (tr) {
      const cellTds = Array.from(tr.querySelectorAll('td.conf-cell-td'));
      const j = cellTds.indexOf(td);
      const tbody = tr.parentElement;
      const i = Array.from(tbody.children).indexOf(tr);
      coords = {i, j};
    }
  }
  _confRenderGrid(expId, m, 'conf-matrix-area', 'conf-results');
  if (coords) {
    const tbody = document.querySelector('#conf-matrix-area table.conf-matrix tbody');
    if (tbody) {
      const tr = tbody.children[coords.i];
      if (tr) {
        const cellTds = tr.querySelectorAll('td.conf-cell-td');
        const td = cellTds[coords.j];
        const inp = td && td.querySelector('input');
        if (inp) inp.focus();
      }
    }
  }
}

// ── Tab actions ──────────────────────────────────────────────────────────────

function confSelect(expId, mid) {
  const s = _confState[expId];
  if (!s) return;
  s.activeId = mid;
  s.compareIds = null;
  _confRenderTab(expId);
}

function confAdd(expId) {
  const s = _confState[expId];
  if (!s) return;
  const name = 'Matrix ' + (s.matrices.length + 1);
  const m = _confNewMatrix(name, 2);
  s.matrices.push(m);
  s.activeId = m.id;
  s.compareIds = null;
  _confScheduleSave(expId);
  _confRenderTab(expId);
}

function confDuplicate(expId) {
  const s = _confState[expId];
  const m = _confActive(expId);
  if (!s || !m) return;
  const copy = JSON.parse(JSON.stringify(m));
  copy.id = _confNewId();
  copy.name = m.name + ' (copy)';
  s.matrices.push(copy);
  s.activeId = copy.id;
  _confScheduleSave(expId);
  _confRenderTab(expId);
}

function confDeleteActive(expId) {
  const s = _confState[expId];
  if (!s || s.matrices.length <= 1) return;
  const m = _confActive(expId);
  if (!m) return;
  if (!confirm('Delete confusion matrix "' + m.name + '"?')) return;
  s.matrices = s.matrices.filter(x => x.id !== m.id);
  s.activeId = s.matrices[0].id;
  s.compareIds = null;
  _confScheduleSave(expId);
  _confRenderTab(expId);
}

function confResetActive(expId) {
  const m = _confActive(expId);
  if (!m) return;
  if (!confirm('Clear all cells in "' + m.name + '"?')) return;
  for (let i = 0; i < m.n; i++) for (let j = 0; j < m.n; j++) m.matrix[i][j] = 0;
  _confScheduleSave(expId);
  _confRenderTab(expId);
}

function confRename(expId, mid) {
  const s = _confState[expId];
  const m = s && s.matrices.find(x => x.id === mid);
  if (!m) return;
  const name = prompt('Rename matrix:', m.name);
  if (name == null) return;
  m.name = String(name).slice(0, 60).trim() || m.name;
  _confScheduleSave(expId);
  _confRenderTab(expId);
}

function confSetName(expId, mid, val) {
  const s = _confState[expId];
  const m = s && s.matrices.find(x => x.id === mid);
  if (!m) return;
  m.name = String(val).slice(0, 60);
  _confScheduleSave(expId);
  // Update tab label inline so we don't lose focus on the text input.
  const bar = document.querySelector('#detail-tab-confusion .conf-tabs');
  if (bar) {
    const buttons = bar.querySelectorAll('.conf-tab');
    const idx = s.matrices.findIndex(x => x.id === mid);
    if (idx >= 0 && buttons[idx]) buttons[idx].textContent = m.name;
  }
}

function confSetPalette(expId, paletteId) {
  const m = _confActive(expId);
  if (!m) return;
  m.palette = paletteId;
  _confScheduleSave(expId);
  _confRefreshHeatmap(expId);
}

function confSetIntensity(expId, val) {
  const m = _confActive(expId);
  if (!m) return;
  m.intensity = Math.max(0.3, Math.min(1.5, parseFloat(val) || 1.0));
  _confScheduleSave(expId);
  _confRefreshHeatmap(expId);
}

function confResize(expId) {
  const m = _confActive(expId);
  if (!m) return;
  const inp = document.getElementById('conf-n-' + m.id);
  let n = parseInt(inp.value, 10);
  if (!Number.isFinite(n) || n < 2) n = 2;
  if (n > 20) n = 20;
  inp.value = n;
  m.n = n;
  _confEnsureShape(m);
  _confScheduleSave(expId);
  _confRenderTab(expId);
}

function confSetCell(expId, i, j, val) {
  const m = _confActive(expId);
  if (!m) return;
  _confEnsureShape(m);
  const cleaned = String(val).replace(/[^0-9]/g, '');
  let v = cleaned === '' ? 0 : parseInt(cleaned, 10);
  if (!Number.isFinite(v) || v < 0) v = 0;
  m.matrix[i][j] = v;
  _confScheduleSave(expId);
  _confCompute(m, 'conf-results');
}

function confSetLabel(expId, i, val) {
  const m = _confActive(expId);
  if (!m) return;
  _confEnsureShape(m);
  m.labels[i] = String(val).slice(0, 40);
  _confScheduleSave(expId);
  const tbody = document.querySelector('#conf-matrix-area table.conf-matrix tbody');
  if (tbody && tbody.children[i]) {
    const span = tbody.children[i].querySelector('.conf-row-label-text');
    if (span) { span.textContent = m.labels[i]; span.title = m.labels[i]; }
  }
  _confCompute(m, 'conf-results');
}

// ── Metrics ──────────────────────────────────────────────────────────────────

function _confMetrics(m) {
  _confEnsureShape(m);
  const n = m.n;
  const M = m.matrix;
  let total = 0, diag = 0;
  const rowSum = new Array(n).fill(0);
  const colSum = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const v = +M[i][j] || 0;
      total += v;
      rowSum[i] += v;
      colSum[j] += v;
      if (i === j) diag += v;
    }
  }
  const perClass = [];
  for (let i = 0; i < n; i++) {
    const tp = +M[i][i] || 0;
    const fp = colSum[i] - tp;
    const fn = rowSum[i] - tp;
    const tn = total - tp - fp - fn;
    const precision = (tp + fp) > 0 ? tp / (tp + fp) : 0;
    const recall    = (tp + fn) > 0 ? tp / (tp + fn) : 0;
    const f1        = (precision + recall) > 0 ? 2 * precision * recall / (precision + recall) : 0;
    perClass.push({label: m.labels[i] ?? ('class '+i), tp, fp, fn, tn, support: rowSum[i], precision, recall, f1});
  }
  const accuracy = total > 0 ? diag / total : 0;
  let macroP = 0, macroR = 0, macroF = 0;
  let wP = 0, wR = 0, wF = 0;
  perClass.forEach(c => { macroP += c.precision; macroR += c.recall; macroF += c.f1; wP += c.precision*c.support; wR += c.recall*c.support; wF += c.f1*c.support; });
  macroP /= n; macroR /= n; macroF /= n;
  if (total > 0) { wP /= total; wR /= total; wF /= total; }
  return {total, accuracy, perClass, macroP, macroR, macroF, weightedP: wP, weightedR: wR, weightedF: wF};
}

function _fmtPct(x) { return (x*100).toFixed(2) + '%'; }
function _fmtNum(x) { return x.toFixed(4); }

function _confCompute(m, outId) {
  const out = document.getElementById(outId);
  if (!out) return;
  const M = _confMetrics(m);
  if (M.total === 0) {
    out.innerHTML = '<p class="conf-hint">Enter counts above to compute metrics.</p>';
    return;
  }
  let html = '<div class="conf-summary">';
  html += '<div class="conf-stat"><div class="conf-stat-label">Accuracy</div><div class="conf-stat-value">' + _fmtPct(M.accuracy) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Macro F1</div><div class="conf-stat-value">' + _fmtNum(M.macroF) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Macro Precision</div><div class="conf-stat-value">' + _fmtNum(M.macroP) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Macro Recall</div><div class="conf-stat-value">' + _fmtNum(M.macroR) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Total</div><div class="conf-stat-value">' + M.total.toLocaleString() + '</div></div>';
  html += '</div>';

  html += '<table class="conf-perclass"><thead><tr><th>Class</th><th>Support</th><th>TP</th><th>FP</th><th>FN</th><th>TN</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>';
  M.perClass.forEach(c => {
    html += '<tr><td>' + esc(c.label) + '</td><td>' + c.support.toLocaleString() + '</td><td>' + c.tp.toLocaleString() +
            '</td><td>' + c.fp.toLocaleString() + '</td><td>' + c.fn.toLocaleString() + '</td><td>' + c.tn.toLocaleString() +
            '</td><td>' + _fmtNum(c.precision) + '</td><td>' + _fmtNum(c.recall) + '</td><td>' + _fmtNum(c.f1) + '</td></tr>';
  });
  html += '<tr class="conf-agg"><td>weighted avg</td><td>' + M.total.toLocaleString() + '</td><td colspan="4"></td><td>' +
          _fmtNum(M.weightedP) + '</td><td>' + _fmtNum(M.weightedR) + '</td><td>' + _fmtNum(M.weightedF) + '</td></tr>';
  html += '</tbody></table>';
  out.innerHTML = html;
}

// ── Compare view ─────────────────────────────────────────────────────────────

function confEnterCompare(expId) {
  const s = _confState[expId];
  if (!s || s.matrices.length < 2) return;
  s.compareIds = [s.matrices[0].id, s.matrices[1].id];
  _confRenderTab(expId);
}

function confSetCompare(expId, slot, mid) {
  const s = _confState[expId];
  if (!s) return;
  s.compareIds = s.compareIds || [s.matrices[0].id, s.matrices[1].id];
  s.compareIds[slot] = mid;
  _confRenderTab(expId);
}

function confExitCompare(expId) {
  const s = _confState[expId];
  if (!s) return;
  s.compareIds = null;
  _confRenderTab(expId);
}

function _confRenderCompare(expId) {
  const s = _confState[expId];
  if (!s) return '';
  const ids = s.compareIds || [s.matrices[0].id, s.matrices[1].id];
  const m1 = s.matrices.find(x => x.id === ids[0]) || s.matrices[0];
  const m2 = s.matrices.find(x => x.id === ids[1]) || s.matrices[1];

  const opts = (selId) => s.matrices.map(m =>
    '<option value="' + m.id + '"' + (m.id === selId ? ' selected' : '') + '>' + esc(m.name) + '</option>'
  ).join('');

  let html = '<div class="conf-compare-controls">';
  html += '<label>A: <select onchange="confSetCompare(\'' + expId + '\',0,this.value)">' + opts(m1.id) + '</select></label>';
  html += '<label>B: <select onchange="confSetCompare(\'' + expId + '\',1,this.value)">' + opts(m2.id) + '</select></label>';
  html += '<button class="action-btn" onclick="confExitCompare(\'' + expId + '\')">Done</button>';
  html += '<span class="conf-hint">Read-only side-by-side. Edit in the matrix tabs to change values.</span>';
  html += '</div>';

  html += '<div class="conf-compare-grid">';
  html += '<div class="conf-compare-side">';
  html += '<h4 class="conf-compare-title">' + esc(m1.name) + '</h4>';
  html += '<div id="conf-cmp-area-1"></div>';
  html += '<div id="conf-cmp-results-1"></div>';
  html += '</div>';
  html += '<div class="conf-compare-side">';
  html += '<h4 class="conf-compare-title">' + esc(m2.name) + '</h4>';
  html += '<div id="conf-cmp-area-2"></div>';
  html += '<div id="conf-cmp-results-2"></div>';
  html += '</div>';
  html += '</div>';

  html += '<div id="conf-cmp-diff"></div>';

  setTimeout(() => {
    _confRenderGrid(expId, m1, 'conf-cmp-area-1', 'conf-cmp-results-1');
    _confRenderGrid(expId, m2, 'conf-cmp-area-2', 'conf-cmp-results-2');
    _confRenderDiff(m1, m2);
  }, 0);

  return html;
}

function _confRenderDiff(m1, m2) {
  const out = document.getElementById('conf-cmp-diff');
  if (!out) return;
  const a = _confMetrics(m1);
  const b = _confMetrics(m2);
  if (a.total === 0 && b.total === 0) { out.innerHTML = ''; return; }

  const diffCell = (av, bv, isPct) => {
    const d = bv - av;
    const fmt = isPct ? _fmtPct : _fmtNum;
    const cls = d > 0 ? 'conf-diff-pos' : (d < 0 ? 'conf-diff-neg' : 'conf-diff-zero');
    const sign = d > 0 ? '+' : '';
    return '<td>' + fmt(av) + '</td><td>' + fmt(bv) + '</td><td class="' + cls + '">' + sign + fmt(d) + '</td>';
  };

  let html = '<h4 class="conf-compare-title" style="margin-top:18px">Difference (B − A)</h4>';
  html += '<table class="conf-perclass conf-diff-table"><thead><tr>'
       +  '<th>Metric</th><th>A</th><th>B</th><th>Δ</th>'
       +  '</tr></thead><tbody>';
  html += '<tr>' + '<td>Accuracy</td>' + diffCell(a.accuracy, b.accuracy, true) + '</tr>';
  html += '<tr>' + '<td>Macro F1</td>' + diffCell(a.macroF, b.macroF, false) + '</tr>';
  html += '<tr>' + '<td>Macro Precision</td>' + diffCell(a.macroP, b.macroP, false) + '</tr>';
  html += '<tr>' + '<td>Macro Recall</td>' + diffCell(a.macroR, b.macroR, false) + '</tr>';
  html += '<tr>' + '<td>Weighted F1</td>' + diffCell(a.weightedF, b.weightedF, false) + '</tr>';
  html += '<tr>' + '<td>Weighted Precision</td>' + diffCell(a.weightedP, b.weightedP, false) + '</tr>';
  html += '<tr>' + '<td>Weighted Recall</td>' + diffCell(a.weightedR, b.weightedR, false) + '</tr>';
  html += '<tr>' + '<td>Total</td><td>' + a.total.toLocaleString() + '</td><td>' + b.total.toLocaleString() + '</td><td>' + (b.total - a.total).toLocaleString() + '</td></tr>';
  html += '</tbody></table>';
  out.innerHTML = html;
}

// ── Export / save metrics ────────────────────────────────────────────────────

function _confExportPng(expId, m, labels, M, rowSum, colSum, total) {
  const n = m.n;
  let cellMax = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const v = +M[i][j] || 0;
    if (v > cellMax) cellMax = v;
  }

  const cellW = 80, cellH = 44;
  const labelW = 110;
  const axisW = 24;
  const totalW = 70;
  const colHeadH = 38;
  const axisH = 24;
  const totalsRowH = 36;
  const padL = 12, padR = 12, padT = 14, padB = 14;

  const tableW = axisW + labelW + n * cellW + totalW;
  const tableH = axisH + colHeadH + n * cellH + totalsRowH;
  const W = padL + tableW + padR;
  const H = padT + tableH + padB;

  const x0 = padL, y0 = padT;
  const cellsX0 = x0 + axisW + labelW;
  const cellsY0 = y0 + axisH + colHeadH;

  const escx = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const fmt = v => Number(v||0).toLocaleString();
  const palette = (_CONF_PALETTES.find(p => p.id === m.palette) || _CONF_PALETTES[0]).rgb;

  let svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif">';
  svg += '<rect width="' + W + '" height="' + H + '" fill="#ffffff"/>';
  svg += '<rect x="' + cellsX0 + '" y="' + y0 + '" width="' + (n*cellW) + '" height="' + axisH + '" fill="#f3f4f7"/>';
  svg += '<text x="' + (cellsX0 + n*cellW/2) + '" y="' + (y0 + axisH/2 + 4) + '" text-anchor="middle" font-size="12" fill="#666">Predicted</text>';
  for (let j = 0; j < n; j++) {
    const cx = cellsX0 + j*cellW;
    svg += '<rect x="' + cx + '" y="' + (y0 + axisH) + '" width="' + cellW + '" height="' + colHeadH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
    svg += '<text x="' + (cx + cellW/2) + '" y="' + (y0 + axisH + colHeadH/2 + 4) + '" text-anchor="middle" font-size="12" fill="#333">' + escx(_clip(labels[j], 14)) + '</text>';
  }
  svg += '<rect x="' + (cellsX0 + n*cellW) + '" y="' + y0 + '" width="' + totalW + '" height="' + (axisH + colHeadH) + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
  svg += '<text x="' + (cellsX0 + n*cellW + totalW/2) + '" y="' + (y0 + (axisH + colHeadH)/2 + 4) + '" text-anchor="middle" font-size="12" fill="#666">Total</text>';
  svg += '<rect x="' + x0 + '" y="' + cellsY0 + '" width="' + axisW + '" height="' + (n*cellH) + '" fill="#f3f4f7"/>';
  const axTextY = cellsY0 + n*cellH/2;
  const axTextX = x0 + axisW/2 + 4;
  svg += '<text x="' + axTextX + '" y="' + axTextY + '" text-anchor="middle" font-size="12" fill="#666" transform="rotate(-90 ' + axTextX + ',' + axTextY + ')">Actual</text>';

  for (let i = 0; i < n; i++) {
    const ry = cellsY0 + i*cellH;
    svg += '<rect x="' + (x0 + axisW) + '" y="' + ry + '" width="' + labelW + '" height="' + cellH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
    svg += '<text x="' + (x0 + axisW + labelW/2) + '" y="' + (ry + cellH/2 + 4) + '" text-anchor="middle" font-size="12" fill="#333">' + escx(_clip(labels[i], 16)) + '</text>';
    for (let j = 0; j < n; j++) {
      const cx = cellsX0 + j*cellW;
      const v = +M[i][j] || 0;
      const t = cellMax > 0 ? (v / cellMax) * (m.intensity || 1) : 0;
      const tt = Math.max(0, Math.min(1, t));
      const r = Math.round(255 + (palette[0] - 255) * tt);
      const g = Math.round(255 + (palette[1] - 255) * tt);
      const b = Math.round(255 + (palette[2] - 255) * tt);
      const fill = tt > 0 ? 'rgb(' + r + ',' + g + ',' + b + ')' : '#ffffff';
      const fg = tt > 0.55 ? '#ffffff' : '#222';
      const fw = i === j ? 600 : 400;
      svg += '<rect x="' + cx + '" y="' + ry + '" width="' + cellW + '" height="' + cellH + '" fill="' + fill + '" stroke="#dcdfe6"/>';
      svg += '<text x="' + (cx + cellW - 10) + '" y="' + (ry + cellH/2 + 5) + '" text-anchor="end" font-size="13" font-weight="' + fw + '" fill="' + fg + '">' + fmt(v) + '</text>';
    }
    const tx = cellsX0 + n*cellW;
    svg += '<rect x="' + tx + '" y="' + ry + '" width="' + totalW + '" height="' + cellH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
    svg += '<text x="' + (tx + totalW - 10) + '" y="' + (ry + cellH/2 + 5) + '" text-anchor="end" font-size="13" fill="#555">' + fmt(rowSum[i]) + '</text>';
  }
  const try_ = cellsY0 + n*cellH;
  svg += '<rect x="' + (x0 + axisW) + '" y="' + try_ + '" width="' + labelW + '" height="' + totalsRowH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
  svg += '<text x="' + (x0 + axisW + labelW/2) + '" y="' + (try_ + totalsRowH/2 + 4) + '" text-anchor="middle" font-size="12" fill="#666">Total</text>';
  for (let j = 0; j < n; j++) {
    const cx = cellsX0 + j*cellW;
    svg += '<rect x="' + cx + '" y="' + try_ + '" width="' + cellW + '" height="' + totalsRowH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
    svg += '<text x="' + (cx + cellW - 10) + '" y="' + (try_ + totalsRowH/2 + 5) + '" text-anchor="end" font-size="13" fill="#555">' + fmt(colSum[j]) + '</text>';
  }
  const gx = cellsX0 + n*cellW;
  svg += '<rect x="' + gx + '" y="' + try_ + '" width="' + totalW + '" height="' + totalsRowH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
  svg += '<text x="' + (gx + totalW - 10) + '" y="' + (try_ + totalsRowH/2 + 5) + '" text-anchor="end" font-size="13" font-weight="600" fill="#222">' + fmt(total) + '</text>';
  svg += '</svg>';

  const scale = 2;
  const blob = new Blob([svg], {type: 'image/svg+xml;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = W * scale;
    canvas.height = H * scale;
    const ctx = canvas.getContext('2d');
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    URL.revokeObjectURL(url);
    canvas.toBlob((png) => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(png);
      const safe = (m.name || 'matrix').replace(/[^a-z0-9_-]+/gi, '_').slice(0, 40);
      a.download = 'confusion_' + safe + '_' + expId + '.png';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      owlSay('PNG downloaded.');
    }, 'image/png');
  };
  img.onerror = () => { URL.revokeObjectURL(url); owlSay('PNG export failed.'); };
  img.src = url;
}

function _clip(s, max) {
  s = String(s ?? '');
  return s.length > max ? s.slice(0, max - 1) + '…' : s;
}

function confExport(expId, fmt) {
  const m = _confActive(expId);
  if (!m) return;
  _confEnsureShape(m);
  const n = m.n;
  const labels = m.labels.slice(0, n);
  const M = m.matrix;
  const rowSum = labels.map((_, i) => M[i].slice(0, n).reduce((a,b) => a + (+b||0), 0));
  const colSum = labels.map((_, j) => { let s = 0; for (let i = 0; i < n; i++) s += +M[i][j] || 0; return s; });
  const total = rowSum.reduce((a,b) => a+b, 0);

  if (fmt === 'png') { _confExportPng(expId, m, labels, M, rowSum, colSum, total); return; }
  if (fmt === 'csv') {
    const csvCell = (s) => {
      s = String(s);
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g,'""') + '"' : s;
    };
    let out = ['actual\\predicted', ...labels, 'total'].map(csvCell).join(',') + '\n';
    for (let i = 0; i < n; i++) {
      const row = [labels[i], ...M[i].slice(0, n).map(v => +v||0), rowSum[i]];
      out += row.map(csvCell).join(',') + '\n';
    }
    out += ['total', ...colSum, total].map(csvCell).join(',') + '\n';
    const blob = new Blob([out], {type: 'text/csv'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const safe = (m.name || 'matrix').replace(/[^a-z0-9_-]+/gi, '_').slice(0, 40);
    a.download = 'confusion_' + safe + '_' + expId + '.csv';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    owlSay('CSV downloaded.');
    return;
  }
  if (fmt === 'md') {
    let out = '| actual \\\\ predicted | ' + labels.join(' | ') + ' | **total** |\n';
    out += '|' + ' --- |'.repeat(labels.length + 2) + '\n';
    for (let i = 0; i < n; i++) {
      out += '| **' + labels[i] + '** | ' + M[i].slice(0, n).map(v => (+v||0)).join(' | ') + ' | ' + rowSum[i] + ' |\n';
    }
    out += '| **total** | ' + colSum.join(' | ') + ' | ' + total + ' |\n';
    navigator.clipboard.writeText(out).then(() => owlSay('Markdown copied.'));
    return;
  }
  if (fmt === 'json') {
    const out = JSON.stringify({name: m.name, labels, matrix: M.slice(0, n).map(r => r.slice(0, n).map(v => +v||0)), row_totals: rowSum, col_totals: colSum, total}, null, 2);
    navigator.clipboard.writeText(out).then(() => owlSay('JSON copied.'));
    return;
  }
}

async function confSaveMetrics(expId) {
  const m = _confActive(expId);
  if (!m) return;
  const M = _confMetrics(m);
  if (M.total === 0) { owlSay('Matrix is empty.'); return; }
  // Prefix with the matrix name when there is more than one, so saving from
  // multiple matrices doesn't overwrite each other.
  const s = _confState[expId];
  const multi = s && s.matrices.length > 1;
  const safeName = multi ? (m.name || 'matrix').replace(/[^a-z0-9_]+/gi, '_').slice(0, 30) + '_' : '';
  const items = [
    ['accuracy',         M.accuracy],
    ['precision_macro',  M.macroP],
    ['recall_macro',     M.macroR],
    ['f1_macro',         M.macroF],
    ['precision_weighted', M.weightedP],
    ['recall_weighted',    M.weightedR],
    ['f1_weighted',        M.weightedF],
  ];
  await Promise.all(items.map(([key, value]) =>
    postApi('/api/experiment/' + expId + '/log-result', {key: safeName + key, value, source: 'manual'})
  ));
  owlSay('Saved ' + items.length + ' metrics.');
}
"""
