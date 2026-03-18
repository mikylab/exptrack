"""Metric charts tab: chart selector, scale controls, and Chart.js rendering."""

JS_CHARTS = r"""

// ── Charts tab ───────────────────────────────────────────────────────────────

let _chartsMetricsData = null;

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

function renderMetricChart(container, selectedKey, metricsData, scaleOpts) {
  if (charts._active) { charts._active.destroy(); delete charts._active; }
  let canvas = container.querySelector('#active-chart-canvas');
  if (canvas) canvas.remove();
  canvas = document.createElement('canvas');
  canvas.id = 'active-chart-canvas';
  const chartDiv = container.querySelector('.chart-container');
  if (!chartDiv) return;
  chartDiv.appendChild(canvas);

  const points = metricsData[selectedKey];
  if (!points || points.length < 1) return;

  charts._active = new Chart(canvas, {
    type: 'line',
    data: {
      labels: points.map((p, i) => p.step !== null ? p.step : i),
      datasets: [{
        label: selectedKey,
        data: points.map(p => p.value),
        borderColor: '#2c5aa0',
        backgroundColor: 'rgba(44,90,160,0.1)',
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
        y: buildChartScaleConfig(selectedKey, scaleOpts, 'y'),
      },
      onClick: (evt, elements) => {
        if (!elements.length) return;
        const idx = elements[0].index;
        const pt = points[idx];
        const step = pt.step;
        const val = pt.value;
        if (confirm('Delete point: ' + selectedKey + ' = ' + val + ' (step ' + (step ?? idx) + ')?')) {
          deleteMetricPoint(currentDetailId, selectedKey, step ?? idx);
        }
      }
    }
  });
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

function buildChartsTabContent(metricsData) {
  const metricKeys = Object.entries(metricsData)
    .filter(([k, pts]) => pts.length >= 1)
    .map(([k]) => k);

  if (metricKeys.length === 0) {
    return '<div class="chart-empty">No metric data to chart.</div>';
  }

  const options = metricKeys.map(k => '<option value="' + esc(k) + '">' + esc(k) + '</option>').join('');

  return '<div class="charts-tab-content">'
    + '<div class="chart-toolbar">'
    +   '<label for="chart-metric-select">Metric</label>'
    +   '<select id="chart-metric-select">' + options + '</select>'
    +   '<div class="chart-scale-group">'
    +     '<label>Y min</label><input type="number" id="chart-y-min" placeholder="auto">'
    +     '<label>Y max</label><input type="number" id="chart-y-max" placeholder="auto">'
    +     '<label>X min</label><input type="number" id="chart-x-min" placeholder="auto">'
    +     '<label>X max</label><input type="number" id="chart-x-max" placeholder="auto">'
    +     '<button class="action-btn" id="chart-scale-apply">Apply</button>'
    +     '<button class="action-btn" id="chart-scale-reset">Reset</button>'
    +   '</div>'
    + '</div>'
    + '<div class="chart-container"></div>'
    + '</div>';
}

function initChartsTab(container, metricsData) {
  _chartsMetricsData = metricsData;
  Object.values(charts).forEach(c => c.destroy());
  charts = {};

  const metricKeys = Object.entries(metricsData)
    .filter(([k, pts]) => pts.length >= 1)
    .map(([k]) => k);
  if (metricKeys.length === 0) return;

  const sel = container.querySelector('#chart-metric-select');
  if (!sel) return;

  sel.addEventListener('change', () => {
    renderMetricChart(container, sel.value, metricsData, getChartScaleOpts());
  });

  const applyBtn = container.querySelector('#chart-scale-apply');
  if (applyBtn) {
    applyBtn.addEventListener('click', () => {
      renderMetricChart(container, sel.value, metricsData, getChartScaleOpts());
    });
  }

  const resetBtn = container.querySelector('#chart-scale-reset');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      resetChartScaleInputs();
      renderMetricChart(container, sel.value, metricsData, null);
    });
  }

  // Render first metric
  renderMetricChart(container, metricKeys[0], metricsData, null);
}

async function loadChartsTab(expId) {
  const container = document.getElementById('detail-tab-charts');
  if (!container) return;

  // Reuse cached metrics if available (from same detail load), else fetch
  let metricsData = _chartsMetricsData;
  if (!metricsData) {
    metricsData = await api('/api/metrics/' + expId);
  }

  container.innerHTML = buildChartsTabContent(metricsData);
  initChartsTab(container, metricsData);
}
"""
