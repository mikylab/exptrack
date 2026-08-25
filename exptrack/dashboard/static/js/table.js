

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

// The *selected* runs that are still `running`. Read from the loaded rows, so
// it costs no request and stays right as the 5s poll updates statuses.
function _selectedRunningIds() {
  return (typeof allExperiments !== 'undefined' ? allExperiments : [])
    .filter(e => selectedIds.has(e.id) && e.status === 'running')
    .map(e => e.id);
}

// Mark every running run in the selection as done. A crashed launcher leaves
// runs `running` in batches — a SLURM array, a killed sweep — and clearing them
// meant opening each detail view in turn.
async function bulkFinish() {
  // Only the ids the button counted. Posting the whole selection made the
  // result report "7 already done" about runs it never offered to touch, and
  // paid a lookup for each of them.
  const ids = _selectedRunningIds();
  const n = ids.length;
  if (!n) { owlSay('No running runs selected.'); return; }
  if (!confirm('Mark ' + n + ' running run' + (n === 1 ? '' : 's') + ' as done?')) return;
  const d = await postApi('/api/bulk-finish', {ids});
  if (!d || d.error) { owlSay('Finish failed' + (d && d.error ? ': ' + d.error : '.')); return; }
  // Say what actually happened to each group rather than one total: a run that
  // was already done is not a failure, and an id that resolved to nothing is
  // the one thing the user needs told.
  let msg = 'Finished ' + d.finished + ' run' + (d.finished === 1 ? '' : 's');
  if (d.already_done) msg += ' (' + d.already_done + ' already done)';
  if (d.failed && d.failed.length) msg += ' — ' + d.failed.length + ' failed';
  owlSay(msg + '.');
  loadStats();
  loadExperiments();
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
  // Only when the selection actually contains running runs, and counting only
  // those: a "Finish (7)" that would change 2 runs offers an action against
  // the set the user picked rather than the set it can act on.
  const running = _selectedRunningIds().length;
  if (running) {
    html += '<button onclick="bulkFinish()" title="Mark the running runs in this '
      + 'selection as done">Finish (' + running + ')</button>';
  }
  html += _buildExportDropdown(n);
  html += _buildCopyDropdown(n);
  html += '<button onclick="bulkCompact()">Compact</button>';
  html += '<button class="danger" onclick="sidebarBulkDelete()">Delete (' + n + ')</button>';
  bar.innerHTML = html;
}

// sidebarBulkDelete() now lives in JS_TRASH — opens the confirm modal with
// aggregate scope and a Trash / Permanent-delete choice.

// Turn a /api/bulk-export response into text, or null when the request failed.
// postApi() returns null on a failed request and the server reports errors as
// {"error": ...} — neither is export content, and writing them into a blob
// produced a downloaded `.csv` containing `{"error":...}` under a success
// toast.
function _exportText(data, fmt) {
  if (!data || data.error) return null;
  if (fmt === 'plain') {
    const exps = Array.isArray(data) ? data : [data];
    return exps.map(d => _formatExpPlainText(d)).join('\n' + '='.repeat(60) + '\n\n');
  }
  if (data.content) return data.content;
  return JSON.stringify(data, null, 2);
}

async function sidebarExportFmt(fmt) {
  owlSpeak('export');
  const ids = [...selectedIds];
  const data = await postApi('/api/bulk-export',
                             {ids, format: fmt === 'plain' ? 'json' : fmt});
  const text = _exportText(data, fmt);
  if (text === null) {
    owlSay('Export failed' + (data && data.error ? ': ' + data.error : '.'));
    return;
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
  // The export payload carries a per-key summary (`metrics`); a full export
  // adds the raw points, which we summarise the same way rather than dumping.
  const ms = d.metrics || _summarizeMetricSeries(d.metrics_series);
  if (Object.keys(ms).length) {
    lines.push('Metrics:');
    Object.entries(ms).forEach(([k,s]) => {
      const last = s.last == null ? '--' : s.last;
      lines.push('  ' + k + ' = ' + last + ' (' + s.count + ' points' +
        (s.min == null ? '' : ', min ' + s.min + ', max ' + s.max) + ')');
    });
    lines.push('');
  }
  const artSum = d.artifacts_summary;
  if (artSum ? artSum.total : (d.artifacts || []).length) {
    // Capped server-side for the same reason the markdown export is: a
    // checkpoint-per-epoch run has thousands, and listing them all buries
    // everything above. The summary states the shape of what is not listed.
    const shown = d.artifacts || [];
    const total = artSum ? artSum.total : shown.length;
    const omitted = artSum ? artSum.omitted : Math.max(0, total - ARTIFACT_LIST_LIMIT);
    lines.push('Artifacts (' + total + '):');
    if (omitted) {
      if (artSum) {
        lines.push('  ' + artSum.by_type.map(t => t.count + ' ' + t.type).join(', '));
        artSum.by_dir.slice(0, 5).forEach(g =>
          lines.push('  ' + String(g.count).padStart(6) + ' in ' + g.dir));
      } else {
        const s = _summarizeArtifacts(shown);
        lines.push('  ' + s.byType.map(([k, n]) => n + ' ' + k).join(', '));
        s.byDir.slice(0, 5).forEach(([dir, items]) =>
          lines.push('  ' + String(items.length).padStart(6) + ' in ' + dir));
      }
      lines.push('');
    }
    shown.slice(0, ARTIFACT_LIST_LIMIT)
      .forEach(a => lines.push('  ' + a.label + ': ' + a.path));
    if (omitted) {
      lines.push('  … and ' + omitted + ' more (export as JSON (full) for the complete list)');
    }
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
  const data = await postApi('/api/bulk-export',
                             {ids, format: fmt === 'plain' ? 'json' : fmt});
  const text = _exportText(data, fmt);
  if (text === null) {
    owlSay('Copy failed' + (data && data.error ? ': ' + data.error : '.'));
    return;
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
  _storageSet('exptrack-group-by', field);
  collapsedGroups.clear();
  // When grouping by day, fold away older days so the most recent stays in view.
  if (field === 'day') {
    const keys = [];
    for (const e of getFilteredExperiments()) {
      const k = GROUP_MODES.day.keyOf(e);   // same key renderExperiments groups on
      if (!keys.includes(k)) keys.push(k);
    }
    keys.slice(1).forEach(k => collapsedGroups.add(k));
  }
  const sel = document.getElementById('group-by-select');
  if (sel && sel.value !== field) sel.value = field;
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
    // Params read most naturally low\u2192high (lr 0.001 \u2026 0.1), like the other
    // value-ish columns; timestamps and metrics default to newest/highest first.
    sortDir = (col === 'name' || col === 'status' || col === 'id' || isParamCol(col)) ? 'asc' : 'desc';
  }
  renderExperiments();
  updateSortHeaders();
}

function updateSortHeaders() {
  document.querySelectorAll('#exp-table th.sortable').forEach(th => {
    // Not \w+ \u2014 param column ids contain ':' and '-' (e.g. "param:--lr").
    const col = th.getAttribute('onclick').match(/toggleSort\('([^']+)'\)/)?.[1];
    th.classList.toggle('sort-active', col === sortCol);
    const arrow = th.querySelector('.sort-arrow');
    if (arrow) arrow.textContent = col === sortCol ? (sortDir === 'asc' ? '\u25B2' : '\u25BC') : '';
  });
}

// Comparator shared by the metric: and param: sort branches. Runs missing the
// value always sort to the bottom, regardless of sort direction — flipping the
// direction should reorder the runs that *have* the value, not promote the ones
// that don't. Present values compare normally and then honour `sortDir`.
// `dir` overrides the list's own `sortDir`, so a view with its own sort state
// (the parameter matrix) shares this rule instead of restating it — the two
// had already drifted, one comparing lowercased strings and the other using
// localeCompare, so the same param set sorted differently in the two views.
function _cmpMissingLast(va, vb, aMiss, bMiss, dir) {
  if (aMiss && bMiss) return 0;
  if (aMiss) return 1;
  if (bMiss) return -1;
  const cmp = va < vb ? -1 : va > vb ? 1 : 0;
  const desc = dir === undefined ? sortDir === 'desc' : dir < 0;
  return desc ? -cmp : cmp;
}

// `opts.includeFailed` forces failed runs through regardless of the `showFailed`
// toggle. The parameter matrix needs that: it carries its own "Show failed"
// control, and the list's toggle would otherwise strip those runs out before
// the matrix ever saw them — leaving its own checkbox visibly checked and
// doing nothing, and silently under-reporting the search.
function getFilteredExperiments(opts) {
  // Defensive: every render path funnels through here, so a non-array payload
  // (failed fetch, unexpected error object) must degrade to "no rows" rather
  // than throw and take the whole table/sidebar render down with it.
  let exps = Array.isArray(allExperiments) ? allExperiments : [];
  if (hiddenIds.size > 0) {
    exps = exps.filter(e => !hiddenIds.has(e.id));
  }
  if (tagFilter) {
    exps = exps.filter(e => (e.tags || []).includes(tagFilter));
  }
  if (studyFilter) {
    exps = exps.filter(e => (e.studies || []).includes(studyFilter));
  }
  if (autoNamedOnly) {
    exps = exps.filter(e => e.name_is_auto || recentlyRenamedIds.has(e.id));
  }
  if (!showFailed && currentFilter !== 'failed' && !(opts && opts.includeFailed)) {
    // Broken runs are hidden by default so the user never has to remember to
    // delete them; the "Show failed" toggle brings them back. But when the user
    // has explicitly filtered to the "Failed" status chip, honor that — else the
    // sidebar/table would show nothing.
    exps = exps.filter(e => e.status !== 'failed');
  }
  if (dateRange) {
    if (dateRange === 'today') {
      const todayKey = dayKeyOf(new Date().toISOString());
      exps = exps.filter(e => dayKeyOf(e.created_at) === todayKey);
    } else {
      const days = dateRange === '7d' ? 7 : dateRange === '30d' ? 30 : 0;
      if (days) {
        const cutoff = Date.now() - days * 86400 * 1000;
        exps = exps.filter(e => { const d = expDate(e.created_at); return d && !isNaN(d) && d.getTime() >= cutoff; });
      }
    }
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
  // Sorting by the Result column ranks runs against each other, so it needs the
  // one metric the *set* is judged by — computed once here, not per comparison.
  // Runs resolving a different key sink rather than interleaving: 0.11 of a
  // loss and 0.92 of an accuracy have no order between them, and sorting them
  // together produces a ranking that looks authoritative and means nothing.
  // Mirrors core/param_study.consensus_metric (most common key wins).
  const primaryKey = sortCol === 'primary' ? consensusMetricKey(exps) : '';

  // Sort: pinned first, then by sort column
  exps = [...exps].sort((a, b) => {
    const ap = pinnedIds.has(a.id) ? 0 : 1;
    const bp = pinnedIds.has(b.id) ? 0 : 1;
    if (ap !== bp) return ap - bp;
    let av, bv;
    // Sort by a metric value: sortCol is 'metric:<key>'. Runs missing that
    // metric always sort to the bottom regardless of direction.
    if (sortCol.startsWith('metric:')) {
      const mk = sortCol.slice(7);
      const ma = a.metrics && a.metrics[mk] ? Number(a.metrics[mk].value) : null;
      const mb = b.metrics && b.metrics[mk] ? Number(b.metrics[mk].value) : null;
      return _cmpMissingLast(ma, mb, ma === null || isNaN(ma), mb === null || isNaN(mb));
    }
    // Sort by each run's own primary metric. Two runs can resolve *different*
    // keys (a run override, a per-study setting), so this orders by whatever
    // each run is judged by rather than by one shared key — which is the point
    // of the column, and also why it can't reuse the `metric:` branch above.
    // Runs with no value sink, as everywhere else.
    if (sortCol === 'primary') {
      const pv = e => {
        const p = e.primary_metric || {};
        if (primaryKey && p.key !== primaryKey) return null;
        return typeof p.final === 'number' ? p.final : null;
      };
      const va = pv(a), vb = pv(b);
      return _cmpMissingLast(va, vb, va === null, vb === null);
    }
    // Sort by a param value: sortCol is 'param:<key>'. Numeric params compare
    // numerically (so lr 0.003 < 0.01 < 0.1, not the string order "0.003" <
    // "0.01" < "0.1" which happens to agree here but breaks on e.g. 2 vs 10);
    // everything else falls back to a string compare. Runs missing the param
    // always sort to the bottom, matching the metric-sort behaviour above.
    if (isParamCol(sortCol)) {
      const pk = paramColKey(sortCol);
      const pa = (a.params || {})[pk];
      const pb = (b.params || {})[pk];
      const na = Number(pa), nb = Number(pb);
      const numeric = pa !== '' && pb !== '' && !isNaN(na) && !isNaN(nb);
      return _cmpMissingLast(
        numeric ? na : String(pa).toLowerCase(),
        numeric ? nb : String(pb).toLowerCase(),
        pa === undefined || pa === null,
        pb === undefined || pb === null);
    }
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
