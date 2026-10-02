

function _buildExportDropdown(n) {
  let h = '<span style="position:relative;display:inline-block">';
  h += '<button class="export-btn" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display===\'block\'?\'none\':\'block\'">Export (' + n + ') \u25BE</button>';
  h += '<div class="export-dropdown-menu" style="display:none">';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'json\')">JSON</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'csv\')">CSV</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'tsv\')">TSV</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'markdown\')">Markdown</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'plain\')">Plain Text</button>';
  h += '<button class="action-btn" onclick="sidebarExportFmt(\'html\')" title="A page with real tables — opens in a browser, imports into OneNote or Word">HTML</button>';
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
  h += '<button class="action-btn" onclick="sidebarCopyFmt(\'markdown\')" title="Pastes as tables in OneNote, Word and Outlook; as markdown elsewhere">Markdown / tables</button>';
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
//
// Plain text and HTML are rendered by the server (core/export_render.py): the
// plain-text layout used to be built here, so the terminal had no equivalent
// and every code change came out JSON-escaped on a single line.
function _exportText(data, fmt) {
  if (!data || data.error) return null;
  if (data.content != null) return data.content;
  return JSON.stringify(data, null, 2);
}

// The /api/bulk-export format for a menu entry: 'plain' is the server's 'text'.
function _bulkFormat(fmt) { return fmt === 'plain' ? 'text' : fmt; }

async function sidebarExportFmt(fmt) {
  owlSpeak('export');
  const ids = [...selectedIds];
  const data = await postApi('/api/bulk-export', {ids, format: _bulkFormat(fmt)});
  const text = _exportText(data, fmt);
  if (text === null) {
    owlSay('Export failed' + (data && data.error ? ': ' + data.error : '.'));
    return;
  }
  const ext = {json:'.json', markdown:'.md', csv:'.csv', tsv:'.tsv', plain:'.txt', html:'.html'};
  const filename = 'exptrack_export_' + ids.length + '_experiments' + (ext[fmt] || '.txt');
  const mime = fmt === 'json' ? 'application/json' : fmt === 'html' ? 'text/html' : 'text/plain';
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

async function sidebarCopyFmt(fmt) {
  const ids = [...selectedIds];
  const data = await postApi('/api/bulk-export', {ids, format: _bulkFormat(fmt), patch: false});
  const text = _exportText(data, fmt);
  if (text === null) {
    owlSay('Copy failed' + (data && data.error ? ': ' + data.error : '.'));
    return;
  }
  document.querySelectorAll('.export-dropdown-menu').forEach(d => d.style.display = 'none');
  // Markdown carries its HTML rendering, so a paste into OneNote is tables.
  await copyRich(text, (data && data.html) || '',
                 ids.length + ' experiment(s) as ' + (fmt === 'plain' ? 'plain text' : fmt));
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

// `opts.includeFailed` forces failed runs through regardless of the list's own
// filter. The parameter matrix needs that: it carries its own include-failed
// control, and the list's filter would otherwise strip those runs out before
// the matrix ever saw them — leaving its own control visibly on and doing
// nothing, and silently under-reporting the search. The "Show failed (N)"
// button counts with this flag set, which is how it knows what it is
// withholding.
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
    // Failed runs are listed by default — "it broke" is a result of the change
    // you just made, and hiding them let the table disagree with the FAILED
    // stat tile counting them above it. The "Hide failed" button is how the
    // user opts out, and it then reads "Show failed (N)" so the count is never
    // silent. When the user has explicitly filtered to the "Failed" status
    // chip, that wins — else the sidebar/table would show nothing.
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
