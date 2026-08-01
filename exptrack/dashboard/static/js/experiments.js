

// The four run-status cards answer "what happened"; the other seven are
// reference numbers nobody reads on every visit, and at full height all eleven
// pushed the experiment table itself below the fold. Keep the secondary row
// collapsed by default, remembering whichever the user prefers.
let _moreStatsOpen = _storageGet('exptrack-stats-more') === 'true';

function toggleMoreStats() {
  _moreStatsOpen = !_moreStatsOpen;
  _storageSet('exptrack-stats-more', _moreStatsOpen ? 'true' : 'false');
  const row = document.getElementById('stats-additional');
  const btn = document.getElementById('stats-more-btn');
  if (row) row.style.display = _moreStatsOpen ? '' : 'none';
  if (btn) btn.innerHTML = (_moreStatsOpen ? '&#9662;' : '&#9656;') + ' More stats';
}

async function loadStats() {
  const s = await api('/api/stats');
  // api() reports the failure via the error banner and returns null; don't
  // paint stale/undefined numbers over the top of it.
  if (!s) return;
  // Drives the "showing N of M" truncation notice.
  expTotal = s.total || 0;
  renderTruncNotice();
  const statsEl = document.getElementById('stats');
  if (statsEl) {
    const timeAgo = s.most_recent ? fmtTimeAgo(s.most_recent) : '--';
    statsEl.innerHTML = `
      <div class="stats-row runs">
        <div class="stat"><div class="num">${s.total}</div><div class="label">Total Runs</div><div class="stat-hint">All experiments tracked in this project</div></div>
        <div class="stat"><div class="num status-done">${s.done}</div><div class="label">Done</div><div class="stat-hint">Completed successfully</div></div>
        <div class="stat"><div class="num status-failed">${s.failed}</div><div class="label">Failed</div><div class="stat-hint">Ended with an error</div></div>
        <div class="stat"><div class="num status-running">${s.running}</div><div class="label">Running</div><div class="stat-hint">Currently in progress</div></div>
      </div>
      <button class="stats-more-btn" id="stats-more-btn" onclick="toggleMoreStats()"
              title="Show or hide the secondary stats">${_moreStatsOpen ? '&#9662;' : '&#9656;'} More stats</button>
      <div class="stats-row additional" id="stats-additional"${_moreStatsOpen ? '' : ' style="display:none"'}>
        <div class="stat"><div class="num">${s.success_rate}%</div><div class="label">Success Rate</div><div class="stat-hint">done / total</div></div>
        <div class="stat"><div class="num">${fmtDur(s.avg_duration_s)}</div><div class="label">Avg Duration</div><div class="stat-hint">Mean run time (completed only)</div></div>
        <div class="stat"><div class="num">${timeAgo}</div><div class="label">Latest Run</div><div class="stat-hint">Time since most recent experiment</div></div>
        <div class="stat"><div class="num">${fmtDur(s.longest_run_s)}</div><div class="label">Longest Run</div><div class="stat-hint">Maximum run duration</div></div>
        <div class="stat"><div class="num">${s.unique_tags}</div><div class="label">Tags</div><div class="stat-hint">Unique tags across all experiments</div></div>
        <div class="stat"><div class="num">${s.total_artifacts}</div><div class="label">Artifacts</div><div class="stat-hint">Total artifacts saved</div></div>
        <div class="stat"><div class="num">${s.unique_branches}</div><div class="label">Branches</div><div class="stat-hint">Unique git branches used</div></div>
      </div>
    `;
    // Show diff storage alert when total exceeds 512KB
    if (s.diff_total_bytes > 512 * 1024) {
      const kb = (s.diff_total_bytes / 1024).toFixed(0);
      const maxKb = s.max_diff_kb || 256;
      statsEl.innerHTML += '<div style="margin:8px 0;padding:8px 12px;background:rgba(232,167,53,0.12);border:1px solid rgba(232,167,53,0.3);border-radius:6px;font-size:13px;color:var(--yellow,#e8a735)">'
        + '<strong>Git diff storage:</strong> ' + kb + ' KB across ' + s.diff_count + ' experiment(s). '
        + 'Max per-run limit: ' + maxKb + ' KB (config: max_git_diff_kb). '
        + '<button style="margin-left:8px;font-size:12px;cursor:pointer;padding:2px 8px;border-radius:3px;border:1px solid rgba(232,167,53,0.4);background:transparent;color:inherit" '
        + 'onclick="bulkCompactAll()">Compact All Done</button>'
        + '</div>';
    }
  }
  renderStatusChips();
}

async function bulkCompactAll() {
  const doneIds = allExperiments.filter(e => e.status === 'done').map(e => e.id);
  if (!doneIds.length) { alert('No done experiments to compact.'); return; }
  const preview = await postApi('/api/bulk-compact', {ids: doneIds, mode: 'deep', dry_run: true});
  if (preview.error) { alert('Error: ' + preview.error); return; }
  if (!preview.will_remove || !preview.will_remove.length) {
    alert('Nothing to compact \u2014 all done experiments are already compacted.');
    return;
  }
  const msg = 'Compact all ' + doneIds.length + ' done experiments?\n\nWill remove:\n'
    + preview.will_remove.map(function(s) { return '  \u2022 ' + s; }).join('\n')
    + '\n\nTotal: ~' + preview.total_fmt
    + '\n\nTip: Run "exptrack compact --export DIR" from the CLI to save diffs first.'
    + '\n\nThis cannot be undone.';
  if (!confirm(msg)) return;
  const d = await postApi('/api/bulk-compact', {ids: doneIds, mode: 'deep'});
  if (d.error) { alert('Compact error: ' + d.error); return; }
  if (d.ok && d.freed > 0) {
    owlSay('Compacted ' + d.compacted + ' experiment(s), freed ~' + fmtFreed(d.freed), 'owl-bounce');
  } else {
    alert('Nothing to compact \u2014 already fully compacted.');
  }
  await loadStats();
  await loadExperiments();
  if (currentDetailId) await refreshDetail(currentDetailId);
}

function _expListUrl(offset) {
  let url = '/api/experiments?limit=' + EXP_PAGE_SIZE + '&offset=' + offset;
  if (currentFilter) url += '&status=' + encodeURIComponent(currentFilter);
  return url;
}

// Shared re-render after a page load (main table + sidebar + auto-named count,
// plus the highlight palette when highlight mode is on).
function _renderExpViews() {
  if (highlightMode) { buildHighlightColors(); renderHighlightLegend(); }
  renderExperiments();
  renderExpList();
  updateAutoNamedCount();
  updateFailedCount();
  updateMetricSortOptions();
  renderTruncNotice();
}

// Filtering, search and metric-sort run over the rows fetched so far. When some
// runs haven't been fetched, say so plainly — an unqualified "best run" answer
// drawn from a partial set is the one failure mode of this table that looks
// exactly like a correct answer.
function renderTruncNotice() {
  const el = document.getElementById('trunc-notice');
  if (!el) return;
  if (!expHasMore) { el.style.display = 'none'; el.innerHTML = ''; return; }
  const of = expTotal > expPageLoaded ? ' of ' + expTotal.toLocaleString() : '';
  el.innerHTML = '<span><strong>Showing the ' + expPageLoaded.toLocaleString()
    + ' most recent runs' + of + '.</strong> '
    + 'Search, filters and metric sort only cover these — load the rest to '
    + 'search or rank the whole project.</span>'
    + '<button class="action-btn" onclick="loadAllExperiments()">Load all runs</button>';
  el.style.display = 'flex';
}

// Page through the remainder in sequence (each request needs the previous
// offset, so these can't be fired concurrently).
async function loadAllExperiments() {
  const btn = document.querySelector('#trunc-notice button');
  if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
  let guard = 0;
  while (expHasMore && guard++ < 100) await loadMoreExperiments();
}

async function loadExperiments() {
  // Reload the first page (used on boot and after mutations). Previously this
  // silently capped at the server default of 50 rows with no way to see older
  // runs; now it fetches a full page and exposes "Load more" for the rest.
  const page = await api(_expListUrl(0));
  // A failed/garbled response must not wipe the list we already have — the
  // error banner is already up, so leave the last good data on screen.
  if (!Array.isArray(page)) return;
  allExperiments = page;
  // The Compare pickers cache their own copy; a mutation that reloads the list
  // must invalidate it or Compare keeps offering a stale set.
  _cmpExps = [];
  expPageLoaded = page.length;
  expHasMore = page.length >= EXP_PAGE_SIZE;
  _renderExpViews();
  renderHiddenPanel();
}

async function loadMoreExperiments() {
  if (!expHasMore) return;
  const page = await api(_expListUrl(expPageLoaded));
  if (!Array.isArray(page)) return;
  // Append, de-duping by id in case a concurrent insert shifted the window.
  const seen = new Set(allExperiments.map(e => e.id));
  for (const e of page) { if (!seen.has(e.id)) allExperiments.push(e); }
  expPageLoaded += page.length;
  expHasMore = page.length >= EXP_PAGE_SIZE;
  _renderExpViews();
}

function onRowClick(id) {
  if (clickTimer) clearTimeout(clickTimer);
  clickTimer = setTimeout(() => { clickTimer = null; showDetail(id); }, 250);
}

function cancelRowClick() {
  if (clickTimer) { clearTimeout(clickTimer); clickTimer = null; }
}

function miniSpark(values) {
  if (!values || values.length < 2) return '';
  const w = 40, h = 14;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((v, i) =>
    (i * w / (values.length - 1)).toFixed(1) + ',' + (h - (v - min) / range * h).toFixed(1)
  ).join(' ');
  return '<svg width="'+w+'" height="'+h+'" style="vertical-align:middle;margin-left:4px"><polyline points="'+points+'" fill="none" stroke="var(--blue)" stroke-width="1.2"/></svg>';
}

function renderExpRow(e) {
  const isSelected = selectedIds.has(e.id);
  const isPinned = pinnedIds.has(e.id);
  const hlStudy = getHighlightStudy(e);
  const rowCls = (isSelected ? 'selected-row' : '') + (isPinned ? ' pinned-row' : '') + (hlStudy ? ' highlighted-row' : '');
  const rowStyle = hlStudy ? ' style="background:' + hlStudy.bg + '"' : '';
  const hlBorder = hlStudy ? ' style="border-left:3px solid ' + hlStudy.border + '"' : '';
  // Editable cells open their editor on DOUBLE-click; a single click falls
  // through to the row handler and opens the run. Wiring the editor to a single
  // click (as this used to) meant a click anywhere in the Tags/Studies/Stage/
  // Notes columns silently swallowed "open this run" and popped up an editor
  // the user never asked for — with five of ~10 columns editable, most of the
  // row was a trap. The hover pencil stays a one-click affordance for anyone
  // who does want to edit, so nothing gets slower to reach.
  const editArgs = "'" + escJs(e.id) + "',";
  // `titled` is false where the cell already carries its own title (name, notes).
  const editOn = (fn, titled = true) => ' ondblclick="event.stopPropagation();cancelRowClick();'
    + fn + '(' + editArgs + 'this)"' + (titled ? ' title="Double-click to edit"' : '');
  const editIcon = fn => '<span class="edit-icon" title="Edit"'
    + ' onclick="event.stopPropagation();cancelRowClick();'
    + fn + '(' + editArgs + "this.closest('.editable-cell'))\">&#9998;</span>";

  // Pre-compute cell content for all possible columns
  const cells = {
    pin: '<td' + hlBorder + ' onclick="event.stopPropagation()"><button class="pin-btn' + (isPinned?' pinned':'') + '" onclick="togglePin(\'' + e.id + '\')" title="' + (isPinned?'Unpin':'Pin') + '">' + (isPinned?'\u2605':'\u2606') + '</button></td>',
    cb: '<td onclick="event.stopPropagation()"><label style="display:flex;align-items:center;justify-content:center;cursor:pointer;padding:4px"><input type="checkbox" ' + (isSelected?'checked':'') + ' onclick="toggleSelection(\'' + e.id + '\')" title="Select" style="cursor:pointer"></label></td>',
    id: '<td class="truncate-cell">' + e.id.slice(0,6) + '</td>',
    // Middle-ellipsis, not head-truncation: an auto name's distinguishing part
    // (`…__lr0.01__2aac1081`) is its tail, so cutting the tail made every row
    // in a rerun burst read identically.
    name: '<td class="truncate-cell">' + (e.name_is_auto ? '<span class="auto-name-badge" title="Auto-generated name — double-click to rename">auto</span>' : '') + '<span class="editable-cell" data-rename-slot="' + e.id + '" title="' + esc(e.name) + '"' + editOn('startInlineRename', false) + '>' + esc(midEllipsis(e.name, nameCellMaxChars(e.name_is_auto))) + editIcon('startInlineRename') + '</span></td>',
    status: '<td class="truncate-cell status-' + e.status + '">' + e.status + '</td>',
    tags: '<td class="tags-cell wrap-cell editable-cell"' + editOn('startInlineTag') + '>' + ((e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('') || '<span style="color:var(--muted)">--</span>') + editIcon('startInlineTag') + '</td>',
    studies: '<td class="tags-cell wrap-cell editable-cell"' + editOn('startInlineStudy') + '>' + ((e.studies||[]).map(g=>'<span class="tag" style="background:rgba(44,90,160,0.1);color:var(--blue)">'+esc(g)+'</span>').join('') || '<span style="color:var(--muted)">--</span>') + editIcon('startInlineStudy') + '</td>',
    stage: '<td class="wrap-cell stage-cell editable-cell"' + editOn('startInlineStage') + '>' + (e.stage != null ? '<span style="font-weight:600">' + esc(String(e.stage)) + '</span>' + (e.stage_name ? ' <span style="color:var(--muted)">\u00b7</span> <span style="color:var(--muted)">' + esc(e.stage_name) + '</span>' : '') : '<span style="color:var(--muted)">--</span>') + editIcon('startInlineStage') + '</td>',
    notes: '<td class="truncate-cell notes-cell-expanded editable-cell" title="' + esc(e.notes||'') + '"' + editOn('startInlineNote', false) + '>' + (e.notes ? esc(e.notes.split('\n')[0].slice(0,60)) : '<span style="color:var(--muted)">--</span>') + editIcon('startInlineNote') + '</td>',
    metrics: (function() {
      const parts = [];
      for (const [k, m] of Object.entries(e.metrics || {}).slice(0, 3)) {
        const v = typeof m === 'object' ? m.value : m;
        const src = typeof m === 'object' ? m.source : 'auto';
        const color = src === 'manual' ? 'var(--tl-metric)' : src === 'pipeline' ? 'var(--green)' : 'var(--blue)';
        parts.push('<span style="color:' + color + '" title="' + esc(k) + ' (' + src + ')">' + esc(abbrevMetric(k).split('/').pop()) + '</span>=' + (typeof v === 'number' ? v.toFixed(3) : esc(String(v))) + miniSpark((e.sparklines||{})[k]));
      }
      return '<td class="truncate-cell" style="font-size:13px">' + (parts.join(', ') || '<span style="color:var(--muted)">--</span>') + '</td>';
    })(),
    changes: (function() {
      const codeParams = Object.keys(e.params || {}).filter(k => k.startsWith('_code_change/') || k === '_code_changes');
      if (!codeParams.length) return '<td class="truncate-cell">--</td>';
      let added = 0, removed = 0;
      for (const k of codeParams) { const v = String(e.params[k] || ''); for (const p of v.split('; ')) { if (p.trim().startsWith('+')) added++; else if (p.trim().startsWith('-')) removed++; } }
      let s = '<span class="code-stat">' + codeParams.length + ' file' + (codeParams.length>1?'s':'');
      if (added || removed) s += ' <span class="lines-added">+' + added + '</span> <span class="lines-removed">-' + removed + '</span>';
      return '<td class="truncate-cell">' + s + '</span></td>';
    })(),
    started: '<td class="truncate-cell">' + fmtDt(e.created_at) + '</td>',
  };

  let tds = '';
  for (const colId of visibleCols) {
    if (cells[colId] !== undefined) { tds += cells[colId]; continue; }
    // Param column (`param:<key>`): render the value straight from the run's
    // captured params, so a sweep's varying hyperparameters are visible in the
    // list instead of only inside each run's detail view.
    if (isParamCol(colId)) tds += _paramCellHtml(e, paramColKey(colId));
  }
  return '<tr class="' + rowCls + '"' + rowStyle + ' onclick="onRowClick(\'' + e.id + '\')">' + tds + '</tr>';
}

// A param value as a table cell. Objects/arrays are JSON-stringified; the full
// value is always in the title so a truncated cell stays inspectable.
function _paramCellHtml(e, key) {
  const v = (e.params || {})[key];
  if (v === undefined || v === null) {
    return '<td class="truncate-cell param-cell"><span style="color:var(--muted)">--</span></td>';
  }
  const text = (typeof v === 'object') ? JSON.stringify(v) : String(v);
  return '<td class="truncate-cell param-cell" title="' + esc(key) + ' = ' + esc(text) + '">'
    + esc(text.length > 24 ? text.slice(0, 24) + '…' : text) + '</td>';
}

function _emptyStateHtml() {
  const total = (allExperiments || []).length;
  if (!total) {
    return '<div class="empty-state">' +
      '<div class="empty-state-icon">🦉</div>' +
      '<div class="empty-state-title">No experiments yet</div>' +
      '<div class="empty-state-msg">Run a script with <code>exptrack run train.py</code>, ' +
      'or start one from a notebook, to see it here.</div></div>';
  }
  const hasFilters = !!(currentFilter || searchQuery || tagFilter || studyFilter ||
    autoNamedOnly || (dateRange && dateRange !== 'all' && dateRange !== ''));
  // Failed runs are hidden by a toggle, not by any of the filter controls — so
  // when every loaded run failed, "no match" plus a Clear-filters button that
  // changes nothing is a dead end. Name the toggle that's actually hiding them.
  const failedHidden = (allExperiments || []).filter(e => e.status === 'failed').length;
  if (!showFailed && currentFilter !== 'failed' && failedHidden === total) {
    return '<div class="empty-state">' +
      '<div class="empty-state-icon">✕</div>' +
      '<div class="empty-state-title">Every run here failed</div>' +
      '<div class="empty-state-msg">' + total + ' failed run' + (total > 1 ? 's are' : ' is') +
      ' hidden by the <strong>Show failed</strong> toggle.' +
      ' <button class="action-btn" onclick="setShowFailed(true)">Show failed runs</button>' +
      (hasFilters ? ' <button class="action-btn" onclick="clearAllFilters()">Clear filters</button>' : '') +
      '</div></div>';
  }
  return '<div class="empty-state">' +
    '<div class="empty-state-icon">🔍</div>' +
    '<div class="empty-state-title">No experiments match your filters</div>' +
    '<div class="empty-state-msg">' + total + ' run' + (total > 1 ? 's' : '') +
    ' hidden by the current filters' +
    (failedHidden ? ' (including ' + failedHidden + ' failed run' + (failedHidden > 1 ? 's' : '') +
      ' behind the <strong>Show failed</strong> toggle)' : '') + '.' +
    (failedHidden ? ' <button class="action-btn" onclick="setShowFailed(true)">Show failed</button>' : '') +
    (hasFilters ? ' <button class="action-btn" onclick="clearAllFilters()">Clear filters</button>' : '') +
    '</div></div>';
}

function clearAllFilters() {
  currentFilter = ''; searchQuery = ''; tagFilter = ''; studyFilter = '';
  autoNamedOnly = false; dateRange = '';
  localStorage.setItem('exptrack-auto-named-only', 'false');
  localStorage.setItem('exptrack-date-range', '');
  const si = document.getElementById('search-input'); if (si) si.value = '';
  if (typeof syncFilterControls === 'function') syncFilterControls();
  renderStatusChips();
  loadExperiments();
}

function renderExperiments() {
  // Scope the preserve to the table body: loadExperiments() renders the table and
  // the sidebar back to back (_renderExpViews), and an unscoped preserve in the
  // second render would detach the input the first had just re-mounted.
  const restoreRename = _preserveActiveRename('exp-body');
  const exps = getFilteredExperiments();
  const tbody = document.getElementById('exp-body');
  if (!tbody) { restoreRename(); return; }
  renderFilterBar();
  // Re-run the header so empty-column collapsing tracks the rows now in view
  // (a filter change can empty or re-populate Tags/Studies/Stage/Notes).
  renderTableHeader(exps);
  updateSortHeaders();
  renderTableActionsBar();

  if (!exps.length) {
    tbody.innerHTML = '<tr class="exp-empty-row"><td colspan="' + visibleCols.length + '">' +
      _emptyStateHtml() + '</td></tr>';
    restoreRename();
    return;
  }

  const moreRow = expHasMore
    ? '<tr class="exp-loadmore-row"><td colspan="' + visibleCols.length + '">' +
      '<button class="btn-secondary" onclick="loadMoreExperiments()">Load more experiments</button>' +
      '</td></tr>'
    : '';

  if (!groupBy) {
    tbody.innerHTML = exps.map(renderExpRow).join('') + moreRow;
    restoreRename();
    return;
  }

  // Group experiments
  const NO_STUDY = '__no_study__';
  const groups = new Map();
  for (const e of exps) {
    let key = '';
    if (groupBy === 'git_commit') key = e.git_commit ? e.git_commit.slice(0, 7) : 'no commit';
    else if (groupBy === 'git_branch') key = e.git_branch || 'no branch';
    else if (groupBy === 'script') key = e.script ? e.script.split('/').pop() : 'no script';
    else if (groupBy === 'status') key = e.status || 'unknown';
    else if (groupBy === 'day') key = dayKeyOf(e.created_at) || 'unknown';
    else if (groupBy === 'study') key = (e.studies && e.studies.length) ? e.studies[0] : NO_STUDY;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(e);
  }

  let html = '';
  for (const [key, items] of groups) {
    const isCollapsed = collapsedGroups.has(key);
    let groupLabel = key;
    if (groupBy === 'git_commit' && items[0].git_branch) {
      groupLabel = key + ' <span class="group-meta">' + esc(items[0].git_branch) + '</span>';
    } else if (groupBy === 'day') {
      groupLabel = esc(dayLabelOf(items[0].created_at));
    } else if (groupBy === 'study' && key === NO_STUDY) {
      groupLabel = '<span style="color:var(--muted);font-style:italic">(no study)</span>';
    } else {
      groupLabel = esc(key);
    }
    html += '<tr class="group-header" onclick="toggleGroup(\'' + escJsAttr(key) + '\')"><td colspan="' + visibleCols.length + '">';
    html += '<span class="group-toggle">' + (isCollapsed ? '\u25B6' : '\u25BC') + '</span> ';
    html += '<span class="group-label">' + groupLabel + '</span>';
    html += '<span class="group-meta"> \u2014 ' + items.length + ' run' + (items.length > 1 ? 's' : '') + '</span>';
    html += '</td></tr>';
    if (!isCollapsed) {
      html += items.map(renderExpRow).join('');
    }
  }
  tbody.innerHTML = html + moreRow;
  restoreRename();
}
