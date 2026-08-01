

// ── Charts ───────────────────────────────────────────────────────────────────

let _chartsMetricsData = null;
let _chartsViewMode = 'single';
let _chartsMaxPoints = 500;
// The metric picked in single view. Held across reloads of the tab because a
// running experiment reloads it on every auto-refresh poll — without this the
// selector snaps back to the first metric every 5 seconds.
let _chartsSelectedKey = null;
// The metric shown in the Overview tab's chart preview, held for the same reason.
let _overviewPreviewKey = null;
// What the tab currently on screen was built from — the run id and the metric
// keys it drew. Compared against fresh data to decide whether the charts can be
// updated in place or the tab HTML has to be rebuilt.
let _chartsExpId = null;
let _chartsRenderedKeys = [];

// The metrics worth charting: every key that has at least one point. Computed
// identically by the HTML builder, the initializer and the overview preview, so
// it lives in one place.
function chartMetricKeys(metricsData) {
  return Object.entries(metricsData || {})
    .filter(([, pts]) => pts.length >= 1)
    .map(([k]) => k);
}

const CHART_COLORS = [
  '#2c5aa0', '#e07b39', '#2d8659', '#c0392b', '#8e44ad',
  '#16a085', '#d4ac0d', '#7f8c8d', '#e84393', '#00b894',
];

function buildChartScaleConfig(axisLabel, scaleOpts, axis) {
  const cfg = { title: { display: true, text: axisLabel, font: { family: "'IBM Plex Mono'" } } };
  if (scaleOpts) {
    const minVal = axis === 'x' ? scaleOpts.xMin : scaleOpts.yMin;
    const maxVal = axis === 'x' ? scaleOpts.xMax : scaleOpts.yMax;
    if (minVal !== '') cfg.min = Number(minVal);
    if (maxVal !== '') cfg.max = Number(maxVal);
  }
  return cfg;
}

function _pointLabels(points) {
  return points.map((p, i) => p.step !== null ? p.step : i);
}

// ── Smoothing ────────────────────────────────────────────────────────────────
//
// Display-only: the stored points are never touched, so smoothing is free to
// undo and a smoothed chart still deletes the real point you click. To actually
// shrink a noisy series on disk, use Settings → Prune (or `exptrack prune`).
function _clampSmoothing(v) {
  return Math.min(0.95, Math.max(0, parseFloat(v) || 0));
}
let _chartSmoothing = _clampSmoothing(
  localStorage.getItem('exptrack-chart-smoothing') || '0');

// Exponential moving average with bias correction — the same weighting
// TensorBoard uses. The debias divisor matters: without it every curve is
// dragged toward zero for its first points and a loss that starts at 2.0
// appears to start near 0 and climb, which is the opposite of what happened.
function _smoothValues(values, alpha) {
  if (!alpha || alpha <= 0) return values;
  const out = new Array(values.length);
  let acc = 0, debias = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v === null || v === undefined || !isFinite(v)) { out[i] = v; continue; }
    acc = acc * alpha + (1 - alpha) * v;
    debias = debias * alpha + (1 - alpha);
    out[i] = acc / debias;
  }
  return out;
}

// Swap a chart's data without recreating it. The points also hang off the chart
// (rather than living only in createChart's closure) so the click-to-delete
// handler always resolves against the points currently drawn.
//
// Every chart carries two datasets: the main line (smoothed, or the raw values
// when smoothing is off) and a faint ghost of the unsmoothed series. Keeping
// both datasets present at all times — the ghost merely hidden at zero — means
// moving the slider never changes the dataset count, so charts update in place
// instead of being torn down and rebuilt.
function _applyChartPoints(chart, points) {
  chart.$points = points;
  const raw = points.map(p => p.value);
  chart.data.labels = _pointLabels(points);
  chart.data.datasets[0].data = _smoothValues(raw, _chartSmoothing);
  if (chart.data.datasets[1]) {
    chart.data.datasets[1].data = raw;
    chart.data.datasets[1].hidden = !_chartSmoothing;
  }
}

// Re-render every live chart against the current smoothing factor. Cheap
// enough to run straight from the slider's input event — no rebuild, so the
// axis inputs keep focus and the metric dropdown stays open.
function setChartSmoothing(value) {
  _chartSmoothing = _clampSmoothing(value);
  try { localStorage.setItem('exptrack-chart-smoothing', String(_chartSmoothing)); } catch (e) {}
  const label = document.getElementById('chart-smoothing-val');
  if (label) label.textContent = _chartSmoothing ? _chartSmoothing.toFixed(2) : 'off';
  for (const c of Object.values(charts)) {
    if (!c || !c.$points) continue;
    _applyChartPoints(c, c.$points);
    c.update('none');
  }
}

function createChart(canvas, key, points, colorIdx, scaleOpts) {
  const color = CHART_COLORS[colorIdx % CHART_COLORS.length];
  const raw = points.map(p => p.value);
  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: _pointLabels(points),
      datasets: [{
        label: key,
        data: _smoothValues(raw, _chartSmoothing),
        borderColor: color,
        backgroundColor: color + '1a',
        fill: true, tension: 0.3, pointRadius: 4, pointHoverRadius: 7,
        pointHitRadius: 10,
      }, {
        // The unsmoothed series, kept visible behind the smoothed line so the
        // real spread is never hidden by the smoothing — a smoothed curve on
        // its own reads as far less noisy data than was actually recorded.
        label: key + ' (raw)',
        data: raw,
        borderColor: color + '59',
        borderWidth: 1,
        fill: false, tension: 0, pointRadius: 0, pointHitRadius: 0,
        hidden: !_chartSmoothing,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } },
        tooltip: { callbacks: { afterLabel: (ctx) => {
          const pt = (ctx.chart.$points || [])[ctx.dataIndex];
          return (pt && pt.step !== null && pt.step !== undefined)
            ? 'Click to delete this point'
            : 'This series logs no step — points can\'t be deleted from the chart';
        } } }
      },
      scales: {
        x: buildChartScaleConfig('Step', scaleOpts, 'x'),
        y: buildChartScaleConfig(key, scaleOpts, 'y'),
      },
      onClick: (evt, elements, self) => {
        if (!elements.length) return;
        const idx = elements[0].index;
        const pt = self.$points[idx];
        const step = pt.step;
        const val = pt.value;
        // Delete is by *stored* step. A step-less series has no stored identity
        // to name here — the array index is an index into the *downsampled*
        // display points, so on any series over metric_max_points the confirm
        // would name one point and the server would delete another. Refuse
        // rather than delete the wrong row.
        if (step === null || step === undefined) {
          owlSay('This metric was logged without a step, so a chart click can\'t identify the point to delete. Use the Metrics table.');
          return;
        }
        if (confirm('Delete point: ' + key + ' = ' + val + ' (step ' + step + ')?')) {
          deleteMetricPoint(currentDetailId, key, step);
        }
      }
    }
  });
  chart.$points = points;
  return chart;
}

function destroyTabCharts() {
  for (const [k, c] of Object.entries(charts)) {
    if (k === '_preview') continue;
    c.destroy();
    delete charts[k];
  }
}

// The axis-range inputs, id → the key it fills in a scale-opts object. One list
// so the read, the write, and the reset can't drift when an input is added or
// renamed. An unset bound is '' throughout, which buildChartScaleConfig skips —
// so an all-empty scale is the same as no scale and needs no special case.
const CHART_SCALE_INPUTS = {
  'chart-y-min': 'yMin', 'chart-y-max': 'yMax',
  'chart-x-min': 'xMin', 'chart-x-max': 'xMax',
};

function getChartScaleOpts() {
  const opts = {};
  for (const [id, key] of Object.entries(CHART_SCALE_INPUTS)) {
    opts[key] = (document.getElementById(id) || {}).value || '';
  }
  return opts;
}

// Write a scale back into the inputs — used to carry the user's typed range
// across a rebuild of the tab HTML. A null/empty opts clears them.
function applyChartScaleInputs(opts) {
  for (const [id, key] of Object.entries(CHART_SCALE_INPUTS)) {
    const el = document.getElementById(id);
    if (el) el.value = (opts && opts[key]) || '';
  }
}

function resetChartScaleInputs() {
  applyChartScaleInputs(null);
}

// ── Single chart view ────────────────────────────────────────────────────────

function renderSingleChart(container, selectedKey, metricsData, scaleOpts) {
  if (charts._active) { charts._active.destroy(); delete charts._active; }
  const chartDiv = container.querySelector('.chart-container');
  if (!chartDiv) return;
  chartDiv.innerHTML = '';
  const canvas = document.createElement('canvas');
  chartDiv.appendChild(canvas);

  const points = metricsData[selectedKey];
  if (!points || points.length < 1) return;

  // Colour by position in the shared chartMetricKeys() list — the same list the
  // all-view colours from — so a metric keeps its colour across the two views.
  const keyIdx = chartMetricKeys(metricsData).indexOf(selectedKey);
  charts._active = createChart(canvas, selectedKey, points, keyIdx, scaleOpts);
}

// ── All charts view ──────────────────────────────────────────────────────────

function renderAllCharts(container, metricsData, scaleOpts) {
  destroyTabCharts();
  const grid = container.querySelector('.charts-all-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const keys = chartMetricKeys(metricsData);
  for (const key of keys) {
    const points = metricsData[key];
    const div = document.createElement('div');
    div.className = 'chart-container';
    const canvas = document.createElement('canvas');
    div.appendChild(canvas);
    grid.appendChild(div);
    charts['all_' + key] = createChart(canvas, key, points, keys.indexOf(key), scaleOpts);
  }
}

// Push fresh metric data into the charts already on screen instead of rebuilding
// the tab. A running experiment reloads this tab every 5 seconds, and a rebuild
// throws the DOM away each time — which takes focus out of an axis input
// mid-typing, closes the metric dropdown if it's open, and restarts the draw
// animation. Returns false when the tab on screen can't represent this data
// (never built, other run, other view mode, or the run gained/lost a metric key),
// leaving the caller to rebuild.
function updateChartsInPlace(container, metricsData, expId, mode) {
  if (expId !== _chartsExpId || mode !== _chartsViewMode) return false;
  if (!container.querySelector('.charts-tab-content')) return false;

  const keys = chartMetricKeys(metricsData);
  if (keys.length !== _chartsRenderedKeys.length) return false;
  if (keys.some((k, i) => k !== _chartsRenderedKeys[i])) return false;

  if (mode === 'all') {
    for (const key of keys) {
      const chart = charts['all_' + key];
      if (!chart) return false;
      _applyChartPoints(chart, metricsData[key]);
      chart.update('none');
    }
    return true;
  }

  const sel = container.querySelector('#chart-metric-select');
  if (!charts._active || !sel || !metricsData[sel.value]) return false;
  _applyChartPoints(charts._active, metricsData[sel.value]);
  charts._active.update('none');
  return true;
}

// ── Charts tab HTML & init ───────────────────────────────────────────────────

function buildChartsTabContent(metricsData, viewMode) {
  const metricKeys = chartMetricKeys(metricsData);

  if (metricKeys.length === 0) {
    return '<div class="chart-empty">No metric data to chart.</div>';
  }

  const options = metricKeys.map(k => '<option value="' + esc(k) + '">' + esc(k) + '</option>').join('');
  const isSingle = viewMode === 'single';

  let html = '<div class="charts-tab-content">';

  // Top bar: view toggle + metric selector (single only)
  html += '<div class="chart-toolbar">';
  html += '<div class="chart-view-toggle">'
    + '<button class="' + (isSingle ? 'active' : '') + '" id="chart-view-single">Single</button>'
    + '<button class="' + (!isSingle ? 'active' : '') + '" id="chart-view-all">Show All</button>'
    + '</div>';
  if (isSingle) {
    html += '<label for="chart-metric-select">Metric</label>'
      + '<select id="chart-metric-select">' + options + '</select>';
  }
  html += '<button class="action-btn" id="chart-download-png" style="margin-left:auto" '
    + 'title="Download the visible chart(s) as PNG">⬇ PNG</button>';
  html += '</div>';

  // Scale controls bar (both modes)
  html += '<div class="chart-scale-bar">'
    + '<span class="scale-label">Axis range</span>'
    + '<div class="chart-scale-pair"><label>Y min</label><input type="number" id="chart-y-min" placeholder="auto"></div>'
    + '<div class="chart-scale-pair"><label>Y max</label><input type="number" id="chart-y-max" placeholder="auto"></div>'
    + '<div class="chart-scale-pair"><label>X min</label><input type="number" id="chart-x-min" placeholder="auto"></div>'
    + '<div class="chart-scale-pair"><label>X max</label><input type="number" id="chart-x-max" placeholder="auto"></div>'
    + '<div class="chart-scale-actions">'
    +   '<button class="action-btn" id="chart-scale-apply">Apply</button>'
    +   '<button class="action-btn" id="chart-scale-reset">Reset</button>'
    + '</div>'
    + '</div>';

  // Smoothing is display-only and applies to every chart at once, so it sits
  // on its own row rather than among the per-axis range inputs.
  html += '<div class="chart-smooth-bar">'
    + '<span class="scale-label">Smoothing</span>'
    + '<input type="range" id="chart-smoothing" min="0" max="0.95" step="0.05" '
    +   'value="' + _chartSmoothing + '" '
    +   'title="Exponential moving average over the plotted points. '
    +         'Display only — the stored data is unchanged.">'
    + '<span class="chart-smooth-val" id="chart-smoothing-val">'
    +   (_chartSmoothing ? _chartSmoothing.toFixed(2) : 'off') + '</span>'
    + '<span class="chart-smooth-note">display only — use Settings → Prune to '
    +   'shrink the stored series</span>'
    + '</div>';

  if (isSingle) {
    html += '<div class="chart-container"></div>';
  } else {
    html += '<div class="charts-all-grid"></div>';
  }

  html += '</div>';
  return html;
}

// initScale: the axis range to render with, carried over by loadChartsTab from
// the previous render of this tab (empty bounds are ignored downstream).
function initChartsTab(container, metricsData, viewMode, initScale) {
  _chartsMetricsData = metricsData;
  _chartsViewMode = viewMode;
  destroyTabCharts();

  const metricKeys = chartMetricKeys(metricsData);
  _chartsRenderedKeys = metricKeys;
  if (metricKeys.length === 0) return;

  // View toggle buttons
  const singleBtn = container.querySelector('#chart-view-single');
  const allBtn = container.querySelector('#chart-view-all');
  if (singleBtn) singleBtn.addEventListener('click', () => loadChartsTab(currentDetailId, 'single'));
  if (allBtn) allBtn.addEventListener('click', () => loadChartsTab(currentDetailId, 'all'));

  // Scale controls (shared by both modes)
  const applyBtn = container.querySelector('#chart-scale-apply');
  const resetBtn = container.querySelector('#chart-scale-reset');

  function handleApply() {
    if (viewMode === 'all') {
      renderAllCharts(container, metricsData, getChartScaleOpts());
    } else {
      const sel = container.querySelector('#chart-metric-select');
      if (sel) renderSingleChart(container, sel.value, metricsData, getChartScaleOpts());
    }
  }

  function handleReset() {
    resetChartScaleInputs();
    if (viewMode === 'all') {
      renderAllCharts(container, metricsData, null);
    } else {
      const sel = container.querySelector('#chart-metric-select');
      if (sel) renderSingleChart(container, sel.value, metricsData, null);
    }
  }

  if (applyBtn) applyBtn.addEventListener('click', handleApply);
  if (resetBtn) resetBtn.addEventListener('click', handleReset);

  const dlBtn = container.querySelector('#chart-download-png');
  if (dlBtn) dlBtn.addEventListener('click', downloadChartsPng);

  const smooth = container.querySelector('#chart-smoothing');
  if (smooth) smooth.addEventListener('input', () => setChartSmoothing(smooth.value));

  if (viewMode === 'all') {
    renderAllCharts(container, metricsData, initScale);
    return;
  }

  // Single view controls
  const sel = container.querySelector('#chart-metric-select');
  if (!sel) return;

  sel.addEventListener('change', () => {
    _chartsSelectedKey = sel.value;
    renderSingleChart(container, sel.value, metricsData, getChartScaleOpts());
  });

  // Keep the user's pick across reloads; fall back to the first metric when it
  // isn't in this run (switching experiments) or nothing is remembered yet.
  const initialKey = metricKeys.includes(_chartsSelectedKey) ? _chartsSelectedKey : metricKeys[0];
  sel.value = initialKey;
  _chartsSelectedKey = initialKey;
  renderSingleChart(container, initialKey, metricsData, initScale);
}

async function loadChartsTab(expId, viewMode) {
  const container = document.getElementById('detail-tab-charts');
  if (!container) return;

  const mode = viewMode || _chartsViewMode || 'single';
  // Carried across a rebuild so the typed axis range survives it. (All-empty on
  // first load, which renders exactly like no scale at all.)
  const keptScale = getChartScaleOpts();
  const metricsData = await api('/api/metrics/' + expId + '?max_points=' + _chartsMaxPoints);
  // api() reports its own failure (and returns null); leave the last good chart
  // on screen rather than blanking the tab on one bad poll.
  if (!metricsData) return;
  _chartsMetricsData = metricsData;

  // The common case while a run trains: same run, same view, same metrics — feed
  // the new points to the live charts and leave the DOM (and the user's focus,
  // dropdown and scroll position) alone.
  if (updateChartsInPlace(container, metricsData, expId, mode)) return;

  destroyTabCharts();
  _chartsExpId = expId;
  container.innerHTML = buildChartsTabContent(metricsData, mode);
  applyChartScaleInputs(keptScale);
  initChartsTab(container, metricsData, mode, keptScale);
}

// ── Chart PNG export ─────────────────────────────────────────────────────────

function _downloadCanvasPng(canvas, filename) {
  if (!canvas) return;
  // Chart.js canvases are transparent; composite onto a theme-matched
  // background so the exported PNG isn't see-through.
  const tmp = document.createElement('canvas');
  tmp.width = canvas.width;
  tmp.height = canvas.height;
  const ctx = tmp.getContext('2d');
  ctx.fillStyle = document.body.classList.contains('dark') ? '#1e1e1e' : '#ffffff';
  ctx.fillRect(0, 0, tmp.width, tmp.height);
  ctx.drawImage(canvas, 0, 0);
  tmp.toBlob(blob => { if (blob) downloadBlob(blob, filename, 'image/png'); });
}

function downloadChartsPng() {
  const safe = s => (s || 'chart').replace(/[^a-z0-9_.-]+/gi, '_');
  if (_chartsViewMode === 'all') {
    let n = 0;
    for (const [k, c] of Object.entries(charts)) {
      if (k.startsWith('all_') && c && c.canvas) {
        _downloadCanvasPng(c.canvas, safe(k.slice(4)) + '.png');
        n++;
      }
    }
    owlSay(n ? ('Downloaded ' + n + ' chart' + (n > 1 ? 's' : '')) : 'No charts to download');
  } else {
    const c = charts._active;
    if (c && c.canvas) {
      _downloadCanvasPng(c.canvas, safe(c.data.datasets[0].label) + '.png');
      owlSay('Chart downloaded');
    } else {
      owlSay('No chart to download');
    }
  }
}

// ── Overview mini chart preview ──────────────────────────────────────────────

function renderOverviewChartPreview(metricsData) {
  const container = document.getElementById('overview-chart-preview');
  if (!container || !metricsData) return;

  const metricKeys = chartMetricKeys(metricsData);
  if (metricKeys.length === 0) return;

  const selHtml = metricKeys.length > 1
    ? '<select id="overview-chart-select" style="font-family:inherit;font-size:12px;padding:3px 8px;background:var(--code-bg);border:1px solid var(--border);border-radius:4px;color:var(--fg);cursor:pointer;margin-right:8px">'
      + metricKeys.map(k => '<option value="' + esc(k) + '">' + esc(k) + '</option>').join('')
      + '</select>'
    : '';

  container.innerHTML = selHtml
    + '<span class="chart-preview-link" onclick="switchDetailTab(\'charts\',currentDetailId)">Open Charts tab</span>'
    + '<div class="chart-preview-container"><canvas id="overview-chart-canvas"></canvas></div>';

  function drawPreview(key) {
    if (charts._preview) { charts._preview.destroy(); delete charts._preview; }
    const canvas = document.getElementById('overview-chart-canvas');
    if (!canvas) return;
    const points = metricsData[key];
    if (!points || points.length < 1) return;
    const keyIdx = metricKeys.indexOf(key);
    charts._preview = createChart(canvas, key, points, keyIdx, null);
  }

  // Remembered like the Charts tab's picker: a running experiment rebuilds the
  // whole Overview panel on every metric poll, so without this the preview snaps
  // back to the first metric every 5 seconds. Falls back to the first key when
  // the remembered one isn't in this run (switching experiments).
  const initialKey = metricKeys.includes(_overviewPreviewKey) ? _overviewPreviewKey : metricKeys[0];
  _overviewPreviewKey = initialKey;

  const sel = document.getElementById('overview-chart-select');
  if (sel) {
    sel.value = initialKey;
    sel.addEventListener('change', () => {
      _overviewPreviewKey = sel.value;
      drawPreview(sel.value);
    });
  }
  drawPreview(initialKey);
}
