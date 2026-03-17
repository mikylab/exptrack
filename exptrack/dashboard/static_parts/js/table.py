"""Table rendering, sorting, column resizing, and bulk selection."""

JS_TABLE = r"""

function _buildExportDropdown(n) {
  let h = '<span style="position:relative;display:inline-block">';
  h += '<button class="export-btn" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'block\'?\'none\':\'block\'">Export (' + n + ') \u25BE</button>';
  h += '<div class="export-dropdown-menu" style="display:none">';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'json\')">JSON</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'csv\')">CSV</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'tsv\')">TSV</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'markdown\')">Markdown</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'plain\')">Plain Text</button>';
  h += '</div></span>';
  return h;
}

function _buildCopyDropdown(n) {
  let h = '<span style="position:relative;display:inline-block">';
  h += '<button class="export-btn" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'block\'?\'none\':\'block\'">Copy (' + n + ') \u25BE</button>';
  h += '<div class="export-dropdown-menu" style="display:none">';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'json\')">JSON</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'csv\')">CSV</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'tsv\')">TSV</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'markdown\')">Markdown</button>';
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'plain\')">Plain Text</button>';
  h += '</div></span>';
  return h;
}

function renderTableActionsBar() {
  const bar = document.getElementById('table-actions-bar');
  if (!bar) return;
  const n = selectedIds.size;
  if (n === 0) {
    bar.style.display = 'none';
    return;
  }
  bar.style.display = 'flex';
  let html = '<button class="deselect-btn" onclick="deselectAll()" title="Deselect all">&times; Deselect All</button>';
  html += '<span class="sel-count">' + n + ' selected</span>';
  if (n >= 2) {
    html += '<button class="primary" onclick="compareSelected()">Compare (' + n + ')</button>';
  }
  html += '<button onclick="hideSelected()">Hide (' + n + ')</button>';
  html += '<button onclick="promptBulkAddToStudy()">Add to Study</button>';
  html += _buildExportDropdown(n);
  html += _buildCopyDropdown(n);
  html += '<button onclick="bulkCompact()">Compact</button>';
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
  bar.innerHTML = html;
}

async function sidebarBulkDelete() {
  owlSpeak('delete');
  if (!confirm('Delete ' + selectedIds.size + ' experiments? This cannot be undone.')) return;
  const ids = [...selectedIds];
  const d = await postApi('/api/bulk-delete', {ids});
  if (d.ok) {
    selectedIds.clear();
    showWelcome();
    loadStats();
    loadExperiments();
  } else alert(d.error || 'Failed');
}

async function sidebarExportFmt(fmt) {
  owlSpeak('export');
  const ids = [...selectedIds];
  let text;
  if (fmt === 'plain') {
    // Plain text: fetch JSON data and format client-side
    const data = await postApi('/api/bulk-export', {ids, format: 'json'});
    const exps = Array.isArray(data) ? data : [data];
    text = exps.map(d => _formatExpPlainText(d)).join('\n' + '='.repeat(60) + '\n\n');
  } else {
    const data = await postApi('/api/bulk-export', {ids, format: fmt});
    if (data.content) {
      text = data.content;
    } else if (Array.isArray(data)) {
      text = JSON.stringify(data, null, 2);
    } else {
      text = JSON.stringify(data, null, 2);
    }
  }
  const ext = {json:'.json', markdown:'.md', csv:'.csv', tsv:'.tsv', plain:'.txt'};
  const filename = 'exptrack_export_' + ids.length + '_experiments' + (ext[fmt] || '.txt');
  const mime = fmt === 'json' ? 'application/json' : 'text/plain';
  const blob = new Blob([text], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  // Close dropdown
  document.querySelectorAll('.export-dropdown-menu').forEach(d => d.style.display = 'none');
  owlSay('Downloaded ' + filename);
}

function _formatExpPlainText(d) {
  // Shared plain-text formatter — same format used by the detail view export
  let lines = [];
  lines.push('Experiment: ' + (d.name || ''));
  lines.push('ID: ' + (d.id || ''));
  lines.push('Status: ' + (d.status || ''));
  if (d.created_at) lines.push('Created: ' + d.created_at);
  if (d.duration_s) lines.push('Duration: ' + fmtDur(d.duration_s));
  if (d.script) lines.push('Script: ' + d.script);
  if (d.command) lines.push('Command: ' + d.command);
  if (d.python_ver) lines.push('Python: ' + d.python_ver);
  if (d.git_branch) lines.push('Branch: ' + d.git_branch);
  if (d.git_commit) lines.push('Commit: ' + d.git_commit);
  if (d.hostname) lines.push('Hostname: ' + d.hostname);
  if (d.tags && d.tags.length) lines.push('Tags: ' + d.tags.join(', '));
  if (d.studies && d.studies.length) lines.push('Studies: ' + d.studies.join(', '));
  if (d.stage != null) lines.push('Stage: ' + d.stage + (d.stage_name ? ' (' + d.stage_name + ')' : ''));
  if (d.output_dir) lines.push('Output Dir: ' + d.output_dir);
  if (d.notes) lines.push('Notes: ' + d.notes);
  lines.push('');
  const params = d.params || {};
  if (Object.keys(params).length) {
    lines.push('Parameters:');
    Object.entries(params).forEach(([k,v]) => lines.push('  ' + k + ' = ' + JSON.stringify(v)));
    lines.push('');
  }
  const vars = d.variables || {};
  if (Object.keys(vars).length) {
    lines.push('Variables:');
    Object.entries(vars).forEach(([k,v]) => lines.push('  ' + k + ' = ' + JSON.stringify(v)));
    lines.push('');
  }
  const ms = d.metrics_series || {};
  if (Object.keys(ms).length) {
    lines.push('Metrics:');
    Object.entries(ms).forEach(([k,pts]) => {
      const last = pts.length ? pts[pts.length-1].value : '--';
      lines.push('  ' + k + ' = ' + last + ' (' + pts.length + ' steps)');
    });
    lines.push('');
  }
  if (d.artifacts && d.artifacts.length) {
    lines.push('Artifacts:');
    d.artifacts.forEach(a => lines.push('  ' + a.label + ': ' + a.path));
    lines.push('');
  }
  const changes = d.code_changes || {};
  if (Object.keys(changes).length) {
    lines.push('Code Changes:');
    Object.entries(changes).forEach(([k,v]) => lines.push('  ' + k + ': ' + JSON.stringify(v)));
    lines.push('');
  }
  const ts = d.timeline_summary || {};
  if (ts.total_events) {
    lines.push('Timeline: ' + ts.total_events + ' events (' +
      (ts.cell_executions || 0) + ' cells, ' +
      (ts.variable_sets || 0) + ' vars, ' +
      (ts.artifact_events || 0) + ' artifacts)');
  }
  return lines.join('\n');
}

async function sidebarCopyFmt(fmt) {
  const ids = [...selectedIds];
  let text;
  if (fmt === 'plain') {
    const data = await postApi('/api/bulk-export', {ids, format: 'json'});
    const sections = (Array.isArray(data) ? data : []).map(d => _formatExpPlainText(d));
    text = sections.join('\n\n---\n\n');
  } else {
    const data = await postApi('/api/bulk-export', {ids, format: fmt});
    if (data.content) {
      text = data.content;
    } else if (Array.isArray(data)) {
      text = JSON.stringify(data, null, 2);
    } else {
      text = JSON.stringify(data, null, 2);
    }
  }
  await navigator.clipboard.writeText(text);
  document.querySelectorAll('.export-dropdown-menu').forEach(d => d.style.display = 'none');
  owlSay('Copied ' + ids.length + ' experiment(s) as ' + fmt.toUpperCase() + ' to clipboard!');
}

async function sidebarCopyText() {
  sidebarCopyFmt('plain');
}

function setGroup(field) {
  groupBy = field;
  collapsedGroups.clear();
  document.querySelectorAll('#group-bar button').forEach(b => {
    const val = b.getAttribute('data-group');
    b.classList.toggle('active', val === field);
  });
  renderExperiments();
}

function toggleGroup(key) {
  if (collapsedGroups.has(key)) collapsedGroups.delete(key);
  else collapsedGroups.add(key);
  renderExperiments();
}

function toggleSort(col) {
  if (sortCol === col) {
    sortDir = sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    sortCol = col;
    sortDir = (col === 'name' || col === 'status' || col === 'id') ? 'asc' : 'desc';
  }
  renderExperiments();
  updateSortHeaders();
}

function updateSortHeaders() {
  document.querySelectorAll('#exp-table th.sortable').forEach(th => {
    const col = th.getAttribute('onclick').match(/toggleSort\('(\w+)'\)/)?.[1];
    th.classList.toggle('sort-active', col === sortCol);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = col === sortCol ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : '';
  });
}

function getFilteredExperiments() {
  let exps = allExperiments;
  if (hiddenIds.size > 0) {
    exps = exps.filter(e => !hiddenIds.has(e.id));
  }
  if (tagFilter) {
    exps = exps.filter(e => (e.tags || []).includes(tagFilter));
  }
  if (studyFilter) {
    exps = exps.filter(e => (e.studies || []).includes(studyFilter));
  }
  if (searchQuery) {
    const q = searchQuery.toLowerCase();
    exps = exps.filter(e =>
      e.name.toLowerCase().includes(q) ||
      e.id.toLowerCase().includes(q) ||
      (e.tags || []).some(t => t.toLowerCase().includes(q)) ||
      (e.studies || []).some(g => g.toLowerCase().includes(q)) ||
      Object.keys(e.params || {}).some(k => k.toLowerCase().includes(q)) ||
      Object.values(e.params || {}).some(v => String(v).toLowerCase().includes(q)) ||
      (e.git_branch || '').toLowerCase().includes(q) ||
      (e.notes || '').toLowerCase().includes(q)
    );
  }
  // Sort: pinned first, then by sort column
  exps = [...exps].sort((a, b) => {
    const ap = pinnedIds.has(a.id) ? 0 : 1;
    const bp = pinnedIds.has(b.id) ? 0 : 1;
    if (ap !== bp) return ap - bp;
    let av, bv;
    switch (sortCol) {
      case 'name': av = a.name.toLowerCase(); bv = b.name.toLowerCase(); break;
      case 'status': av = a.status; bv = b.status; break;
      case 'id': av = a.id; bv = b.id; break;
      case 'tags': av = (a.tags||[]).length; bv = (b.tags||[]).length; break;
      case 'studies': av = (a.studies||[]).length; bv = (b.studies||[]).length; break;
      case 'stage': av = a.stage != null ? a.stage : Infinity; bv = b.stage != null ? b.stage : Infinity; break;
      case 'created_at': default: av = a.created_at||''; bv = b.created_at||''; break;
    }
    let cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'desc' ? -cmp : cmp;
  });
  return exps;
}
"""

# Stats loading, experiment list, row rendering
