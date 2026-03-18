"""Metric charts: tab with single/all view toggle, scale controls, and overview preview."""

JS_CHARTS = r"""

// ── Charts ───────────────────────────────────────────────────────────────────

let _chartsMetricsData = null;
let _chartsViewMode = 'single';

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

function createChart(canvas, key, points, colorIdx, scaleOpts) {
  const color = CHART_COLORS[colorIdx % CHART_COLORS.length];
  return new Chart(canvas, {
    type: 'line',
    data: {
      labels: points.map((p, i) => p.step !== null ? p.step : i),
      datasets: [{
        label: key,
        data: points.map(p => p.value),
        borderColor: color,
        backgroundColor: color + '1a',
        fill: true, tension: 0.3, pointRadius: 4, pointHoverRadius: 7,
        pointHitRadius: 10,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } },
        tooltip: { callbacks: { afterLabel: () => 'Click to delete this point' } }
      },
      scales: {
        x: buildChartScaleConfig('Step', scaleOpts, 'x'),
        y: buildChartScaleConfig(key, scaleOpts, 'y'),
      },
      onClick: (evt, elements) => {
        if (!elements.length) return;
        const idx = elements[0].index;
        const pt = points[idx];
        const step = pt.step;
        const val = pt.value;
        if (confirm('Delete point: ' + key + ' = ' + val + ' (step ' + (step ?? idx) + ')?')) {
          deleteMetricPoint(currentDetailId, key, step ?? idx);
        }
      }
    }
  });
}

function destroyAllCharts() {
  Object.values(charts).forEach(c => c.destroy());
  charts = {};
}

function getChartScaleOpts() {
  return {
    yMin: (document.getElementById('chart-y-min') || {}).value || '',
    yMax: (document.getElementById('chart-y-max') || {}).value || '',
    xMin: (document.getElementById('chart-x-min') || {}).value || '',
    xMax: (document.getElementById('chart-x-max') || {}).value || '',
  };
}

function resetChartScaleInputs() {
  ['chart-y-min', 'chart-y-max', 'chart-x-min', 'chart-x-max'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
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

  const keyIdx = Object.keys(metricsData).indexOf(selectedKey);
  charts._active = createChart(canvas, selectedKey, points, keyIdx, scaleOpts);
}

// ── All charts view ──────────────────────────────────────────────────────────

function renderAllCharts(container, metricsData) {
  destroyAllCharts();
  const grid = container.querySelector('.charts-all-grid');
  if (!grid) return;
  grid.innerHTML = '';

  let colorIdx = 0;
  for (const [key, points] of Object.entries(metricsData)) {
    if (points.length < 1) { colorIdx++; continue; }
    const div = document.createElement('div');
    div.className = 'chart-container';
    const canvas = document.createElement('canvas');
    div.appendChild(canvas);
    grid.appendChild(div);
    charts['all_' + key] = createChart(canvas, key, points, colorIdx, null);
    colorIdx++;
  }
}

// ── Charts tab HTML & init ───────────────────────────────────────────────────

function buildChartsTabContent(metricsData, viewMode) {
  const metricKeys = Object.entries(metricsData)
    .filter(([k, pts]) => pts.length >= 1)
    .map(([k]) => k);

  if (metricKeys.length === 0) {
    return '<div class="chart-empty">No metric data to chart.</div>';
  }

  const options = metricKeys.map(k => '<option value="' + esc(k) + '">' + esc(k) + '</option>').join('');
  const isSingle = viewMode === 'single';

  let html = '<div class="charts-tab-content">';
  html += '<div class="chart-toolbar">';
  html += '<div class="chart-view-toggle">'
    + '<button class="' + (isSingle ? 'active' : '') + '" id="chart-view-single">Single</button>'
    + '<button class="' + (!isSingle ? 'active' : '') + '" id="chart-view-all">Show All</button>'
    + '</div>';

  if (isSingle) {
    html += '<label for="chart-metric-select">Metric</label>'
      + '<select id="chart-metric-select">' + options + '</select>'
      + '<div class="chart-scale-group">'
      +   '<label>Y min</label><input type="number" id="chart-y-min" placeholder="auto">'
      +   '<label>Y max</label><input type="number" id="chart-y-max" placeholder="auto">'
      +   '<label>X min</label><input type="number" id="chart-x-min" placeholder="auto">'
      +   '<label>X max</label><input type="number" id="chart-x-max" placeholder="auto">'
      +   '<button class="action-btn" id="chart-scale-apply">Apply</button>'
      +   '<button class="action-btn" id="chart-scale-reset">Reset</button>'
      + '</div>';
  }

  html += '</div>';

  if (isSingle) {
    html += '<div class="chart-container"></div>';
  } else {
    html += '<div class="charts-all-grid"></div>';
  }

  html += '</div>';
  return html;
}

function initChartsTab(container, metricsData, viewMode) {
  _chartsMetricsData = metricsData;
  _chartsViewMode = viewMode;
  destroyAllCharts();

  const metricKeys = Object.entries(metricsData)
    .filter(([k, pts]) => pts.length >= 1)
    .map(([k]) => k);
  if (metricKeys.length === 0) return;

  // View toggle buttons
  const singleBtn = container.querySelector('#chart-view-single');
  const allBtn = container.querySelector('#chart-view-all');
  if (singleBtn) singleBtn.addEventListener('click', () => loadChartsTab(currentDetailId, 'single'));
  if (allBtn) allBtn.addEventListener('click', () => loadChartsTab(currentDetailId, 'all'));

  if (viewMode === 'all') {
    renderAllCharts(container, metricsData);
    return;
  }

  // Single view controls
  const sel = container.querySelector('#chart-metric-select');
  if (!sel) return;

  sel.addEventListener('change', () => {
    renderSingleChart(container, sel.value, metricsData, getChartScaleOpts());
  });

  const applyBtn = container.querySelector('#chart-scale-apply');
  if (applyBtn) {
    applyBtn.addEventListener('click', () => {
      renderSingleChart(container, sel.value, metricsData, getChartScaleOpts());
    });
  }

  const resetBtn = container.querySelector('#chart-scale-reset');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      resetChartScaleInputs();
      renderSingleChart(container, sel.value, metricsData, null);
    });
  }

  renderSingleChart(container, metricKeys[0], metricsData, null);
}

async function loadChartsTab(expId, viewMode) {
  const container = document.getElementById('detail-tab-charts');
  if (!container) return;

  const mode = viewMode || _chartsViewMode || 'single';
  let metricsData = _chartsMetricsData;
  if (!metricsData) {
    metricsData = await api('/api/metrics/' + expId);
  }

  container.innerHTML = buildChartsTabContent(metricsData, mode);
  initChartsTab(container, metricsData, mode);
}

// ── Overview mini chart preview ──────────────────────────────────────────────

function renderOverviewChartPreview(metricsData) {
  const container = document.getElementById('overview-chart-preview');
  if (!container) return;

  const metricKeys = Object.entries(metricsData)
    .filter(([k, pts]) => pts.length >= 1)
    .map(([k]) => k);
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
    const color = CHART_COLORS[keyIdx % CHART_COLORS.length];
    charts._preview = new Chart(canvas, {
      type: 'line',
      data: {
        labels: points.map((p, i) => p.step !== null ? p.step : i),
        datasets: [{
          label: key, data: points.map(p => p.value),
          borderColor: color, backgroundColor: color + '1a',
          fill: true, tension: 0.3, pointRadius: 2, pointHoverRadius: 5,
        }]
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: {
          x: { title: { display: false }, ticks: { font: { size: 10 } } },
          y: { title: { display: false }, ticks: { font: { size: 10 } } },
        },
      }
    });
  }

  const sel = document.getElementById('overview-chart-select');
  if (sel) sel.addEventListener('change', () => drawPreview(sel.value));
  drawPreview(metricKeys[0]);
}
"""
