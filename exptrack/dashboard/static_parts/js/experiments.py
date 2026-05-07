"""Experiment list filtering, grouping, and rendering."""

JS_EXPERIMENTS = r"""

async function loadStats() {
  const s = await api('/api/stats');
  const statsEl = document.getElementById('stats');
  if (statsEl) {
    const timeAgo = s.most_recent ? fmtTimeAgo(s.most_recent) : '--';
    statsEl.innerHTML = `
      <div class="stats-label">Runs</div>
      <div class="stats-row runs">
        <div class="stat"><div class="num">${s.total}</div><div class="label">Total Runs</div><div class="stat-hint">All experiments tracked in this project</div></div>
        <div class="stat"><div class="num status-done">${s.done}</div><div class="label">Done</div><div class="stat-hint">Completed successfully</div></div>
        <div class="stat"><div class="num status-failed">${s.failed}</div><div class="label">Failed</div><div class="stat-hint">Ended with an error</div></div>
        <div class="stat"><div class="num status-running">${s.running}</div><div class="label">Running</div><div class="stat-hint">Currently in progress</div></div>
      </div>
      <div class="stats-label">Additional Stats</div>
      <div class="stats-row additional">
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

async function loadExperiments() {
  const url = currentFilter ? '/api/experiments?status=' + currentFilter : '/api/experiments';
  allExperiments = await api(url);
  if (highlightMode) { buildHighlightColors(); renderHighlightLegend(); }
  renderExperiments();
  renderExpList();
  renderHiddenPanel();
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
  const editIcon = '<span class="edit-icon" title="Click to edit">&#9998;</span>';

  // Pre-compute cell content for all possible columns
  const cells = {
    pin: '<td' + hlBorder + ' onclick="event.stopPropagation()"><button class="pin-btn' + (isPinned?' pinned':'') + '" onclick="togglePin(\'' + e.id + '\')" title="' + (isPinned?'Unpin':'Pin') + '">' + (isPinned?'\u2605':'\u2606') + '</button></td>',
    cb: '<td onclick="event.stopPropagation()"><label style="display:flex;align-items:center;justify-content:center;cursor:pointer;padding:4px"><input type="checkbox" ' + (isSelected?'checked':'') + ' onclick="toggleSelection(\'' + e.id + '\')" title="Select" style="cursor:pointer"></label></td>',
    id: '<td class="truncate-cell">' + e.id.slice(0,6) + '</td>',
    name: '<td class="truncate-cell"><span class="editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineRename(\'' + e.id + '\',this)">' + esc(e.name.slice(0,45)) + editIcon + '</span></td>',
    status: '<td class="truncate-cell status-' + e.status + '">' + e.status + '</td>',
    tags: '<td class="tags-cell wrap-cell editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineTag(\'' + e.id + '\',this)">' + ((e.tags||[]).map(t=>'<span class="tag">#'+esc(t)+'</span>').join('') || '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
    studies: '<td class="tags-cell wrap-cell editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineStudy(\'' + e.id + '\',this)">' + ((e.studies||[]).map(g=>'<span class="tag" style="background:rgba(44,90,160,0.1);color:var(--blue)">'+esc(g)+'</span>').join('') || '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
    stage: '<td class="wrap-cell stage-cell editable-cell" onclick="event.stopPropagation();cancelRowClick();startInlineStage(\'' + e.id + '\',this)">' + (e.stage != null ? '<span style="font-weight:600">' + esc(String(e.stage)) + '</span>' + (e.stage_name ? ' <span style="color:var(--muted)">\u00b7</span> <span style="color:var(--muted)">' + esc(e.stage_name) + '</span>' : '') : '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
    notes: '<td class="truncate-cell notes-cell-expanded editable-cell" title="' + esc(e.notes||'') + '" onclick="event.stopPropagation();cancelRowClick();startInlineNote(\'' + e.id + '\',this)">' + (e.notes ? esc(e.notes.split('\n')[0].slice(0,60)) : '<span style="color:var(--muted)">--</span>') + editIcon + '</td>',
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
  for (const colId of visibleCols) { tds += cells[colId] || ''; }
  return '<tr class="' + rowCls + '"' + rowStyle + ' onclick="onRowClick(\'' + e.id + '\')">' + tds + '</tr>';
}

function renderExperiments() {
  const exps = getFilteredExperiments();
  const tbody = document.getElementById('exp-body');
  if (!tbody) return;
  renderFilterBar();
  updateSortHeaders();
  renderTableActionsBar();

  if (!groupBy) {
    tbody.innerHTML = exps.map(renderExpRow).join('');
    return;
  }

  // Group experiments
  const NO_STUDY = '__no_study__';
  const groups = new Map();
  for (const e of exps) {
    let key = '';
    if (groupBy === 'git_commit') key = e.git_commit ? e.git_commit.slice(0, 7) : 'no commit';
    else if (groupBy === 'git_branch') key = e.git_branch || 'no branch';
    else if (groupBy === 'status') key = e.status || 'unknown';
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
    } else if (groupBy === 'study' && key === NO_STUDY) {
      groupLabel = '<span style="color:var(--muted);font-style:italic">(no study)</span>';
    } else {
      groupLabel = esc(key);
    }
    html += '<tr class="group-header" onclick="toggleGroup(\'' + esc(key) + '\')"><td colspan="' + visibleCols.length + '">';
    html += '<span class="group-toggle">' + (isCollapsed ? '\u25B6' : '\u25BC') + '</span> ';
    html += '<span class="group-label">' + groupLabel + '</span>';
    html += '<span class="group-meta"> \u2014 ' + items.length + ' run' + (items.length > 1 ? 's' : '') + '</span>';
    html += '</td></tr>';
    if (!isCollapsed) {
      html += items.map(renderExpRow).join('');
    }
  }
  tbody.innerHTML = html;
}
"""

# Inline editing: rename, tags, notes
