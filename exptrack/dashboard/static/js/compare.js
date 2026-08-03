

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
  const ext = {json:'.json', 'json-full':'.full.json', markdown:'.md', csv:'.csv',
               tsv:'.tsv', plain:'.txt',
               params:'.params.txt', 'params-flags':'.params.txt', 'params-json':'.params.json',
               'params-md':'.params.md', 'params-tsv':'.params.tsv'};
  // 'json-full' is the same endpoint asked for the complete (round-trippable)
  // payload — every metric point, every artifact — rather than the summary.
  const full = fmt === 'json-full';
  const fileExt = ext[fmt] || '.txt';
  if (full) fmt = 'json';
  let text;
  if (fmt === 'csv' || fmt === 'tsv') {
    const data = await postApi('/api/bulk-export', {ids: [id], format: fmt});
    // api()/postApi() report the failure themselves; returning null lets the
    // callers stop rather than throwing mid-download on a null body.
    if (!data || data.error) return null;
    text = data.content || JSON.stringify(data, null, 2);
  } else {
    const data = await api('/api/export/' + id + '?format=' + (fmt === 'plain' ? 'json' : fmt) +
                           (full ? '&full=1' : ''));
    if (!data || data.error) return null;
    if (fmt === 'markdown') text = data.markdown || JSON.stringify(data, null, 2);
    else if (fmt === 'plain') text = _formatExpPlainText(data.data || data);
    else if (fmt.startsWith('params')) {
      text = data.params_text != null ? data.params_text : JSON.stringify(data, null, 2);
    }
    else text = JSON.stringify(data, null, 2);
  }
  const exp = allExperiments.find(e => e.id.startsWith(id));
  const name = exp ? exp.name.replace(/[^a-zA-Z0-9_-]/g, '_') : id.slice(0,8);
  const mime = (fmt === 'json' || fmt === 'params-json') ? 'application/json' : 'text/plain';
  return {text, filename: name + fileExt, mime};
}

async function downloadExportFmt(id, fmt) {
  owlSpeak('export');
  const d = await _fetchExportText(id, fmt);
  if (!d) return;
  await saveOrDownload(d.text, d.filename, d.mime);
}

async function copyExportFmt(id, fmt) {
  owlSpeak('export');
  const d = await _fetchExportText(id, fmt);
  if (!d) return;
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
  // Shares the pair pickers' cache, option labels and truncation notice, so the
  // filter box narrows this list too (see _loadCmpExps in js/detail.py).
  if (!await _loadCmpExps()) return;
  const box = document.getElementById('cmp-filter');
  const q = box ? box.value.trim().toLowerCase() : '';
  document.getElementById('cmp-multi-select').innerHTML = _cmpOptsHtml(q, '', selectedIds);
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

// Files whose working-tree diff differs between two runs — i.e. code that moved
// between the attempts but isn't either run's own script. Both runs' stored
// `git_diff` bodies are already on the /api/compare payload, so this needs no
// request; a sentinel ('[compacted…]', '[capture-failed]') is a status, not diff
// text, so a pair carrying one is skipped rather than reported as a difference.
function _cmpWorkingTreeFiles(a, b) {
  const da = (a && a.git_diff) || '', db = (b && b.git_diff) || '';
  if (!da && !db) return [];
  // Every diff sentinel is a bracketed marker ('[compacted…]', '[capture-failed]',
  // '[diff-unavailable]') — a status, never diff text. Two runs carrying
  // different markers are not two runs whose code differed.
  if (da.startsWith('[') || db.startsWith('[')) return [];
  if (da === db || typeof _parseDiff !== 'function') return [];
  // Per file, keep two things: a key for "did this differ between the runs?",
  // and the file's post-image *as this run saw it* — the hunks' context and
  // added lines, i.e. what the file actually contained when the run started.
  // Diffing the two post-images is what turns "helper.py differed" into the
  // line that moved.
  const byFile = d => {
    const m = {};
    for (const f of _parseDiff(String(d)).files) {
      if (!f.hunks.length) continue;
      const key = f.hunks.map(
        h => h.header + '\n' + h.rows.map(r => r.kind + r.text).join('\n')).join('\n');
      const post = f.hunks.map(
        h => h.rows.filter(r => r.kind !== 'del').map(r => r.text).join('\n')).join('\n');
      m[_shortFileLabel(f.header)] = { key, post };
    }
    return m;
  };
  const ma = byFile(da), mb = byFile(db);
  return [...new Set([...Object.keys(ma), ...Object.keys(mb)])]
    .filter(k => (ma[k] || {}).key !== (mb[k] || {}).key)
    .sort()
    .map(k => ({ file: k, a: (ma[k] || {}).post || '', b: (mb[k] || {}).post || '' }));
}

// One code-diff block, used by both branches of the Code changes panel.
// `lineNumbers` is false for a working-tree reconstruction, whose line numbers
// would be those of the hunks rather than of the file.
function _cmpCodeBlockHtml(label, a, b, lineNumbers) {
  const rows = (typeof _lineDiffRows === 'function') ? _lineDiffRows(a || '', b || '') : null;
  return '<div class="cmp-code-block"><div class="cmp-code-label">' + esc(label) + '</div>'
    + (rows ? _renderDiffRows(rows, lineNumbers)
            : '<pre class="cell-code">' + esc(b || a || '') + '</pre>')
    + '</div>';
}

// Render the "Code changes" panel for the Compare view: the cell edit (or
// script-source edit) between the two attempts, using the shared line/word-diff
// renderer. `cd` is the /api/compare `code_diff` payload
// ({mode, cells:[{pos,label,a,b}]}). Older attempt → newer attempt.
function _renderCompareCodeDiff(cd, expA, expB) {
  if (!cd || !cd.mode || cd.mode === 'none') return '';
  const cells = cd.cells || [];
  const kind = cd.mode === 'script' ? 'Script source' : 'Cell edits';
  if (!cells.length) {
    // "No code change" is only true of the code this compares — the run's own
    // script or cells. A run routinely differs from the last one by an edit to
    // a file it *imports*: run train.py, tweak helper.py. That edit is captured
    // (it's in each run's working-tree diff) but it is not the run's own source,
    // so this panel found nothing and said, flatly, that nothing changed — the
    // exact opposite of what happened, on the one screen built to answer it.
    const moved = _cmpWorkingTreeFiles(expA, expB);
    if (moved.length) {
      let h = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">'
        + 'Code changes <span class="cmp-code-count">'
        + moved.length + ' other file' + (moved.length === 1 ? '' : 's')
        + ' differed</span></summary>'
        + '<p style="color:var(--muted);font-size:12px;margin:4px 0 8px">These runs executed identical '
        + (cd.mode === 'script' ? 'script source' : 'cells')
        + ', but a file around them changed between the attempts. Reconstructed from '
        + 'each run\'s working-tree diff, so it covers the changed regions of the '
        + 'file rather than the whole of it.</p>';
      for (const m of moved) h += _cmpCodeBlockHtml(m.file, m.a, m.b, false);
      return h + '</details>';
    }
    return '<details><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">' +
      'Code changes <span class="cmp-code-none">no code change between these runs</span></summary>' +
      '<p style="color:var(--muted);font-size:12px;margin:4px 0 12px">' +
      'These two runs executed identical ' + (cd.mode === 'script' ? 'script source.' : 'cells.') +
      '</p></details>';
  }
  let h = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">' +
    'Code changes <span class="cmp-code-count">' + cells.length + ' ' +
    (cd.mode === 'script' ? 'file' : (cells.length === 1 ? 'cell' : 'cells')) + ' changed</span></summary>';
  for (const c of cells) h += _cmpCodeBlockHtml(c.label || kind, c.a, c.b, true);
  h += '</details>';
  return h;
}

async function doCompare() {
  Object.values(compareCharts).forEach(c => c.destroy());
  compareCharts = {};
  const id1 = document.getElementById('cmp-id1').value.trim();
  const id2 = document.getElementById('cmp-id2').value.trim();
  if (!id1 || !id2) return;
  const data = await api('/api/compare?id1=' + id1 + '&id2=' + id2);
  if (!data) {
    document.getElementById('compare-result').innerHTML =
      '<p>Could not load the comparison \u2014 the request failed.</p>';
    return;
  }
  if (data.error || data.exp1?.error || data.exp2?.error) {
    document.getElementById('compare-result').innerHTML = '<p>One or both experiments not found.</p>';
    return;
  }
  const e1 = data.exp1, e2 = data.exp2;
  const allPKeys = [...new Set([...Object.keys(e1.params), ...Object.keys(e2.params)])].filter(isUserParamKey).sort();
  // api() returns null on a failed request (already reported in the error bar);
  // an unguarded read here threw mid-render and left the whole panel blank.
  const [rawVars1, rawVars2] = await Promise.all([
    api('/api/vars-at/' + id1 + '?seq=999999'),
    api('/api/vars-at/' + id2 + '?seq=999999'),
  ]);
  const tlVars1 = rawVars1 || {};
  const tlVars2 = rawVars2 || {};
  const allVarKeysFromTimeline = [...new Set([...Object.keys(tlVars1), ...Object.keys(tlVars2)])].sort();
  const allMKeys = [...new Set([...e1.metrics.map(m=>m.key), ...e2.metrics.map(m=>m.key)])].sort();
  const m1 = latestMetricsMap(e1.metrics);
  const m2 = latestMetricsMap(e2.metrics);

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
      const row = paramDiffRow(k, e1.params, e2.params);
      if (onlyDiffers && !row.differs) continue;
      html += row.html;
    }
    html += '</table></details>';
  }

  // ── Code changes between the two runs (the run/run/compare loop payoff) ──
  html += _renderCompareCodeDiff(data.code_diff, data.exp1, data.exp2);

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
      // Enough precision that two differing values never print identically.
      const [sv1, sv2] = fmtMetricPair(v1, v2);
      const { differs, html: delta } = metricDelta(v1, v2, k);
      if (onlyDiffers && !differs) continue;
      const ks1 = src1[k] || 'auto', ks2 = src2[k] || 'auto';
      const source = ks1 === ks2 ? '<span class="source-badge ' + ks1 + '">' + ks1 + '</span>' : '<span class="source-badge ' + ks1 + '">' + ks1 + '</span> / <span class="source-badge ' + ks2 + '">' + ks2 + '</span>';
      html += '<tr><td>' + esc(k) + '</td><td>' + esc(sv1) + '</td><td>' + esc(sv2) + '</td><td>' + delta + '</td><td>' + source + '</td></tr>';
    }
    html += '</table></details>';
  }

  // Overlay metric charts
  const [rawSeries1, rawSeries2] = await Promise.all([
    api('/api/metrics/' + id1),
    api('/api/metrics/' + id2),
  ]);
  const metricsSeries1 = rawSeries1 || {};
  const metricsSeries2 = rawSeries2 || {};
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
  const [rawImg1, rawImg2] = await Promise.all([
    api('/api/images/' + id1),
    api('/api/images/' + id2),
  ]);
  const imgData1 = rawImg1 || {};
  const imgData2 = rawImg2 || {};
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
        html += '<div class="cmp-img-thumb" data-side="1" data-src="' + esc(src) + '" onclick="selectCrossImg(\'' + escJsAttr(src) + '\',\'' + escJsAttr(img.name) + '\',1)">';
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
        html += '<div class="cmp-img-thumb" data-side="2" data-src="' + esc(src) + '" onclick="selectCrossImg(\'' + escJsAttr(src) + '\',\'' + escJsAttr(img.name) + '\',2)">';
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
    // Align the two runs on their x-values, never on array index. Two runs can
    // log at a different cadence, and read-time downsampling can keep different
    // points from each — so point i of one run is not point i of the other, and
    // plotting positionally drew unrelated points on top of each other under
    // whichever run's step label came first. Build the union of x-values, map
    // each run onto it, and leave a null (spanGaps) wherever a run has no point.
    const xOf = (p, i) => (p && p.step !== null && p.step !== undefined) ? p.step : i;
    const xs = [...new Set([...pts1.map(xOf), ...pts2.map(xOf)])].sort((a, b) => a - b);
    const alignTo = (pts) => {
      const byX = new Map();
      pts.forEach((p, i) => byX.set(xOf(p, i), p.value));
      return xs.map(x => (byX.has(x) ? byX.get(x) : null));
    };
    compareCharts[k] = new Chart(canvas, {
      type: 'line',
      data: {
        labels: xs,
        datasets: [{
          label: n1,
          data: alignTo(pts1),
          borderColor: '#2c5aa0',
          backgroundColor: 'rgba(44,90,160,0.1)',
          fill: false, tension: 0.3, pointRadius: 2, spanGaps: true,
        }, {
          label: n2,
          data: alignTo(pts2),
          borderColor: '#2d7d46',
          backgroundColor: 'rgba(45,125,70,0.1)',
          fill: false, tension: 0.3, pointRadius: 2, spanGaps: true,
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
  if (!data || data.error || !data.experiments || !data.experiments.length) {
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

  // Summary table — per metric row, the highest value is tinted green and the
  // lowest red so the spread across runs is scannable at a glance (neutral re:
  // higher- vs lower-is-better, which exptrack can't know).
  let html = '<details open><summary style="cursor:pointer;font-size:16px;font-weight:600;margin:12px 0">Comparison Table <span class="cmp-bestkey"><span class="cmp-best-max">highest</span> / <span class="cmp-best-min">lowest</span> per row</span></summary>';
  html += '<div style="overflow-x:auto"><table class="metrics-table"><tr><th>Key</th>';
  for (const e of exps) {
    const name = e.name.length > 20 ? e.name.slice(0,17) + '...' : e.name;
    html += '<th>' + esc(name) + '</th>';
  }
  html += '</tr>';
  for (const k of keys) {
    html += '<tr><td>' + esc(k) + '</td>';
    const nums = exps.map(e => e.metrics[k]).filter(v => typeof v === 'number');
    const mn = nums.length ? Math.min(...nums) : null;
    const mx = nums.length ? Math.max(...nums) : null;
    for (const e of exps) {
      const v = e.metrics[k];
      let cls = '';
      if (typeof v === 'number' && mn !== mx) {
        if (v === mx) cls = ' class="cmp-best-max"';
        else if (v === mn) cls = ' class="cmp-best-min"';
      }
      html += '<td' + cls + '>' + (v !== undefined ? (typeof v === 'number' ? v.toFixed(4) : esc(String(v))) : '--') + '</td>';
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
          html += '<img src="' + fileUrl(img.path) + '" alt="' + esc(label) + '" onclick="openImageModal(this.src,\'' + escJsAttr(label) + '\')">';
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
