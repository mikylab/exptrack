"""Confusion matrix calculator tab — enter values, view metrics, save to experiment."""

JS_CONFUSION = r"""
// ── Confusion Matrix calculator ──────────────────────────────────────────────
//
// Stores per-experiment matrix state in localStorage so it survives reloads.
// Computes accuracy plus per-class precision/recall/F1, with macro and
// weighted aggregates. "Save as metrics" posts each via /log-result.

function _confKey(expId) { return 'exptrack:confusion:' + expId; }

function _confLoad(expId) {
  try {
    const raw = localStorage.getItem(_confKey(expId));
    if (raw) return JSON.parse(raw);
  } catch (e) {}
  return {n: 2, labels: ['neg','pos'], matrix: [[0,0],[0,0]]};
}

function _confSave(expId, state) {
  try { localStorage.setItem(_confKey(expId), JSON.stringify(state)); } catch (e) {}
}

function loadConfusionTab(expId) {
  const container = document.getElementById('detail-tab-confusion');
  if (!container) return;
  const state = _confLoad(expId);
  const palette = _confPalette();

  let html = '<div class="conf-wrap">';
  html += '<div class="conf-controls">';
  html += '<label>Classes: <input type="number" min="2" max="20" value="' + state.n + '" id="conf-n" onchange="confResize(\'' + expId + '\')"></label>';
  html += '<label>Color: <select id="conf-palette" onchange="confSetPalette(\'' + expId + '\',this.value)">';
  for (const p of _CONF_PALETTES) {
    html += '<option value="' + p.id + '"' + (p.id === palette ? ' selected' : '') + '>' + p.label + '</option>';
  }
  html += '</select></label>';
  html += '<button class="action-btn" onclick="confReset(\'' + expId + '\')">Reset</button>';
  html += '<button class="action-btn" onclick="confSaveMetrics(\'' + expId + '\')" title="Save accuracy, macro precision/recall/F1 as manual metrics on this experiment">Save as metrics</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'png\')" title="Download matrix as a PNG image">Export PNG</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'csv\')" title="Download matrix as CSV">Export CSV</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'md\')" title="Copy matrix as a Markdown table">Copy Markdown</button>';
  html += '<button class="action-btn" onclick="confExport(\'' + expId + '\',\'json\')" title="Copy matrix as JSON">Copy JSON</button>';
  html += '<span class="conf-hint">Rows = actual, columns = predicted. Edit a class name once — it applies to both axes.</span>';
  html += '</div>';
  html += '<div id="conf-matrix-area"></div>';
  html += '<div id="conf-results"></div>';
  html += '</div>';
  container.innerHTML = html;
  _confRender(expId, state);
}

const _CONF_PALETTES = [
  {id: 'blue',   label: 'Blue',   rgb: [44, 90, 160]},
  {id: 'green',  label: 'Green',  rgb: [45, 125, 70]},
  {id: 'purple', label: 'Purple', rgb: [124, 58, 237]},
  {id: 'orange', label: 'Orange', rgb: [200, 110, 30]},
  {id: 'teal',   label: 'Teal',   rgb: [20, 140, 140]},
  {id: 'grey',   label: 'Grey',   rgb: [110, 110, 110]},
];

function _confPalette() {
  const v = localStorage.getItem('exptrack:confusion:palette');
  if (v && _CONF_PALETTES.some(p => p.id === v)) return v;
  return 'blue';
}

function confSetPalette(expId, id) {
  localStorage.setItem('exptrack:confusion:palette', id);
  const state = _confLoad(expId);
  _confRender(expId, state);
}

function _confPaletteRgb() {
  const id = _confPalette();
  return (_CONF_PALETTES.find(p => p.id === id) || _CONF_PALETTES[0]).rgb;
}

function _escAttr(s) { return String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }

function _confRender(expId, state) {
  const area = document.getElementById('conf-matrix-area');
  if (!area) return;
  _confEnsureShape(state);
  const n = state.n;

  // Single shared scale across all cells — sklearn-style heatmap.
  let cellMax = 0;
  const rowSum = new Array(n).fill(0);
  const colSum = new Array(n).fill(0);
  let total = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const v = +state.matrix[i][j] || 0;
    if (v > cellMax) cellMax = v;
    rowSum[i] += v; colSum[j] += v; total += v;
  }

  let html = '<table class="conf-matrix">';
  html += '<thead>';
  html += '<tr><th class="conf-corner" colspan="2" rowspan="2"></th>' +
          '<th class="conf-axis" colspan="' + n + '">Predicted</th>' +
          '<th class="conf-corner conf-total-corner" rowspan="2">Total</th></tr>';
  html += '<tr>';
  for (let j = 0; j < n; j++) {
    html += '<th class="conf-col-head"><input class="conf-label" value="' + _escAttr(state.labels[j]) +
            '" oninput="confSetLabel(\'' + expId + '\',' + j + ',this.value)"></th>';
  }
  html += '</tr></thead><tbody>';
  for (let i = 0; i < n; i++) {
    html += '<tr>';
    if (i === 0) {
      html += '<th class="conf-actual-axis" rowspan="' + (n + 1) + '"><span>Actual</span></th>';
    }
    html += '<th class="conf-row-head"><span class="conf-row-label-text" title="' + _escAttr(state.labels[i]) + '">' + esc(state.labels[i]) + '</span></th>';
    for (let j = 0; j < n; j++) {
      const v = +state.matrix[i][j] || 0;
      const isDiag = i === j;
      const intensity = cellMax > 0 ? v / cellMax : 0;
      const bg = _confCellColor(intensity);
      const fg = _confCellTextColor(intensity);
      const cls = 'conf-cell' + (isDiag ? ' conf-diag' : '');
      html += '<td class="conf-cell-td" style="background:' + bg + '">' +
              '<input type="text" inputmode="numeric" pattern="[0-9]*" class="' + cls +
              '" style="color:' + fg + '" value="' + v +
              '" oninput="confSetCell(\'' + expId + '\',' + i + ',' + j + ',this.value)"' +
              ' onblur="_confRefreshHeatmap(\'' + expId + '\')"></td>';
    }
    html += '<td class="conf-total-cell" title="Row total (actual = ' + esc(state.labels[i]) + ')">' + rowSum[i].toLocaleString() + '</td>';
    html += '</tr>';
  }
  // Column-totals footer row
  html += '<tr class="conf-totals-row"><th class="conf-row-head">Total</th>';
  for (let j = 0; j < n; j++) {
    html += '<td class="conf-total-cell" title="Column total (predicted = ' + esc(state.labels[j]) + ')">' + colSum[j].toLocaleString() + '</td>';
  }
  html += '<td class="conf-total-cell conf-grand-total" title="Total samples">' + total.toLocaleString() + '</td>';
  html += '</tr>';
  html += '</tbody></table>';
  area.innerHTML = html;
  _confCompute(expId, state);
}

function _confCellColor(t) {
  // Alpha-based gradient over the chosen palette accent. Empty cells are
  // transparent so the underlying card-bg shows through — works in both
  // light and dark mode.
  if (t <= 0) return 'transparent';
  const [r,g,b] = _confPaletteRgb();
  const a = 0.10 + 0.85 * t;
  return 'rgba(' + r + ',' + g + ',' + b + ',' + a.toFixed(3) + ')';
}

function _confCellTextColor(t) {
  // On a translucent fill the text needs enough contrast in both themes.
  // Past ~0.55 alpha the cell is dark enough that white sits well; below
  // that fall back to the theme foreground.
  return t > 0.55 ? '#ffffff' : 'var(--fg)';
}

function _confRefreshHeatmap(expId) {
  // Re-render so heatmap colors update after editing.
  const state = _confLoad(expId);
  // Preserve focus by remembering active element coords.
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
  _confRender(expId, state);
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

function _confEnsureShape(state) {
  const n = state.n;
  if (!Array.isArray(state.labels)) state.labels = [];
  while (state.labels.length < n) state.labels.push('class ' + state.labels.length);
  state.labels.length = n;
  if (!Array.isArray(state.matrix)) state.matrix = [];
  while (state.matrix.length < n) state.matrix.push([]);
  state.matrix.length = n;
  for (let i = 0; i < n; i++) {
    if (!Array.isArray(state.matrix[i])) state.matrix[i] = [];
    while (state.matrix[i].length < n) state.matrix[i].push(0);
    state.matrix[i].length = n;
  }
}

function confResize(expId) {
  const inp = document.getElementById('conf-n');
  let n = parseInt(inp.value, 10);
  if (!Number.isFinite(n) || n < 2) n = 2;
  if (n > 20) n = 20;
  inp.value = n;
  const state = _confLoad(expId);
  state.n = n;
  _confEnsureShape(state);
  _confSave(expId, state);
  _confRender(expId, state);
}

function confReset(expId) {
  if (!confirm('Clear the confusion matrix for this experiment?')) return;
  localStorage.removeItem(_confKey(expId));
  loadConfusionTab(expId);
}

function confSetCell(expId, i, j, val) {
  const state = _confLoad(expId);
  _confEnsureShape(state);
  // Strip non-digit chars (no decimals — these are counts).
  const cleaned = String(val).replace(/[^0-9]/g, '');
  let v = cleaned === '' ? 0 : parseInt(cleaned, 10);
  if (!Number.isFinite(v) || v < 0) v = 0;
  state.matrix[i][j] = v;
  _confSave(expId, state);
  _confCompute(expId, state);
}

function confSetLabel(expId, i, val) {
  const state = _confLoad(expId);
  _confEnsureShape(state);
  state.labels[i] = String(val).slice(0, 40);
  _confSave(expId, state);
  // Update row-header text in place so we don't lose focus on the input.
  const tbody = document.querySelector('#conf-matrix-area table.conf-matrix tbody');
  if (tbody && tbody.children[i]) {
    const span = tbody.children[i].querySelector('.conf-row-label-text');
    if (span) { span.textContent = state.labels[i]; span.title = state.labels[i]; }
  }
  _confCompute(expId, state);
}

function _confMetrics(state) {
  _confEnsureShape(state);
  const n = state.n;
  const M = state.matrix;
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
    perClass.push({label: state.labels[i] ?? ('class '+i), tp, fp, fn, tn, support: rowSum[i], precision, recall, f1});
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

function _confCompute(expId, state) {
  const out = document.getElementById('conf-results');
  if (!out) return;
  const m = _confMetrics(state);
  if (m.total === 0) {
    out.innerHTML = '<p class="conf-hint">Enter counts above to compute metrics.</p>';
    return;
  }
  let html = '<div class="conf-summary">';
  html += '<div class="conf-stat"><div class="conf-stat-label">Accuracy</div><div class="conf-stat-value">' + _fmtPct(m.accuracy) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Macro F1</div><div class="conf-stat-value">' + _fmtNum(m.macroF) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Macro Precision</div><div class="conf-stat-value">' + _fmtNum(m.macroP) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Macro Recall</div><div class="conf-stat-value">' + _fmtNum(m.macroR) + '</div></div>';
  html += '<div class="conf-stat"><div class="conf-stat-label">Total</div><div class="conf-stat-value">' + m.total.toLocaleString() + '</div></div>';
  html += '</div>';

  html += '<table class="conf-perclass"><thead><tr><th>Class</th><th>Support</th><th>TP</th><th>FP</th><th>FN</th><th>TN</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>';
  m.perClass.forEach(c => {
    html += '<tr><td>' + esc(c.label) + '</td><td>' + c.support.toLocaleString() + '</td><td>' + c.tp.toLocaleString() +
            '</td><td>' + c.fp.toLocaleString() + '</td><td>' + c.fn.toLocaleString() + '</td><td>' + c.tn.toLocaleString() +
            '</td><td>' + _fmtNum(c.precision) + '</td><td>' + _fmtNum(c.recall) + '</td><td>' + _fmtNum(c.f1) + '</td></tr>';
  });
  html += '<tr class="conf-agg"><td>weighted avg</td><td>' + m.total.toLocaleString() + '</td><td colspan="4"></td><td>' +
          _fmtNum(m.weightedP) + '</td><td>' + _fmtNum(m.weightedR) + '</td><td>' + _fmtNum(m.weightedF) + '</td></tr>';
  html += '</tbody></table>';
  out.innerHTML = html;
}

function _confExportPng(expId, state, labels, M, rowSum, colSum, total) {
  const n = state.n;
  let cellMax = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) {
    const v = +M[i][j] || 0;
    if (v > cellMax) cellMax = v;
  }

  const cellW = 80, cellH = 44;
  const labelW = 110;          // row-label column
  const axisW = 24;            // "Actual" sidebar
  const totalW = 70;           // row-total column
  const colHeadH = 38;         // column-name row
  const axisH = 24;            // "Predicted" header strip
  const totalsRowH = 36;
  const padL = 12, padR = 12, padT = 14, padB = 14;

  const tableW = axisW + labelW + n * cellW + totalW;
  const tableH = axisH + colHeadH + n * cellH + totalsRowH;
  const W = padL + tableW + padR;
  const H = padT + tableH + padB;

  const x0 = padL;
  const y0 = padT;
  const cellsX0 = x0 + axisW + labelW;
  const cellsY0 = y0 + axisH + colHeadH;

  const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  const fmt = v => Number(v||0).toLocaleString();
  let svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif">';
  svg += '<rect width="' + W + '" height="' + H + '" fill="#ffffff"/>';

  // "Predicted" axis label strip
  svg += '<rect x="' + (cellsX0) + '" y="' + y0 + '" width="' + (n*cellW) + '" height="' + axisH + '" fill="#f3f4f7"/>';
  svg += '<text x="' + (cellsX0 + n*cellW/2) + '" y="' + (y0 + axisH/2 + 4) + '" text-anchor="middle" font-size="12" fill="#666">Predicted</text>';

  // Column headers
  for (let j = 0; j < n; j++) {
    const cx = cellsX0 + j*cellW;
    svg += '<rect x="' + cx + '" y="' + (y0 + axisH) + '" width="' + cellW + '" height="' + colHeadH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
    svg += '<text x="' + (cx + cellW/2) + '" y="' + (y0 + axisH + colHeadH/2 + 4) + '" text-anchor="middle" font-size="12" fill="#333">' + esc(_clip(labels[j], 14)) + '</text>';
  }
  // Total column header
  svg += '<rect x="' + (cellsX0 + n*cellW) + '" y="' + y0 + '" width="' + totalW + '" height="' + (axisH + colHeadH) + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
  svg += '<text x="' + (cellsX0 + n*cellW + totalW/2) + '" y="' + (y0 + (axisH + colHeadH)/2 + 4) + '" text-anchor="middle" font-size="12" fill="#666">Total</text>';

  // "Actual" sidebar
  svg += '<rect x="' + x0 + '" y="' + cellsY0 + '" width="' + axisW + '" height="' + (n*cellH) + '" fill="#f3f4f7"/>';
  const axTextY = cellsY0 + n*cellH/2;
  const axTextX = x0 + axisW/2 + 4;
  svg += '<text x="' + axTextX + '" y="' + axTextY + '" text-anchor="middle" font-size="12" fill="#666" transform="rotate(-90 ' + axTextX + ',' + axTextY + ')">Actual</text>';

  // Cells + row labels
  for (let i = 0; i < n; i++) {
    const ry = cellsY0 + i*cellH;
    // Row label
    svg += '<rect x="' + (x0 + axisW) + '" y="' + ry + '" width="' + labelW + '" height="' + cellH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
    svg += '<text x="' + (x0 + axisW + labelW/2) + '" y="' + (ry + cellH/2 + 4) + '" text-anchor="middle" font-size="12" fill="#333">' + esc(_clip(labels[i], 16)) + '</text>';
    for (let j = 0; j < n; j++) {
      const cx = cellsX0 + j*cellW;
      const v = +M[i][j] || 0;
      const t = cellMax > 0 ? v / cellMax : 0;
      const [pr, pg, pb] = _confPaletteRgb();
      // Lerp from white to accent so the PNG renders well on white bg.
      const r = Math.round(255 + (pr - 255) * t);
      const g = Math.round(255 + (pg - 255) * t);
      const b = Math.round(255 + (pb - 255) * t);
      const fill = t > 0 ? 'rgb(' + r + ',' + g + ',' + b + ')' : '#ffffff';
      const fg = t > 0.55 ? '#ffffff' : '#222';
      const fw = i === j ? 600 : 400;
      svg += '<rect x="' + cx + '" y="' + ry + '" width="' + cellW + '" height="' + cellH + '" fill="' + fill + '" stroke="#dcdfe6"/>';
      svg += '<text x="' + (cx + cellW - 10) + '" y="' + (ry + cellH/2 + 5) + '" text-anchor="end" font-size="13" font-weight="' + fw + '" fill="' + fg + '">' + fmt(v) + '</text>';
    }
    // Row total
    const tx = cellsX0 + n*cellW;
    svg += '<rect x="' + tx + '" y="' + ry + '" width="' + totalW + '" height="' + cellH + '" fill="#f3f4f7" stroke="#dcdfe6"/>';
    svg += '<text x="' + (tx + totalW - 10) + '" y="' + (ry + cellH/2 + 5) + '" text-anchor="end" font-size="13" fill="#555">' + fmt(rowSum[i]) + '</text>';
  }

  // Totals row
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

  // Rasterize via Image + canvas at 2x for retina-quality output.
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
      a.download = 'confusion_matrix_' + expId + '.png';
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
  const state = _confLoad(expId);
  _confEnsureShape(state);
  const n = state.n;
  const labels = state.labels.slice(0, n);
  const M = state.matrix;
  const rowSum = labels.map((_, i) => M[i].slice(0, n).reduce((a,b) => a + (+b||0), 0));
  const colSum = labels.map((_, j) => { let s = 0; for (let i = 0; i < n; i++) s += +M[i][j] || 0; return s; });
  const total = rowSum.reduce((a,b) => a+b, 0);

  if (fmt === 'png') { _confExportPng(expId, state, labels, M, rowSum, colSum, total); return; }
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
    a.download = 'confusion_matrix_' + expId + '.csv';
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
    const out = JSON.stringify({labels, matrix: M.slice(0, n).map(r => r.slice(0, n).map(v => +v||0)), row_totals: rowSum, col_totals: colSum, total}, null, 2);
    navigator.clipboard.writeText(out).then(() => owlSay('JSON copied.'));
    return;
  }
}

async function confSaveMetrics(expId) {
  const state = _confLoad(expId);
  const m = _confMetrics(state);
  if (m.total === 0) { owlSay('Matrix is empty.'); return; }
  const items = [
    ['accuracy',         m.accuracy],
    ['precision_macro',  m.macroP],
    ['recall_macro',     m.macroR],
    ['f1_macro',         m.macroF],
    ['precision_weighted', m.weightedP],
    ['recall_weighted',    m.weightedR],
    ['f1_weighted',        m.weightedF],
  ];
  for (const [key, value] of items) {
    await postApi('/api/experiment/' + expId + '/log-result', {key, value, source: 'manual'});
  }
  owlSay('Saved ' + items.length + ' metrics.');
}
"""
