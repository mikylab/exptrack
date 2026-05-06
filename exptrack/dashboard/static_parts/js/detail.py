"""Experiment detail panel, tabs, metric charts, and export."""

JS_DETAIL = r"""

async function compareSelected() {
  if (selectedIds.size < 2) return;
  owlSpeak('compare');
  showCompareView();
  const ids = [...selectedIds];
  if (ids.length === 2) {
    // Pair compare
    document.getElementById('compare-pair-tab').classList.add('active');
    document.getElementById('compare-multi-tab').classList.remove('active');
    document.getElementById('compare-pair-content').style.display = '';
    document.getElementById('compare-multi-content').style.display = 'none';
    await populateCompareDropdowns();
    document.getElementById('cmp-id1').value = ids[0];
    document.getElementById('cmp-id2').value = ids[1];
    doCompare();
  } else {
    // Multi compare
    document.getElementById('compare-pair-tab').classList.remove('active');
    document.getElementById('compare-multi-tab').classList.add('active');
    document.getElementById('compare-pair-content').style.display = 'none';
    document.getElementById('compare-multi-content').style.display = '';
    await populateMultiCompareSelector();
    doMultiCompare(ids);
  }
}

function filterExps(status) {
  if (status) owlSpeak('filter');
  currentFilter = status;
  renderStatusChips();
  loadExperiments();
}

async function populateCompareDropdowns() {
  const exps = await api('/api/experiments?limit=100');
  const sel1 = document.getElementById('cmp-id1');
  const sel2 = document.getElementById('cmp-id2');
  const prev1 = sel1.value, prev2 = sel2.value;
  const makeOpts = (exps) => '<option value="">-- Select experiment --</option>' +
    exps.map(e => `<option value="${e.id}">${e.id.slice(0,6)} | ${esc(e.name.slice(0,35))} | ${e.status} | ${fmtDt(e.created_at)}</option>`).join('');
  sel1.innerHTML = makeOpts(exps);
  sel2.innerHTML = makeOpts(exps);
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
  // Toggle: clicking same experiment deselects
  if (currentDetailId === id) {
    showWelcome();
    return;
  }
  return refreshDetail(id);
}

async function refreshDetail(id) {
  // Only auto-expand the sidebar when transitioning to a different experiment
  // (or entering detail view from welcome/compare). On in-place refreshes from
  // logging a metric / adding a param / etc, leave the sidebar in whatever
  // state the user left it.
  const isInitialEntry = currentDetailId !== id ||
    document.getElementById('detail-view').style.display === 'none';
  currentDetailId = id;
  showDetailView();
  if (isInitialEntry) {
    document.getElementById('exp-sidebar').classList.remove('collapsed');
  }
  renderExpList();

  const [exp, metricsData, diffData] = await Promise.all([
    api('/api/experiment/' + id),
    api('/api/metrics/' + id),
    api('/api/diff/' + id),
  ]);
  if (exp.error) return;

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
    } else if (k === '_tags') {
      // skip, shown elsewhere
    } else {
      regularParams[k] = v;
    }
  }

  const paramSources = exp.param_sources || {};
  const paramRows = Object.entries(regularParams).map(([k,v]) => {
    const src = paramSources[k] || 'auto';
    const isManual = src === 'manual';
    const keyColor = isManual ? 'var(--tl-metric)' : 'var(--blue)';
    const keyAttrs = isManual
      ? ` class="editable-hint" ondblclick="startParamRename('${exp.id}','${esc(k)}',this)" title="Double-click to rename"`
      : '';
    const valAttrs = isManual
      ? ` class="editable-hint" ondblclick="startParamEdit('${exp.id}','${esc(k)}',this)" title="Double-click to edit"`
      : '';
    const delBtn = isManual
      ? `<span class="result-del-x" onclick="event.stopPropagation();deleteParam('${exp.id}','${esc(k)}')" title="Delete">&times;</span>`
      : '';
    return `<tr><td style="color:${keyColor}"${keyAttrs}>${esc(k)}</td><td${valAttrs}>${esc(JSON.stringify(v))}</td><td><span class="source-badge ${src}">${src}</span> ${delBtn}</td></tr>`;
  }).join('');

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
    const delBtn = `<span class="result-del-x" onclick="event.stopPropagation();deleteMetric('${exp.id}','${esc(m.key)}')" title="Delete all">&times;</span>`;
    const editAttr = isManual ? ` class="editable-hint" ondblclick="startResultEdit('${exp.id}','${esc(m.key)}',this)" title="Double-click to edit"` : '';
    const displayKey = showFullKey ? abbrevMetric(m.key) : abbrevMetric(m.key.includes('/') ? m.key.split('/').slice(1).join('/') : m.key);
    const sMin = m.step_min, sMax = m.step_max;
    const stepStr = sMin == null ? '--' : (sMin === sMax ? String(sMin) : sMin + '-' + sMax);
    return `<tr><td style="color:${keyColor}" class="editable-hint" ondblclick="startMetricRename('${exp.id}','${esc(m.key)}',this)" title="${esc(m.key)} — double-click to rename">${esc(displayKey)}</td><td${editAttr}>${m.last?.toFixed(4) ?? '--'}</td><td>${m.min?.toFixed(4) ?? '--'}</td><td>${m.max?.toFixed(4) ?? '--'}</td><td style="font-size:12px;color:var(--muted)">${stepStr}</td><td><span class="source-badge ${src}">${src}</span> ${delBtn}</td></tr>`;
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
      ? `<button onclick="viewLogFile('${esc(a.path)}','${esc(a.label)}')" title="View contents">view</button>`
      : '';
    const searchKey = ((a.label || '') + ' ' + (a.path || '')).toLowerCase();
    const overflow = i >= ARTIFACT_TRUNCATE_THRESHOLD ? ' overflow' : '';
    return `<tr data-artifact-search="${esc(searchKey)}" class="artifact-row-tr${overflow}"><td><div class="artifact-row">${artifactTypeBadge(a.path)} ${esc(a.label)}</div></td><td class="artifact-path-cell" title="${esc(a.path)}">${esc(a.path)}</td><td><div class="artifact-actions">${viewBtn}<button onclick="editArtifact('${exp.id}','${esc(a.label)}','${esc(a.path)}')">edit</button><button class="art-del" onclick="deleteArtifact('${exp.id}','${esc(a.label)}','${esc(a.path)}')">del</button></div></td></tr>`;
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

  // Code changes
  let codeHtml = '';
  if (Object.keys(codeChanges).length) {
    codeHtml = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Code Changes</h2><div class="section-body"><div class="code-changes">';
    for (const [k, v] of Object.entries(codeChanges)) {
      const label = k === '_code_changes' ? 'Script diff vs. last commit' : k.replace('_code_change/','Cell ');
      const parts = String(v).split('; ').map(part => {
        const trimmed = part.trim();
        if (trimmed.startsWith('+')) return '<span class="diff-add">' + esc(trimmed) + '</span>';
        if (trimmed.startsWith('-')) return '<span class="diff-del">' + esc(trimmed) + '</span>';
        return esc(trimmed);
      }).join('\n');
      codeHtml += '<div class="change-item"><div class="change-label">' + esc(label) + '</div><div class="change-diff">' + parts + '</div></div>';
    }
    codeHtml += '</div></div>';
  }

  // Variable changes
  let varHtml = '';
  if (Object.keys(varChanges).length) {
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
    varHtml = '<h2 class="section-toggle" onclick="this.classList.toggle(\'collapsed\')">Variables (' + Object.keys(varChanges).length + ')</h2><div class="section-body"><div class="var-changes">';
    const renderGroup = (title, vars) => {
      if (!Object.keys(vars).length) return '';
      let h = '<div class="var-section-title">' + title + ' (' + Object.keys(vars).length + ')</div><table>';
      for (const [k, v] of Object.entries(vars)) {
        let displayVal = String(v);
        // Strip "varname = " prefix if present (capture stores "x = expr  # type")
        if (displayVal.startsWith(k + ' = ')) {
          displayVal = displayVal.slice(k.length + 3);
        }
        h += '<tr><td class="var-name">' + esc(k) + '</td><td>= ' + esc(displayVal) + '</td></tr>';
      }
      return h + '</table>';
    };
    varHtml += renderGroup('Scalars', scalars);
    varHtml += renderGroup('Arrays & Tensors', arrays);
    varHtml += renderGroup('Other', other);
    varHtml += '</div></div>';
  }

  // Summary card
  const totalMetricSteps = exp.metrics.reduce((s,m) => s + m.n, 0);
  const numVars = Object.keys(varChanges).length;
  const numArt = exp.artifacts.length;
  const numCodeChanges = Object.keys(codeChanges).length;
  let summaryHtml = '<div class="summary-card"><div class="summary-grid">';
  summaryHtml += '<div class="summary-item"><div class="val">' + Object.keys(regularParams).length + '</div><div class="lbl">Params</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + exp.metrics.length + '</div><div class="lbl">Metric Keys</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + totalMetricSteps + '</div><div class="lbl">Metric Points</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numVars + '</div><div class="lbl">Variables</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numArt + '</div><div class="lbl">Artifacts</div></div>';
  summaryHtml += '<div class="summary-item"><div class="val">' + numCodeChanges + '</div><div class="lbl">Code Changes</div></div>';
  summaryHtml += '</div>' + _compactStatusHtml(exp) + '</div>';

  // Diff
  let diffHtml = '';
  let diffCompacted = false;
  if (diffData.diff) {
    if (diffData.diff.startsWith('[compacted')) {
      diffCompacted = true;
      diffHtml = '<div style="padding:16px;color:var(--yellow,#e8a735);font-style:italic">'
        + esc(diffData.diff)
        + (diffData.commit ? '<br><span style="color:var(--muted);font-size:12px">To recover: git diff ' + esc(diffData.commit) + '~1 ' + esc(diffData.commit) + '</span>' : '')
        + '</div>';
    } else {
      diffHtml = diffData.diff.split('\n').map(line => {
        if (line.startsWith('+') && !line.startsWith('+++')) return '<span class="diff-add">' + esc(line) + '</span>';
        if (line.startsWith('-') && !line.startsWith('---')) return '<span class="diff-del">' + esc(line) + '</span>';
        if (line.startsWith('@@')) return '<span class="diff-hunk">' + esc(line) + '</span>';
        return esc(line);
      }).join('\n');
    }
  }

  const expTags = exp.tags || [];
  const tagsHtml = '<span class="detail-tags-inline" id="detail-tags-area">' +
    (expTags.length
      ? expTags.map(t => '<span class="tag-removable">#' + esc(t) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteTagInline(\'' + exp.id + '\',\'' + esc(t) + '\')" title="Remove tag from this experiment">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-tag-input-area"></span>' +
    '</span>';

  const expStudies = exp.studies || [];
  const studiesDetailHtml = '<span class="detail-tags-inline" id="detail-studies-area">' +
    (expStudies.length
      ? expStudies.map(g => '<span class="tag-removable" style="background:rgba(44,90,160,0.1);color:var(--blue)">' + esc(g) +
        ' <span class="tag-delete" onclick="event.stopPropagation();deleteStudyInline(\'' + exp.id + '\',\'' + esc(g) + '\')" title="Remove study">&times;</span>' +
        '</span>').join('')
      : '') +
    '<span class="tag-input-area" id="detail-study-input-area"></span>' +
    '</span>';

  document.getElementById('detail-panel').innerHTML = `
    <div class="detail" style="border:none;padding:4px 16px;margin:0">
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

      <!-- Header with name + actions -->
      <div class="detail-header">
        <h2 id="detail-name" class="editable-hint" ondblclick="startInlineRename('${exp.id}',this)" title="Double-click to rename">${esc(exp.name)}</h2>
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
          <button class="action-btn danger" onclick="deleteExp('${exp.id}','${esc(exp.name)}')">Delete</button>
          <button class="close-btn" onclick="showWelcome()" title="Back to list">&times;</button>
        </div>
      </div>

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
            ${exp.command ? '<div class="reproduce-box"><div class="reproduce-header"><span class="label">Reproduce</span><span><button class="copy-btn" onclick="saveReproduceToCommands(\'' + exp.id + '\')" title="Save to Commands notepad">&gt;_ Save</button><button class="copy-btn" data-cmd="' + esc(exp.command).replace(/"/g,'&quot;') + '" onclick="navigator.clipboard.writeText(this.dataset.cmd).then(()=>owlSay(\'Copied!\'))">Copy</button></span></div><code class="reproduce-cmd editable-hint" id="detail-command" ondblclick="startDetailCommandEdit(\'' + exp.id + '\')" title="Double-click to edit">' + esc(exp.command) + '</code></div>' : '<div class="reproduce-box"><div class="reproduce-header"><span class="label">Reproduce</span></div><code class="reproduce-cmd editable-hint" id="detail-command" ondblclick="startDetailCommandEdit(\'' + exp.id + '\')" title="Double-click to add command" style="color:var(--muted);cursor:pointer">double-click to add command</code></div>'}
            <h2 class="section-toggle" onclick="this.classList.toggle('collapsed')">Params (${Object.keys(regularParams).length})<span class="section-actions" onclick="event.stopPropagation()"><button class="copy-btn" title="Copy as a markdown table — pastes into lab notebooks, Obsidian, GitHub, Jupyter markdown cells" onclick="copyExportFmt('${exp.id}','params-md')">Copy</button></span></h2>
            <div class="section-body">
            ${paramRows ? '<table class="params-table"><tr><th>Key</th><th>Value</th><th>Source</th></tr>'+paramRows+'</table>' : '<p style="color:var(--muted);font-size:13px">No params yet.</p>'}
            ${addParamForm}
            </div>
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
"""

# Compare view
