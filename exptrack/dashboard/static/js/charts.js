

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
// The metrics ticked in the overlay view. Per browser rather than per run, like
// smoothing: "train vs val loss" is a way of reading every run, and a run that
// lacks a remembered key simply falls back to its own default pair.
let _overlayPicks = _overlayLoadPicks();

// The metrics worth charting: every key that has at least one point. Computed
// identically by the HTML builder, the initializer and the overview preview, so
// it lives in one place.
function chartMetricKeys(metricsData) {
  return Object.entries(metricsData || {})
    .filter(([, pts]) => pts.length >= 1)
    .map(([k]) => k);
}

// The colour for a "every run, behind the highlighted series" scatter — the
// role the progress and trade-off charts both need. Beside the palette so it
// can't be spelled at two different alphas in two files.
const CHART_MUTED = 'rgba(130,130,130,0.55)';

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
let _chartSmoothing = _clampSmoothing(_storageGet('exptrack-chart-smoothing') || '0');

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
  _storageSet('exptrack-chart-smoothing', String(_chartSmoothing));
  const label = document.getElementById('chart-smoothing-val');
  if (label) label.textContent = _chartSmoothing ? _chartSmoothing.toFixed(2) : 'off';
  for (const c of Object.values(charts)) {
    if (c && c.$overlay) {
      // Same data, so the axis split cannot change; only the smoothing does.
      _applyOverlayPoints(c, _chartsMetricsData);
      c.update('none');
      continue;
    }
    if (!c || !c.$points) continue;
    _applyChartPoints(c, c.$points);
    c.update('none');
  }
}

// A metric's colour: its position in the run's `chartMetricKeys` list, the one
// list every view colours from, so a metric keeps its colour across Single,
// Show All, Overlay and the overlay's own chips.
function _metricColor(metricKeys, key) {
  return CHART_COLORS[Math.max(0, metricKeys.indexOf(key)) % CHART_COLORS.length];
}

// The line and its raw ghost — the two datasets every chart draws per metric.
// The ghost is the unsmoothed series, kept visible behind the smoothed line so
// the real spread is never hidden by the smoothing: a smoothed curve on its
// own reads as far less noisy data than was actually recorded.
function _seriesDatasets(key, color, line, raw, extra) {
  const x = extra || {};
  return [Object.assign({
    label: key, data: line, borderColor: color, backgroundColor: color + '1a',
    fill: true, tension: 0.3, pointRadius: 4, pointHoverRadius: 7, pointHitRadius: 10,
  }, x.line), Object.assign({
    label: key + ' (raw)', data: raw, borderColor: color + '59', borderWidth: 1,
    fill: false, tension: 0, pointRadius: 0, pointHitRadius: 0,
    hidden: !_chartSmoothing, $ghost: true,
  }, x.raw)];
}

function _hasStep(pt) {
  return !!pt && pt.step !== null && pt.step !== undefined;
}

function _pointTooltip(pt) {
  return _hasStep(pt)
    ? 'Click to delete this point'
    : 'This series logs no step — points can\'t be deleted from the chart';
}

// Delete is by *stored* step. A step-less series has no stored identity to
// name here — the array index is an index into the *downsampled* display
// points, so on any series over metric_max_points the confirm would name one
// point and the server would delete another. Refuse rather than delete the
// wrong row.
function _confirmDeletePoint(key, pt) {
  if (!pt) return;
  if (!_hasStep(pt)) {
    owlSay('This metric was logged without a step, so a chart click can\'t identify the point to delete. Use the Metrics table.');
    return;
  }
  if (confirm('Delete point: ' + key + ' = ' + pt.value + ' (step ' + pt.step + ')?')) {
    deleteMetricPoint(currentDetailId, key, pt.step);
  }
}

function createChart(canvas, key, points, colorIdx, scaleOpts) {
  const color = CHART_COLORS[colorIdx % CHART_COLORS.length];
  const raw = points.map(p => p.value);
  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: _pointLabels(points),
      datasets: _seriesDatasets(key, color, _smoothValues(raw, _chartSmoothing), raw),
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: true, labels: { font: { family: "'IBM Plex Mono'" } } },
        tooltip: { callbacks: { afterLabel: (ctx) => _pointTooltip((ctx.chart.$points || [])[ctx.dataIndex]) } }
      },
      scales: {
        x: buildChartScaleConfig('Step', scaleOpts, 'x'),
        y: buildChartScaleConfig(key, scaleOpts, 'y'),
      },
      onClick: (evt, elements, self) => {
        if (elements.length) _confirmDeletePoint(key, self.$points[elements[0].index]);
      }
    }
  });
  chart.$points = points;
  chart.$title = key;
  return chart;
}

// A fresh canvas in the tab's `.chart-container`, the previous `_active` chart
// released first. Null when the container is not on the page.
function _freshChartCanvas(container) {
  if (charts._active) { charts._active.destroy(); delete charts._active; }
  const chartDiv = container.querySelector('.chart-container');
  if (!chartDiv) return null;
  chartDiv.innerHTML = '';
  const canvas = document.createElement('canvas');
  chartDiv.appendChild(canvas);
  return canvas;
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
  const canvas = _freshChartCanvas(container);
  if (!canvas) return;

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

// ── Overlay view ─────────────────────────────────────────────────────────────
//
// Several of one run's metrics on one chart — the reading "Show All" cannot
// give, because two metrics in two grid cells have two y-axes and two widths,
// so where train and validation loss part company has to be eyeballed across
// the gap. The x-axis is the logged *step* on a linear scale rather than a
// label per point: train loss logged every epoch and validation every tenth
// still line up, which one shared label list could not do.

function _overlayLoadPicks() {
  try {
    const v = JSON.parse(_storageGet('exptrack-chart-overlay') || '[]');
    return Array.isArray(v) ? v.map(String) : [];
  } catch (e) { return []; }      // a hand-edited value is not a list
}

function _overlaySavePicks(picks) {
  _overlayPicks = picks.slice();
  _storageSet('exptrack-chart-overlay', JSON.stringify(_overlayPicks));
}

// A metric name with its split marker removed, so `loss`, `train_loss`,
// `val_loss`, `valid/loss` and `loss_val` all read as the one measurement
// `loss`. Only the split words are stripped — `val_acc` and `val_loss` must
// stay two different bases.
function _overlayBaseName(key) {
  const split = '(train|training|tr|val|valid|validation|dev|test|eval)';
  const k = String(key).toLowerCase();
  const pre = k.match(new RegExp('^' + split + '[_./-](.+)$'));
  if (pre) return pre[2];
  const post = k.match(new RegExp('^(.+?)[_./-]' + split + '$'));
  return post ? post[1] : k;
}

// What the overlay opens on when nothing remembered applies: the train/val
// pair of the run's primary metric, else the first family that has a pair at
// all, else the primary metric and the key after it.
function _overlayDefaultKeys(keys, primary) {
  const list = (keys || []).slice();
  if (list.length < 2) return list;
  const families = {};
  for (const k of list) {
    const base = _overlayBaseName(k);
    (families[base] = families[base] || []).push(k);
  }
  const lead = primary && list.includes(primary) ? primary : list[0];
  const own = families[_overlayBaseName(lead)];
  if (own.length >= 2) return own;
  for (const k of list) {
    const fam = families[_overlayBaseName(k)];
    if (fam.length >= 2) return fam;
  }
  return [lead, list.find(k => k !== lead)];
}

// A metric's scale: its largest magnitude. A zero-only series gets a floor so
// the ratio below never divides by zero.
function _overlaySpan(points) {
  let m = 0;
  for (const p of points || []) {
    const v = Math.abs(p.value);
    if (isFinite(v) && v > m) m = v;
  }
  return m || 1e-12;
}

// Which picks share the left axis and which need the right one. The first
// pick sets the left axis; anything within 10x of it shares it, because two
// curves on one axis are the point, and loss (~2) against accuracy (~0.9)
// reads fine together. Past 10x — loss against a 1e-4 learning rate — the
// smaller series would be a flat line on the floor, so it gets its own axis.
// Two axes at most: a third would be unreadable.
function _overlayAxisGroups(picks, metricsData) {
  const out = {left: [], right: []};
  if (!picks.length) return out;
  const ref = _overlaySpan(metricsData[picks[0]]);
  for (const k of picks) {
    const r = _overlaySpan(metricsData[k]) / ref;
    (r > 10 || r < 0.1 ? out.right : out.left).push(k);
  }
  return out;
}

// One metric's overlay points: {x: step (index when step-less), y}, as the
// line (smoothed when smoothing is on) and the raw ghost.
function _overlaySeries(points) {
  const raw = points.map((p, i) => ({x: _hasStep(p) ? p.step : i, y: p.value}));
  const sm = _smoothValues(points.map(p => p.value), _chartSmoothing);
  return {line: raw.map((d, i) => ({x: d.x, y: sm[i]})), raw: raw};
}

// Every picked metric draws the same two datasets a single chart does.
function _overlayDatasets(picks, metricsData, groups) {
  const allKeys = chartMetricKeys(metricsData);
  const sets = [];
  for (const k of picks) {
    const axis = groups.right.includes(k) ? 'y1' : 'y';
    const pts = metricsData[k] || [];
    const s = _overlaySeries(pts);
    sets.push(..._seriesDatasets(k, _metricColor(allKeys, k), s.line, s.raw, {
      line: {label: k + (axis === 'y1' ? ' (right axis)' : ''), yAxisID: axis,
             fill: false, pointRadius: 3, pointHoverRadius: 6, pointHitRadius: 8,
             $key: k, $points: pts},
      raw: {yAxisID: axis},
    }));
  }
  return sets;
}

function _overlayAxisSig(groups) {
  return groups.left.join('\n') + '|' + groups.right.join('\n');
}

function _createOverlayChart(canvas, picks, metricsData, scaleOpts) {
  const groups = _overlayAxisGroups(picks, metricsData);
  const scales = {
    x: Object.assign({type: 'linear'}, buildChartScaleConfig('Step', scaleOpts, 'x')),
    y: Object.assign({position: 'left'},
      buildChartScaleConfig(groups.left.join(', '), scaleOpts, 'y')),
  };
  // The axis-range inputs bound the left axis only: the right one exists
  // because its series lives on another scale, so a shared bound would flatten
  // one of them.
  if (groups.right.length) {
    scales.y1 = {position: 'right', grid: {drawOnChartArea: false},
      title: {display: true, text: groups.right.join(', '),
              font: {family: "'IBM Plex Mono'"}}};
  }
  const chart = new Chart(canvas, {
    type: 'line',
    data: {datasets: _overlayDatasets(picks, metricsData, groups)},
    options: {
      responsive: true,
      interaction: {mode: 'nearest', intersect: true},
      plugins: {
        legend: {display: true, labels: {font: {family: "'IBM Plex Mono'"},
          filter: (item, data) => !data.datasets[item.datasetIndex].$ghost}},
        tooltip: {callbacks: {afterLabel: (ctx) => _pointTooltip((ctx.dataset.$points || [])[ctx.dataIndex])}},
      },
      scales: scales,
      // Same rule as a single chart, resolved against the series that was hit.
      onClick: (evt, elements, self) => {
        if (!elements.length) return;
        const ds = self.data.datasets[elements[0].datasetIndex];
        if (ds && ds.$points) _confirmDeletePoint(ds.$key, ds.$points[elements[0].index]);
      },
    },
  });
  chart.$overlay = {picks: picks.slice(), axisSig: _overlayAxisSig(groups)};
  chart.$title = 'overlay: ' + picks.join(' + ');
  return chart;
}

// Fresh points into the overlay on screen. Returns false when the new data
// would move a series to the other axis — that is a different chart, and the
// caller rebuilds it rather than letting a line jump scales under the reader.
function _applyOverlayPoints(chart, metricsData) {
  const picks = chart.$overlay.picks;
  if (_overlayAxisSig(_overlayAxisGroups(picks, metricsData)) !== chart.$overlay.axisSig) {
    return false;
  }
  // Datasets come in (line, ghost) pairs, one pair per pick, in pick order.
  picks.forEach((k, i) => {
    const pts = metricsData[k] || [];
    const s = _overlaySeries(pts);
    const line = chart.data.datasets[2 * i], ghost = chart.data.datasets[2 * i + 1];
    line.data = s.line;
    line.$points = pts;
    ghost.data = s.raw;
    ghost.hidden = !_chartSmoothing;
  });
  return true;
}

// Remembered picks that exist in this run, if at least two do; otherwise the
// run's default pair.
function _overlayInitialPicks(metricKeys) {
  const kept = _overlayPicks.filter(k => metricKeys.includes(k));
  if (kept.length >= 2) return kept;
  return _overlayDefaultKeys(metricKeys, _defaultChartKey(metricKeys, null));
}

function _overlayChipsHtml(metricKeys, picks) {
  return '<span class="scale-label">Overlay</span>' + metricKeys.map(k => {
    const on = picks.includes(k);
    const color = _metricColor(metricKeys, k);
    return '<button type="button" class="chart-overlay-chip' + (on ? ' on' : '') + '" '
      + 'aria-pressed="' + on + '" data-key="' + esc(k) + '" '
      + 'style="--chip-color:' + color + '">' + esc(k) + '</button>';
  }).join('');
}

function renderOverlayChart(container, metricsData, scaleOpts) {
  const canvas = _freshChartCanvas(container);
  if (!canvas) return;
  const picks = _overlayPicks.filter(k => metricsData[k] && metricsData[k].length);
  if (!picks.length) {
    canvas.parentNode.innerHTML = '<div class="chart-empty">Tick two or more metrics above to draw them on one chart.</div>';
    return;
  }
  charts._active = _createOverlayChart(canvas, picks, metricsData, scaleOpts);
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

  if (mode === 'overlay') {
    const chart = charts._active;
    // No chart means nothing is ticked: the empty prompt stays as it is.
    if (!chart) return !_overlayPicks.some(k => keys.includes(k));
    if (!chart.$overlay || !_applyOverlayPoints(chart, metricsData)) {
      renderOverlayChart(container, metricsData, getChartScaleOpts());
      return true;
    }
    chart.update('none');
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
    + '<button class="' + (viewMode === 'all' ? 'active' : '') + '" id="chart-view-all">Show All</button>'
    + '<button class="' + (viewMode === 'overlay' ? 'active' : '') + '" id="chart-view-overlay" '
    +   'title="Draw several of this run\'s metrics on one chart">Overlay</button>'
    + '</div>';
  if (isSingle) {
    html += '<label for="chart-metric-select">Metric</label>'
      + '<select id="chart-metric-select">' + options + '</select>';
  }
  html += '<button class="action-btn" id="chart-download-png" style="margin-left:auto" '
    + 'title="Download the visible chart(s) as PNG'
    + (viewMode === 'all' ? ' — one file per metric' : '')
    + '">⬇ PNG</button>';
  // "Show All" answers "how did every metric move", and the only way to take
  // that answer anywhere was one file per canvas, to be reassembled by hand in
  // something else. The sheet is the view itself, as one image.
  if (viewMode === 'all') {
    html += '<button class="action-btn" id="chart-download-sheet" '
      + 'title="Download every visible chart as one image">⬇ Sheet</button>';
  }
  html += '<button class="action-btn" id="chart-copy-png" '
    + 'title="Copy ' + (viewMode === 'all' ? 'the charts as one image' : 'this chart')
    + ' to the clipboard">⧉ Copy</button>';
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

  if (viewMode === 'overlay') {
    html += '<div class="chart-overlay-bar" id="chart-overlay-picks"></div>';
  }
  if (viewMode !== 'all') {
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
  const overlayBtn = container.querySelector('#chart-view-overlay');
  if (overlayBtn) overlayBtn.addEventListener('click', () => loadChartsTab(currentDetailId, 'overlay'));

  // Scale controls (shared by both modes)
  const applyBtn = container.querySelector('#chart-scale-apply');
  const resetBtn = container.querySelector('#chart-scale-reset');

  // Redraw at a new scale from `_chartsMetricsData` — the live poll keeps it
  // current, where the `metricsData` this tab was built from goes stale after
  // the first in-place update.
  function rerender(scale) {
    const data = _chartsMetricsData;
    if (viewMode === 'overlay') {
      renderOverlayChart(container, data, scale);
    } else if (viewMode === 'all') {
      renderAllCharts(container, data, scale);
    } else {
      const sel = container.querySelector('#chart-metric-select');
      if (sel) renderSingleChart(container, sel.value, data, scale);
    }
  }

  if (applyBtn) applyBtn.addEventListener('click', () => rerender(getChartScaleOpts()));
  if (resetBtn) resetBtn.addEventListener('click', () => { resetChartScaleInputs(); rerender(null); });

  const dlBtn = container.querySelector('#chart-download-png');
  if (dlBtn) dlBtn.addEventListener('click', downloadChartsPng);
  const sheetBtn = container.querySelector('#chart-download-sheet');
  if (sheetBtn) sheetBtn.addEventListener('click', downloadChartsSheetPng);
  const copyBtn = container.querySelector('#chart-copy-png');
  if (copyBtn) copyBtn.addEventListener('click', copyChartsPng);

  const smooth = container.querySelector('#chart-smoothing');
  if (smooth) smooth.addEventListener('input', () => setChartSmoothing(smooth.value));

  if (viewMode === 'all') {
    renderAllCharts(container, metricsData, initScale);
    return;
  }

  if (viewMode === 'overlay') {
    _overlaySavePicks(_overlayInitialPicks(metricKeys));
    const bar = container.querySelector('#chart-overlay-picks');
    const paint = () => { if (bar) bar.innerHTML = _overlayChipsHtml(metricKeys, _overlayPicks); };
    paint();
    // A tick redraws the chart, never the tab: the axis inputs and the
    // smoothing slider keep their state. Reads `_chartsMetricsData`, which the
    // live poll keeps current, so a tick mid-run draws the newest points.
    if (bar) bar.addEventListener('click', ev => {
      const chip = ev.target.closest('.chart-overlay-chip');
      if (!chip) return;
      const k = chip.dataset.key;
      const next = _overlayPicks.includes(k)
        ? _overlayPicks.filter(x => x !== k) : _overlayPicks.concat([k]);
      // The first pick anchors the left axis and stays where the reader put
      // it; the rest follow metric order, so the legend and the axis titles do
      // not reshuffle with the order things were clicked.
      const first = next.includes(_overlayPicks[0]) ? _overlayPicks[0] : null;
      const rest = metricKeys.filter(x => next.includes(x) && x !== first);
      _overlaySavePicks(first ? [first].concat(rest) : rest);
      paint();
      renderOverlayChart(container, _chartsMetricsData, getChartScaleOpts());
    });
    renderOverlayChart(container, metricsData, initScale);
    return;
  }

  // Single view controls
  const sel = container.querySelector('#chart-metric-select');
  if (!sel) return;

  sel.addEventListener('change', () => {
    _chartsSelectedKey = sel.value;
    renderSingleChart(container, sel.value, metricsData, getChartScaleOpts());
  });

  // Keep the user's pick across reloads; otherwise open on the run's primary
  // metric (see _defaultChartKey).
  const initialKey = _defaultChartKey(metricKeys, _chartsSelectedKey);
  sel.value = initialKey;
  _chartsSelectedKey = initialKey;
  renderSingleChart(container, initialKey, metricsData, initScale);
}

// The chart to open on. The user's remembered pick wins, then the run's primary
// metric — the number it is judged by is the one worth seeing first, and
// "whichever key sorted first" was an arbitrary default on the tab most likely
// to be read while a run is still going. Falls back to the first key.
function _defaultChartKey(metricKeys, remembered) {
  if (metricKeys.includes(remembered)) return remembered;
  // From the list row rather than a cached detail payload: `list_experiments`
  // already resolves `primary_metric` for every run, so this needs no new state
  // and no request.
  const row = (Array.isArray(allExperiments) ? allExperiments : [])
    .find(e => e.id === currentDetailId);
  const pk = ((row && row.primary_metric) || {}).key;
  if (pk && metricKeys.includes(pk)) return pk;
  return metricKeys[0];
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

// The charts on screen, in the order they are drawn, with the metric each one
// shows. `charts` is keyed `all_<metric>` in the grid view and `_active` in the
// single view, so this is the one place that has to know the difference.
function _visibleCharts() {
  if (_chartsViewMode === 'all') {
    return Object.keys(charts)
      .filter(k => k.startsWith('all_') && charts[k] && charts[k].canvas)
      .map(k => ({name: k.slice(4), canvas: charts[k].canvas}));
  }
  const c = charts._active;
  if (!c || !c.canvas) return [];
  return [{name: c.$title || 'chart', canvas: c.canvas}];
}

function _chartsInk() {
  return document.body.classList.contains('dark')
    ? {bg: '#1e1e1e', fg: '#e6e6e6'} : {bg: '#ffffff', fg: '#1a1a1a'};
}

// Every visible chart composited into one image: a grid, each cell captioned
// with its metric, on an opaque theme-matched ground. Chart.js canvases are
// transparent and device-pixel scaled, so the cell size comes from the canvases
// themselves rather than from CSS pixels -- scaling them to a guessed size is
// what makes an exported figure blurry.
function _chartsSheetCanvas(items) {
  const list = items || _visibleCharts();
  if (!list.length) return null;
  const cols = list.length === 1 ? 1 : (list.length <= 4 ? 2 : 3);
  const rows = Math.ceil(list.length / cols);
  const cw = Math.max(...list.map(i => i.canvas.width));
  const ch = Math.max(...list.map(i => i.canvas.height));
  const scale = Math.max(1, Math.round(cw / 600));   // caption size follows the DPR
  const cap = 22 * scale, pad = 14 * scale;
  const sheet = document.createElement('canvas');
  sheet.width = cols * cw + pad * (cols + 1);
  sheet.height = rows * (ch + cap) + pad * (rows + 1);
  const ctx = sheet.getContext('2d');
  const ink = _chartsInk();
  ctx.fillStyle = ink.bg;
  ctx.fillRect(0, 0, sheet.width, sheet.height);
  ctx.fillStyle = ink.fg;
  ctx.font = (13 * scale) + "px 'IBM Plex Mono', monospace";
  ctx.textBaseline = 'top';
  list.forEach((item, i) => {
    const col = i % cols, row = Math.floor(i / cols);
    const x = pad + col * (cw + pad);
    const y = pad + row * (ch + cap + pad);
    ctx.fillText(item.name, x, y);
    ctx.drawImage(item.canvas, x, y + cap);
  });
  return sheet;
}

// Writing an image to the clipboard needs both the async clipboard API and a
// secure context: 127.0.0.1 is one, a plain-http tunnel to the dashboard is not.
// A button that silently does nothing there reads as a broken button, so the
// reason is said and the download is named as the way through.
function _copyCanvasPng(canvas, what) {
  if (!canvas) { owlSay('No chart to copy'); return; }
  if (!(navigator.clipboard && window.ClipboardItem && window.isSecureContext)) {
    owlSay('This browser will not let a page write an image to the clipboard '
      + 'over plain http — use ⬇ PNG instead.');
    return;
  }
  const tmp = document.createElement('canvas');
  tmp.width = canvas.width;
  tmp.height = canvas.height;
  const ctx = tmp.getContext('2d');
  ctx.fillStyle = _chartsInk().bg;
  ctx.fillRect(0, 0, tmp.width, tmp.height);
  ctx.drawImage(canvas, 0, 0);
  tmp.toBlob(blob => {
    if (!blob) { owlSay('Could not render the image'); return; }
    navigator.clipboard.write([new window.ClipboardItem({'image/png': blob})])
      .then(() => owlSay('Copied ' + (what || 'the chart') + ' to the clipboard!'))
      .catch(err => owlSay('Clipboard refused the image: ' + (err && err.message || err)));
  });
}

function downloadChartsSheetPng() {
  const list = _visibleCharts();
  const sheet = _chartsSheetCanvas(list);
  if (!sheet) { owlSay('No charts to download'); return; }
  _downloadCanvasPng(sheet, 'charts.png');
  owlSay('Downloaded ' + list.length + ' chart' + (list.length > 1 ? 's' : '') + ' as one image');
}

function copyChartsPng() {
  const list = _visibleCharts();
  if (!list.length) { owlSay('No chart to copy'); return; }
  // One chart is itself; several are the sheet -- the clipboard holds one image,
  // so copying nine charts one at a time would keep only the last.
  if (list.length === 1) { _copyCanvasPng(list[0].canvas, 'the chart'); return; }
  _copyCanvasPng(_chartsSheetCanvas(list), list.length + ' charts');
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
      _downloadCanvasPng(c.canvas, safe(c.$title) + '.png');
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
    ? '<select id="overview-chart-select" class="select-sm" style="margin-right:8px">'
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
  const initialKey = _defaultChartKey(metricKeys, _overviewPreviewKey);
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
