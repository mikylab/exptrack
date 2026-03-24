"""Compare view dropdowns, diff rendering, and metric comparison."""

JS_COMPARE = r"""

// ── Export ──────────────────────────────────────────────────────────────────────

let _exportCache = {};

async function exportExp(id) {
  owlSpeak('export');
  _exportCache = {};
  const container = document.getElementById('export-container');
  const fmts = ['json','markdown','csv','tsv','plain'];
  let btns = fmts.map(f =>
    '<button class="action-btn" id="export-btn-' + f + '" onclick="doExport(\'' + id + '\',\'' + f + '\')">' +
    f.toUpperCase().replace('PLAIN','Plain Text').replace('MARKDOWN','Markdown') + '</button>'
  ).join('');
  container.innerHTML = '<div class="export-panel">' +
    '<div class="export-actions">' + btns +
    '<button class="action-btn" onclick="downloadExport()">Download File</button>' +
    '<button class="action-btn" onclick="copyExport()">Copy to Clipboard</button>' +
    '<button class="action-btn" onclick="this.closest(\'.export-panel\').remove()">Close</button>' +
    '</div><pre id="export-content" style="display:none"></pre></div>';
}

function toggleDetailExport(btn) {
  const menu = btn.nextElementSibling;
  menu.style.display = menu.style.display === 'none' ? 'flex' : 'none';
}
function closeDetailExport(btn) {
  btn.closest('.export-dropdown-menu').style.display = 'none';
}

async function _fetchExportText(id, fmt) {
  const ext = {json:'.json', markdown:'.md', csv:'.csv', tsv:'.tsv', plain:'.txt'};
  let text;
  if (fmt === 'csv' || fmt === 'tsv') {
    const data = await postApi('/api/bulk-export', {ids: [id], format: fmt});
    text = data.content || JSON.stringify(data, null, 2);
  } else {
    const data = await api('/api/export/' + id + '?format=' + (fmt === 'plain' ? 'json' : fmt));
    if (fmt === 'markdown') text = data.markdown || JSON.stringify(data, null, 2);
    else if (fmt === 'plain') text = _formatExpPlainText(data.data || data);
    else text = JSON.stringify(data, null, 2);
  }
  const exp = allExperiments.find(e => e.id.startsWith(id));
  const name = exp ? exp.name.replace(/[^a-zA-Z0-9_-]/g, '_') : id.slice(0,8);
  return {text, filename: name + (ext[fmt] || '.txt'), mime: fmt === 'json' ? 'application/json' : 'text/plain'};
}

function _downloadBlob(text, filename, mime) {
  const blob = new Blob([text], {type: mime || 'text/plain'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function downloadExportFmt(id, fmt) {
  owlSpeak('export');
  const d = await _fetchExportText(id, fmt);
  _downloadBlob(d.text, d.filename, d.mime);
  owlSay('Downloaded ' + d.filename);
}

async function copyExportFmt(id, fmt) {
  owlSpeak('export');
  const d = await _fetchExportText(id, fmt);
  navigator.clipboard.writeText(d.text).then(() => owlSay('Copied ' + fmt.toUpperCase() + ' to clipboard!'));
}

// Legacy compat — used by bulk export sidebar
async function doExport(id, fmt) { await downloadExportFmt(id, fmt); }
function downloadExport() {}
function copyExport() {}

// ── Compare ────────────────────────────────────────────────────────────────────

let onlyDiffers = false;
let compareCharts = {};

function switchCompareTab(tab) {
  document.getElementById('compare-pair-tab').classList.toggle('active', tab === 'pair');
  document.getElementById('compare-multi-tab').classList.toggle('active', tab === 'multi');
  document.getElementById('compare-pair-content').style.display = tab === 'pair' ? '' : 'none';
  document.getElementById('compare-multi-content').style.display = tab === 'multi' ? '' : 'none';
  if (tab === 'pair') populateCompareDropdowns();
  if (tab === 'multi') populateMultiCompareSelector();
}

async function populateMultiCompareSelector() {
  const exps = await api('/api/experiments?limit=100');
  const sel = document.getElementById('cmp-multi-select');
  sel.innerHTML = exps.map(e =>
    '<option value="' + e.id + '"' + (selectedIds.has(e.id) ? ' selected' : '') + '>' +
    e.id.slice(0,6) + ' | ' + esc(e.name.slice(0,35)) + ' | ' + e.status + ' | ' + fmtDt(e.created_at) + '</option>'
  ).join('');
}

function doMultiCompareFromSelector() {
  const sel = document.getElementById('cmp-multi-select');
  const ids = [...sel.selectedOptions].map(o => o.value);
  if (ids.length < 2) { owlSay('Select at least 2 experiments'); return; }
  doMultiCompare(ids);
}

function selectAllMultiCompare() {
  const sel = document.getElementById('cmp-multi-select');
  for (const opt of sel.options) opt.selected = true;
}

async function doCompare() {
  Object.values(compareCharts).forEach(c => c.destroy());
  compareCharts = {};
  const id1 = document.getElementById('cmp-id1').value.trim();
  const id2 = document.getElementById('cmp-id2').value.trim();
  if (!id1 || !id2) return;
  const data = await api('/api/compare?id1=' + id1 + '&id2=' + id2);
  if (data.error || data.exp1?.error || data.exp2?.error) {
    document.getElementById('compare-result').innerHTML = '<p>One or both experiments not found.</p>';
    return;
  }
  const e1 = data.exp1, e2 = data.exp2;
  const isUserParam = k => !k.startsWith('_code_change') && k !== '_code_changes' && !k.startsWith('_var/') && k !== '_script_hash' && k !== '_cells_ran' && k !== '_tags' && !k.startsWith('_result:');
  const allPKeys = [...new Set([...Object.keys(e1.params), ...Object.keys(e2.params)])].filter(isUserParam).sort();
  const [tlVars1, tlVars2] = await Promise.all([
    api('/api/vars-at/' + id1 + '?seq=999999'),
    api('/api/vars-at/' + id2 + '?seq=999999'),
  ]);
  const allVarKeysFromTimeline = [...new Set([...Object.keys(tlVars1), ...Object.keys(tlVars2)])].sort();
  const allMKeys = [...new Set([...e1.metrics.map(m=>m.key), ...e2.metrics.map(m=>m.key)])].sort();
  const m1 = Object.fromEntries(e1.metrics.map(m => [m.key, m.last]));
  const m2 = Object.fromEntries(e2.metrics.map(m => [m.key, m.last]));

  const n1 = e1.name.length > 25 ? e1.name.slice(0,22) + '...' : e1.name;
  const n2 = e2.name.length > 25 ? e2.name.slice(0,22) + '...' : e2.name;

  let html = '<div class="compare-grid">';
  html += '<div><h2>' + esc(n1) + '</h2><p class="status-' + e1.status + '">' + e1.status + ' - ' + fmtDur(e1.duration_s) + '</p></div>';
  html += '<div><h2>' + esc(n2) + '</h2><p class="status-' + e2.status + '">' + e2.status + ' - ' + fmtDur(e2.duration_s) + '</p></div>';
  html += '</div>';
  html += '<label class="only-differs-toggle"><input type="checkbox" ' + (onlyDiffers ? 'checked' : '') + ' onchange="onlyDiffers=this.checked;doCompare()"> Show only differences</label>';

  if (allPKeys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Params</summary><table class="params-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allPKeys) {
      const v1 = JSON.stringify(e1.params[k] ?? '--');
      const v2 = JSON.stringify(e2.params[k] ?? '--');
      const differs = v1 !== v2;
      if (onlyDiffers && !differs) continue;
      const cls1 = differs ? (e1.params[k]!==undefined ? ' class="diff-removed"' : '') : '';
      const cls2 = differs ? (e2.params[k]!==undefined ? ' class="diff-added"' : '') : '';
      html += '<tr><td>' + esc(k) + '</td><td' + cls1 + '>' + esc(v1) + '</td><td' + cls2 + '>' + esc(v2) + '</td></tr>';
    }
    html += '</table></details>';
  }

  if (allVarKeysFromTimeline.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Variables <span class="help-icon" title="Final variable state from the execution timeline of each experiment.">?</span></summary><table class="params-table"><tr><th>Variable</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th></tr>';
    for (const k of allVarKeysFromTimeline) {
      const v1 = String(tlVars1[k] ?? '--').slice(0, 60);
      const v2 = String(tlVars2[k] ?? '--').slice(0, 60);
      const differs = v1 !== v2;
      if (onlyDiffers && !differs) continue;
      const cls1 = differs ? ' class="diff-removed"' : '';
      const cls2 = differs ? ' class="diff-added"' : '';
      html += '<tr><td class="var-name">' + esc(k) + '</td><td' + cls1 + '>' + esc(v1) + '</td><td' + cls2 + '>' + esc(v2) + '</td></tr>';
    }
    html += '</table></details>';
  }

  // Unified metrics comparison (all sources now in metrics table)
  const allUnifiedKeys = [...allMKeys];
  // Build source maps from metrics data
  const src1 = Object.fromEntries(e1.metrics.map(m => [m.key, m.source || 'auto']));
  const src2 = Object.fromEntries(e2.metrics.map(m => [m.key, m.source || 'auto']));

  if (allUnifiedKeys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Metrics</summary><table class="metrics-table"><tr><th>Key</th><th>' + esc(n1) + '</th><th>' + esc(n2) + '</th><th>Delta</th><th>Source</th></tr>';
    for (const k of allUnifiedKeys) {
      const v1 = m1[k], v2 = m2[k];
      const sv1 = v1 !== undefined ? (typeof v1 === 'number' ? v1.toFixed(4) : String(v1)) : '--';
      const sv2 = v2 !== undefined ? (typeof v2 === 'number' ? v2.toFixed(4) : String(v2)) : '--';
      let delta = '';
      if (v1 !== undefined && v2 !== undefined && typeof v1 === 'number' && typeof v2 === 'number') {
        const d = v2 - v1;
        if (onlyDiffers && Math.abs(d) < 0.0001) continue;
        const arrow = d > 0 ? '&#x25B2;' : d < 0 ? '&#x25BC;' : '';
        delta = '<span style="color:' + (d>0?'var(--green,#3fb950)':'var(--red,#f85149)') + '">' + arrow + ' ' + (d>0?'+':'') + d.toFixed(4) + '</span>';
      }
      const ks1 = src1[k] || 'auto', ks2 = src2[k] || 'auto';
      const source = ks1 === ks2 ? '<span class="source-badge ' + ks1 + '">' + ks1 + '</span>' : '<span class="source-badge ' + ks1 + '">' + ks1 + '</span> / <span class="source-badge ' + ks2 + '">' + ks2 + '</span>';
      html += '<tr><td>' + esc(k) + '</td><td>' + sv1 + '</td><td>' + sv2 + '</td><td>' + delta + '</td><td>' + source + '</td></tr>';
    }
    html += '</table></details>';
  }

  // Overlay metric charts
  const [metricsSeries1, metricsSeries2] = await Promise.all([
    api('/api/metrics/' + id1),
    api('/api/metrics/' + id2),
  ]);
  const sharedMKeys = allMKeys.filter(k => metricsSeries1[k] && metricsSeries2[k] && (metricsSeries1[k].length > 1 || metricsSeries2[k].length > 1));
  if (sharedMKeys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Metric Charts</summary><div class="compare-charts-grid">';
    for (const k of sharedMKeys) {
      html += '<div class="chart-container"><canvas id="cmp-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_') + '"></canvas></div>';
    }
    html += '</div></details>';
  }

  // ── Image comparison section ──
  crossCmpA = null; crossCmpB = null;
  const [imgData1, imgData2] = await Promise.all([
    api('/api/images/' + id1),
    api('/api/images/' + id2),
  ]);
  let imgs1 = (imgData1.images || []);
  let imgs2 = (imgData2.images || []);
  mergeArtifactImages(imgs1, imgData1.artifact_images);
  mergeArtifactImages(imgs2, imgData2.artifact_images);

  if (imgs1.length || imgs2.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Images</summary>';
    html += '<div class="compare-images-section">';
    html += '<div class="compare-images-cols">';

    // Left column
    html += '<div class="compare-images-col"><h4>' + esc(n1) + ' (' + imgs1.length + ')</h4>';
    if (imgs1.length) {
      html += '<div class="cmp-img-grid">';
      for (const img of imgs1.slice(0, 60)) {
        const src = fileUrl(img.path);
        html += '<div class="cmp-img-thumb" data-side="1" data-src="' + esc(src) + '" onclick="selectCrossImg(\'' + esc(src) + '\',\'' + esc(img.name) + '\',1)">';
        html += '<img src="' + src + '" loading="lazy" alt="' + esc(img.name) + '">';
        html += '<div class="cmp-thumb-name">' + esc(img.name) + '</div>';
        html += '</div>';
      }
      html += '</div>';
    } else {
      html += '<p style="color:var(--muted);font-size:12px">No image paths configured. Set them in the experiment\'s Images tab.</p>';
    }
    html += '</div>';

    // Right column
    html += '<div class="compare-images-col"><h4>' + esc(n2) + ' (' + imgs2.length + ')</h4>';
    if (imgs2.length) {
      html += '<div class="cmp-img-grid">';
      for (const img of imgs2.slice(0, 60)) {
        const src = fileUrl(img.path);
        html += '<div class="cmp-img-thumb" data-side="2" data-src="' + esc(src) + '" onclick="selectCrossImg(\'' + esc(src) + '\',\'' + esc(img.name) + '\',2)">';
        html += '<img src="' + src + '" loading="lazy" alt="' + esc(img.name) + '">';
        html += '<div class="cmp-thumb-name">' + esc(img.name) + '</div>';
        html += '</div>';
      }
      html += '</div>';
    } else {
      html += '<p style="color:var(--muted);font-size:12px">No image paths configured. Set them in the experiment\'s Images tab.</p>';
    }
    html += '</div></div>';

    // Selection bar
    html += '<div class="compare-select-bar" id="cross-cmp-bar">';
    html += '<span class="cmp-sel-a">A: (none)</span>';
    html += '<span style="color:var(--muted)">vs</span>';
    html += '<span class="cmp-sel-b">B: (none)</span>';
    html += '<button class="cmp-compare-btn" onclick="doCrossCompare()" disabled>Compare</button>';
    html += '<button class="cmp-clear-btn" onclick="clearCrossCompare()">Clear</button>';
    html += '</div>';

    html += '</div></details>';
  }

  document.getElementById('compare-result').innerHTML = html;

  // Create overlay charts for shared metrics
  for (const k of sharedMKeys) {
    const canvasId = 'cmp-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_');
    const canvas = document.getElementById(canvasId);
    if (!canvas) continue;
    const pts1 = metricsSeries1[k] || [];
    const pts2 = metricsSeries2[k] || [];
    const maxLen = Math.max(pts1.length, pts2.length);
    const labels = Array.from({length: maxLen}, (_, i) => {
      const p = pts1[i] || pts2[i];
      return p && p.step !== null ? p.step : i;
    });
    compareCharts[k] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          label: n1,
          data: pts1.map(p => p.value),
          borderColor: '#2c5aa0',
          backgroundColor: 'rgba(44,90,160,0.1)',
          fill: false, tension: 0.3, pointRadius: 2,
        }, {
          label: n2,
          data: pts2.map(p => p.value),
          borderColor: '#2d7d46',
          backgroundColor: 'rgba(45,125,70,0.1)',
          fill: false, tension: 0.3, pointRadius: 2,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } } },
        scales: {
          x: { title: { display: true, text: 'Step', font: { family: "'IBM Plex Mono'" } } },
          y: { title: { display: true, text: k, font: { family: "'IBM Plex Mono'" } } }
        }
      }
    });
  }
}

// ── Multi Compare ───────────────────────────────────────────────────────────

const MULTI_COLORS = ['#2c5aa0','#2d7d46','#c0392b','#7c3aed','#d4820f','#1abc9c','#e74c3c','#3498db','#9b59b6','#f39c12'];
let multiCharts = {};

async function doMultiCompare(ids) {
  Object.values(multiCharts).forEach(c => c.destroy());
  multiCharts = {};
  if (!ids || ids.length < 2) {
    ids = [...selectedIds];
  }
  if (ids.length < 2) return;

  const data = await api('/api/multi-compare?ids=' + ids.join(','));
  if (data.error || !data.experiments || !data.experiments.length) {
    document.getElementById('multi-compare-result').innerHTML = '<p>Could not load experiments.</p>';
    return;
  }
  const exps = data.experiments;
  // Collect all unique metric keys
  const allKeys = new Set();
  for (const e of exps) {
    for (const k of Object.keys(e.metrics || {})) allKeys.add(k);
  }
  const keys = [...allKeys].sort();

  // Summary table
  let html = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Comparison Table</summary>';
  html += '<div style="overflow-x:auto"><table class="metrics-table"><tr><th>Key</th>';
  for (const e of exps) {
    const name = e.name.length > 20 ? e.name.slice(0,17) + '...' : e.name;
    html += '<th>' + esc(name) + '</th>';
  }
  html += '</tr>';
  for (const k of keys) {
    html += '<tr><td>' + esc(k) + '</td>';
    for (const e of exps) {
      const v = e.metrics[k];
      html += '<td>' + (v !== undefined ? (typeof v === 'number' ? v.toFixed(4) : esc(String(v))) : '--') + '</td>';
    }
    html += '</tr>';
  }
  html += '</table></div></details>';

  // Bar charts
  if (keys.length) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Bar Charts</summary><div class="compare-charts-grid">';
    for (const k of keys) {
      html += '<div class="chart-container"><canvas id="multi-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_') + '"></canvas></div>';
    }
    html += '</div></details>';
  }

  // Image comparison — group by label across experiments
  const allImageLabels = new Set();
  for (const e of exps) {
    for (const img of (e.images || [])) {
      allImageLabels.add(img.label || img.path.split('/').pop());
    }
  }
  if (allImageLabels.size > 0) {
    html += '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Images</summary>';
    for (const label of [...allImageLabels].sort()) {
      html += '<div class="multi-compare-image-group"><h4 style="font-size:13px;color:var(--muted);margin:8px 0 4px">' + esc(label) + '</h4>';
      html += '<div class="multi-compare-image-row">';
      for (const e of exps) {
        const img = (e.images || []).find(i => (i.label || i.path.split('/').pop()) === label);
        const name = e.name.length > 20 ? e.name.slice(0,17) + '...' : e.name;
        html += '<div class="multi-compare-image-cell">';
        html += '<div style="font-size:11px;color:var(--muted);margin-bottom:4px">' + esc(name) + '</div>';
        if (img) {
          html += '<img src="' + fileUrl(img.path) + '" alt="' + esc(label) + '" onclick="openImageModal(this.src,\'' + esc(label) + '\')">';
        } else {
          html += '<div style="color:var(--muted);font-size:12px;padding:20px;text-align:center">No image</div>';
        }
        html += '</div>';
      }
      html += '</div></div>';
    }
    html += '</details>';
  }

  document.getElementById('multi-compare-result').innerHTML = html;

  // Create bar charts
  for (const k of keys) {
    const canvasId = 'multi-chart-' + k.replace(/[^a-zA-Z0-9]/g,'_');
    const canvas = document.getElementById(canvasId);
    if (!canvas) continue;
    const labels = exps.map(e => e.name.length > 15 ? e.name.slice(0,12) + '...' : e.name);
    const values = exps.map(e => e.metrics[k] ?? null);
    const colors = exps.map((_, i) => MULTI_COLORS[i % MULTI_COLORS.length]);
    multiCharts[k] = new Chart(canvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: k,
          data: values,
          backgroundColor: colors.map(c => c + '33'),
          borderColor: colors,
          borderWidth: 1.5,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { font: { family: "'IBM Plex Mono'", size: 11 } } },
          y: { title: { display: true, text: k, font: { family: "'IBM Plex Mono'" } } }
        }
      }
    });
  }
}
"""

# Utility functions and mutation actions
