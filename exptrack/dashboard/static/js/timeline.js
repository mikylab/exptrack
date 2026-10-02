

// ── Timeline visualization ───────────────────────────────────────────────────

let timelineFilter = '';

// Mirror of cell_lineage.is_magic_only — true when a cell is only IPython
// magics / shell escapes / comments / blanks (a command, not editable code).
// api() returns null when a request fails (it has already raised the error
// bar), so every `data.error` read must be guarded — otherwise it throws, the
// render never runs, and the tab sits at "Loading…" forever. That blank-panel
// outcome is exactly what the visible-failures rule exists to prevent.
function _apiFailedHtml(what) {
  return '<p style="color:var(--muted)">Could not load ' + esc(what) +
         ' \u2014 the request failed. See the error bar above for details.</p>';
}

function _isMagicOnlyCell(src) {
  if (!src) return false;
  let hasMagic = false;
  for (const line of String(src).split('\n')) {
    const s = line.trim();
    if (!s || s.startsWith('#')) continue;
    if (s.startsWith('%') || s.startsWith('!')) { hasMagic = true; continue; }
    return false;
  }
  return hasMagic;
}

// ── Run source (Code › Source) ────────────────────────────────────────────────
// The code a run actually ran, read back from its snapshot (scripts) or cell
// records (notebooks). This is independent of the file on disk, so it still
// answers after the script has been edited or was never committed — which is
// exactly when it is hardest to get any other way.
// Fetched when the Code tab's Source view opens, not with the timeline: a
// script snapshot can be hundreds of KB.

// The last source rendered, so a live run's 5 s rebuild (which empties the
// pane) repaints it without refetching a snapshot that cannot change.
let _sourceHtmlFor = {id: '', html: ''};

async function loadRunSource(expId) {
  const box = document.getElementById('tl-source-body');
  if (!box) return;
  if (_sourceHtmlFor.id === expId) { box.innerHTML = _sourceHtmlFor.html; return; }
  const data = await api('/api/run-source/' + encodeURIComponent(expId));
  // api() returns null on failure (it has already raised the error bar); a bare
  // `.error` read would throw and leave the fold stuck on "Loading…".
  if (!data || data.error) {                     // not cached: a retry re-fetches
    box.innerHTML = _apiFailedHtml('source');
    return;
  }

  if (!data.kind || !data.files.length) {
    _sourceHtmlFor = {id: expId, html: ''};
    box.innerHTML = _sourceHtmlFor.html =
      '<p style="color:var(--muted)">This run didn&#39;t capture its code.</p>' +
      '<p style="color:var(--muted);font-size:var(--text-xs)">Scripts capture a ' +
      'full snapshot automatically; notebook runs capture executed cells. A run ' +
      'recorded before source capture, or a label-only pipeline run, has neither.</p>';
    return;
  }

  const kindNote = data.kind === 'script'
    ? 'Full script source, captured when the run started.'
    : data.files.length + ' executed cell(s), in execution order.';
  let html = '<div class="source-tab-note">' + esc(kindNote) + '</div>';

  for (const f of data.files) {
    const lines = (f.content || '').split('\n');
    const code = _numberedSourceHtml(f.content);
    html += '<details class="source-file" open>' +
      '<summary><span class="sf-label">' + esc(f.label) + '</span>' +
      '<span class="sf-lines">' + lines.length + ' lines</span>' +
      '<span class="copy-btn" data-raw="' + esc(f.content || '') +
      '" onclick="event.preventDefault();event.stopPropagation();copySessionText(this)">⧉ Copy</span>' +
      '</summary><pre class="cell-code">' + code + '</pre></details>';
  }
  _sourceHtmlFor = {id: expId, html: html};
  box.innerHTML = html;
}

async function loadTimeline(expId, filter) {
  if (filter !== undefined) timelineFilter = filter;
  // 'lineage' is a client-side filter — fetch all cell_exec events then filter
  const isLineageFilter = timelineFilter === 'lineage';
  const serverFilter = isLineageFilter ? 'cell_exec' : timelineFilter;
  const url = serverFilter
    ? '/api/timeline/' + expId + '?type=' + serverFilter
    : '/api/timeline/' + expId;
  let events = await api(url);
  const container = document.getElementById('detail-tab-timeline');
  // api() returns null on a failed request (already reported in the error bar) —
  // reading through it threw mid-render and left the tab blank with no message.
  if (!Array.isArray(events)) {
    if (container) container.innerHTML = _apiFailedHtml('the timeline');
    return;
  }
  if (isLineageFilter) {
    events = events.filter(ev => ev.parent_hash);
  }

  // Single source of truth for each event type's icon, plain-language label,
  // color, and a one-line meaning (used by the filter bar, the legend, the per-event
  // type chip, and hover tooltips) so the timeline is self-explanatory.
  const evMeta = {
    cell_exec:     {icon:'&#9654;', label:'Code run',      meaning:'a code cell ran',                         color:'var(--tl-cell)'},
    var_set:       {icon:'=',       label:'Variable set',  meaning:'a tracked variable was set or changed',   color:'var(--tl-var)'},
    artifact:      {icon:'&#8595;', label:'Output saved',  meaning:'an output file was saved',                color:'var(--tl-artifact)'},
    metric:        {icon:'#',       label:'Metric',        meaning:'a metric value was logged',               color:'var(--tl-metric)'},
    observational: {icon:'&#183;',  label:'Ran, no change',meaning:'a cell ran but changed no code or tracked variable', color:'var(--tl-obs)'},
    resume:        {icon:'&#8635;', label:'Resumed',       meaning:'the experiment was resumed',              color:'var(--accent)'},
    setup:         {icon:'&#128295;', label:'Setup / prep', meaning:'a %%setup prep cell ran (recorded but secondary)', color:'var(--tl-obs)'},
  };

  let html = '<div class="tl-filters">';
  const types = ['', 'cell_exec', 'var_set', 'artifact', 'observational', 'setup', 'resume', 'lineage'];
  const labels = ['All', 'Code run', 'Variables', 'Outputs', 'Ran, no change', 'Setup', 'Resumed', 'Edited cells'];
  types.forEach((t, i) => {
    html += '<button class="' + (timelineFilter===t?'active':'') + '" onclick="loadTimeline(\'' + expId + '\',\'' + t + '\')">' + labels[i] + '</button>';
  });
  html += '</div>';


  if (!events.length) {
    // A plain script run records no timeline events at all; its code is in
    // the Source view, so say where to look rather than ending on a blank.
    html += '<p style="color:var(--muted)">No timeline events recorded. The code this run ran is under <a href="#" onclick="switchDetailView(\'code\',\'source\',\'' + escJsAttr(expId) + '\');return false">Source</a>.</p>';
    container.innerHTML = html;
    return;
  }

  // Legend — what each icon/label means, always one glance away.
  const legendTypes = ['cell_exec', 'var_set', 'artifact', 'metric', 'observational'];
  html += '<div class="tl-legend"><span class="tl-legend-title">Key:</span>';
  for (const t of legendTypes) {
    const m = evMeta[t];
    html += '<span class="tl-legend-item" title="' + m.meaning + '">'
          + '<span class="tl-legend-icon" style="color:' + m.color + '">' + m.icon + '</span>'
          + m.label + ' <span class="tl-legend-meaning">— ' + m.meaning + '</span></span>';
  }
  html += '</div>';

  // Badge key — what the chips on a code-run row mean. Same recipe/colors as the
  // badges themselves so the meaning is one glance away.
  html += '<div class="tl-legend tl-legend-badges"><span class="tl-legend-title">Badges:</span>'
        + '<span class="tl-badge tl-badge-new" title="Brand-new code cell in this run">new</span>'
        + '<span class="tl-badge tl-badge-edited" title="Code changed from an earlier version (click an edited badge to view it)">edited</span>'
        + '<span class="tl-badge tl-badge-rerun" title="Ran again with no code change">rerun</span>'
        + '</div>';

  html += '<p style="color:var(--muted);font-size:12px;margin-bottom:8px">' + events.length + ' events. Click "view source" on cells to see full code.</p>';

  const varState = {};

  html += '<div class="timeline">';
  for (const ev of events) {
    const cls = 'tl-event tl-' + ev.event_type;
    const ts = fmtDt(ev.ts);
    const meta = evMeta[ev.event_type] || {icon:'?', label:ev.event_type, meaning:'', color:'var(--fg)'};
    const icon = meta.icon;
    const iconColor = meta.color;
    const typeLabel = '<span class="tl-type-label tl-type-' + ev.event_type + '" title="' + meta.meaning + '">' + meta.label + '</span>';
    // The left number is execution order (event #N in the run), NOT a line/cell
    // number — say so on hover and prefix with # so it reads as an index.
    const seqHtml = '<div class="tl-seq" title="Execution order — event #' + ev.seq + ' in this run">#' + ev.seq + '</div>';
    // Notebook cell position, when known (skips scripts / cell 0).
    const cellNumChip = ev.cell_pos ? '<span class="tl-cellpos" title="Notebook cell position">cell ' + ev.cell_pos + '</span>' : '';

    if (ev.event_type === 'cell_exec' || ev.event_type === 'observational') {
      const info = ev.value || {};
      const preview = (info.source_preview || '').split('\n')[0].slice(0, 80);
      // Magic-only cells (e.g. %exptrack checkpoint/branch) are commands, not
      // editable code. Older runs may have a bogus fuzzy-matched parent + diff
      // stored; suppress the edited/lineage badges and diff at render time so
      // they read as the command they are. (New captures already skip this.)
      const magicOnly = _isMagicOnlyCell(info.source_preview);
      // One status chip per row. "edited" doubles as the link to the earlier
      // version when there's a parent, so we don't need a separate lineage chip;
      // the cell's result is shown inline below, so no "result" chip either.
      let badges = '';
      if (info.code_is_new && !magicOnly) badges += '<span class="tl-badge tl-badge-new" title="Brand-new code cell in this run">new</span>';
      else if (info.code_changed && !magicOnly) {
        if (ev.parent_hash) badges += '<span class="tl-badge tl-badge-edited tl-badge-link" title="Code changed from an earlier version (' + ev.parent_hash.slice(0,6) + ') — click to view it" onclick="event.stopPropagation();viewCellSource(\'' + ev.parent_hash + '\',this.closest(\'.tl-body\').querySelector(\'.view-source-btn\') || this)">edited</span>';
        else badges += '<span class="tl-badge tl-badge-edited" title="Code changed from a previous run">edited</span>';
      }
      else if (info.is_rerun) badges += '<span class="tl-badge tl-badge-rerun" title="Ran again with no code change">rerun</span>';

      // Flag a print() with a hardcoded number (e.g. print("accuracy 98")) —
      // often a stale value the author meant to interpolate from a variable.
      if (!magicOnly && (info.source_preview || '').split('\n').some(_isStalePrintLine)) {
        badges += _stalePrintBadge();
      }

      // View source button - uses cell_hash to fetch from lineage
      const viewSrcBtn = ev.cell_hash ? ' <button class="view-source-btn" onclick="event.stopPropagation();viewCellSource(\'' + ev.cell_hash + '\',this)">view source</button>' : '';

      // Single human-readable cell label. Prefer the "cell N" position chip; fall
      // back to the stored key reformatted ("cell_1" → "cell 1") for scripts / runs
      // captured before cell_pos existed. The raw ev.key ("cell_1") is never shown
      // alongside the chip — that produced the duplicate "cell 1" + "cell_1".
      let cellLabelChip = cellNumChip;
      if (!cellLabelChip && ev.key) {
        cellLabelChip = '<span class="tl-cellpos" title="Cell">' + esc(String(ev.key).replace(/^cell_/, 'cell ')) + '</span>';
      }

      html += '<div class="' + cls + '">';
      html += seqHtml;
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + cellLabelChip + badges + viewSrcBtn;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      if (preview) html += '<div class="tl-code-preview">' + _highlightPy(preview) + '</div>';

      const sdiff = _normalizeSourceDiff(ev.source_diff);
      if (sdiff.length && !magicOnly) {
        let summaryHtml = '', rows = [];
        for (const d of sdiff.slice(0, 8)) {
          if (d.op === 'summary') summaryHtml += '<div class="tl-diff-summary">' + esc(d.line) + '</div>';
          else if (d.op === '+') rows.push({kind:'add', text: String(d.line).slice(0,200)});
          else if (d.op === '-') rows.push({kind:'del', text: String(d.line).slice(0,200)});
        }
        html += '<div class="tl-diff">' + summaryHtml + _renderDiffRows(rows);
        if (sdiff.length > 8) html += '<div style="color:var(--muted)">... ' + (sdiff.length - 8) + ' more lines</div>';
        html += '</div>';
      }

      // The cell's output (captured print() stdout + trailing-expression repr)
      // renders LAST so it always sits *below* the code — including when the
      // full source is expanded (viewCellSource inserts the source above it).
      if (info.output_preview) {
        html += '<div class="tl-cell-output"><div class="tl-out-label">Out</div>'
              + '<pre class="tl-out-pre">' + esc(String(info.output_preview)) + '</pre></div>';
      }
      html += '</div></div>';

    } else if (ev.event_type === 'var_set') {
      varState[ev.key] = ev.value;
      let cleanVal = String(ev.value);
      if (cleanVal.startsWith(ev.key + ' = ')) {
        cleanVal = cleanVal.slice(ev.key.length + 3);
      }
      const valStr = cleanVal.slice(0, 60);
      let prevHtml = '';
      if (ev.prev_value !== null && ev.prev_value !== undefined) {
        let cleanPrev = String(ev.prev_value);
        if (cleanPrev.startsWith(ev.key + ' = ')) {
          cleanPrev = cleanPrev.slice(ev.key.length + 3);
        }
        prevHtml = ' <span class="tl-var-arrow">&larr;</span> <span style="color:var(--muted);text-decoration:line-through">' + esc(cleanPrev.slice(0,40)) + '</span>';
      }
      html += '<div class="' + cls + '">';
      html += seqHtml;
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-var)">' + esc(ev.key) + '</strong> = ' + esc(valStr) + prevHtml;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';

    } else if (ev.event_type === 'artifact') {
      html += '<div class="' + cls + '">';
      html += seqHtml;
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + artifactTypeBadge(String(ev.value||'')) + ' <strong>' + esc(ev.key||'') + '</strong> &rarr; ' + esc(String(ev.value||'').slice(0,60));
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      const ctxKeys = Object.keys(varState).filter(k => !k.startsWith('_'));
      if (ctxKeys.length) {
        const ctx = ctxKeys.slice(0, 6).map(k => k + '=' + String(varState[k]).slice(0,15)).join(', ');
        html += '<div class="tl-context">context: ' + esc(ctx) + '</div>';
      }
      html += '</div></div>';

    } else if (ev.event_type === 'metric') {
      html += '<div class="' + cls + '">';
      html += seqHtml;
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-metric)">' + esc(ev.key) + '</strong> = ' + ev.value;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';

    } else if (ev.event_type === 'setup') {
      // %%setup prep cell — recorded but secondary: the full source collapses
      // into a <details>, with its captured output below.
      const info = ev.value || {};
      const src = info.source || info.source_preview || '';
      const srcLines = src.split('\n');
      const numbered = srcLines.map((ln, k) =>
        '<span class="cl"><span class="ln">' + (k + 1) + '</span>' + _highlightPy(ln) + '</span>').join('');
      html += '<div class="' + cls + ' tl-setup">';
      html += seqHtml;
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '<details class="cell-block setup-cell"><summary>'
            + '<span class="cell-meta">' + srcLines.length + ' line'
            + (srcLines.length === 1 ? '' : 's') + ' of prep code</span></summary>'
            + '<pre class="cell-code">' + numbered + '</pre></details>';
      if (info.output_preview) {
        html += '<div class="tl-cell-output"><div class="tl-out-label">Out</div>'
              + '<pre class="tl-out-pre">' + esc(String(info.output_preview)) + '</pre></div>';
      }
      html += '</div></div>';
    }
  }
  html += '</div>';
  container.innerHTML = html;
}

// Hide/restore the inline timeline preview (first-line + short diff) for one
// event row. The expanded "view source" shows the full source/diff, so the short
// preview would just duplicate it — collapse it back when the source is hidden.
function _toggleTimelinePreview(body, hide) {
  if (!body) return;
  body.querySelectorAll('.tl-code-preview, .tl-diff').forEach(el => {
    el.style.display = hide ? 'none' : '';
  });
}

async function viewCellSource(cellHash, btnEl) {
  const body = btnEl.closest('.tl-body') || btnEl.parentElement;
  // Toggle: if source is already showing, hide it (and restore the inline preview)
  const existing = btnEl.parentElement.querySelector('.source-view');
  if (existing) {
    existing.remove();
    _toggleTimelinePreview(body, false);
    btnEl.textContent = 'view source';
    return;
  }
  btnEl.textContent = 'loading...';
  const data = await api('/api/cell-source/' + cellHash);
  btnEl.textContent = 'hide source';
  if (!data || data.error || !data.source) {
    // No cell_lineage row. For a *script* run there never was one — cell
    // lineage is a notebook concept, so a script's `cell_exec` event carries a
    // hash that nothing backs, and the old message announced "compacted" for a
    // run nothing had ever compacted. The script's real source lives
    // content-addressed in code_snapshots, which no compaction mode touches,
    // so ask for that before apologising.
    const snap = currentDetailId
      ? await api('/api/run-source/' + encodeURIComponent(currentDetailId))
      : null;
    const file = snap && !snap.error && (snap.files || [])[0];
    const div = document.createElement('div');
    if (file) {
      div.className = 'source-view';
      div.innerHTML =
        '<div style="margin-bottom:8px;color:var(--blue);font-size:11px;' +
          'text-transform:uppercase">Source from snapshot: ' + esc(file.label) +
        '</div>' + _numberedSourceHtml(file.content);
    } else {
      div.className = 'source-view';
      div.innerHTML = '<span style="color:var(--yellow)">No source stored for this cell.</span>'
        + '<br><span style="color:var(--muted);font-size:12px">Cell hash: ' + esc(cellHash) + '</span>'
        + '<br><span style="color:var(--muted);font-size:12px">Variable changes and lineage are still tracked in the timeline.</span>';
    }
    btnEl.parentElement.appendChild(div);
    return;
  }
  // When there's a parent (an edited cell), render current-vs-previous as a real
  // diff so the changed words are spotlighted (the same word-level highlighting as
  // the timeline preview, honoring the Settings toggle) — unchanged lines stay as
  // context so the full source is still visible. No parent ⇒ plain highlighted source.
  let diffRows = data.parent_source ? _lineDiffRows(data.parent_source, data.source) : null;
  let html;
  if (diffRows) {
    html = '<div class="source-view diff-view">'
      + '<div style="margin-bottom:8px;color:var(--blue);font-size:11px;text-transform:uppercase">Changes from previous version (hash: ' + cellHash + ' ← ' + data.parent_hash + ')</div>'
      + _renderDiffRows(diffRows, true)
      + '</div>';
  } else {
    html = '<div class="source-view">';
    html += '<div style="margin-bottom:8px;color:var(--blue);font-size:11px;text-transform:uppercase">Current cell source (hash: ' + cellHash + ')</div>';
    const lines = data.source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const stale = _isStalePrintLine(lines[i]);
      html += '<span class="line-num">' + (i+1) + '</span>'
        + (stale ? '<span class="stale-line">' : '') + _highlightPy(lines[i])
        + (stale ? ' <span class="stale-print-mark" title="' + STALE_PRINT_TITLE + '">⚠</span></span>' : '')
        + '\n';
    }
    // Parent present but too large to diff — fall back to showing it dimmed.
    if (data.parent_source) {
      html += '<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:8px;color:var(--muted);font-size:11px;text-transform:uppercase">Previous version (hash: ' + data.parent_hash + ')</div>';
      const plines = data.parent_source.split('\n');
      html += '<span style="opacity:0.55">';
      for (let i = 0; i < plines.length; i++) {
        html += '<span class="line-num">' + (i+1) + '</span>' + _highlightPy(plines[i]) + '\n';
      }
      html += '</span>';
    }
    html += '</div>';
  }
  // Keep the cell's "Out" panel at the very bottom: insert the expanded source
  // *before* it when present, so the result never floats above the code.
  const outEl = btnEl.parentElement.querySelector('.tl-cell-output');
  if (outEl) outEl.insertAdjacentHTML('beforebegin', html);
  else btnEl.parentElement.insertAdjacentHTML('beforeend', html);
  _toggleTimelinePreview(body, true);
}

// ── Scan-path suggestions ────────────────────────────────────────────────────
//
// Shared by the Images and Data Files tabs. Suggestions used to be shown only
// while *no* path had been saved, which hid them at exactly the point the user
// had proved they were useful and wanted a second one — so they stay visible,
// with anything already added filtered out server-side. Each chip carries the
// reason it was suggested ("a dataset this run read", "42 matching files"), so
// picking one is a decision rather than a guess.
// The server bounds a saved scan path's walk (a checkpoint-per-epoch tree is
// thousands of files, re-scanned on every request). Say so rather than letting
// a capped listing read as the complete set.
function _scanTruncNotice(data, noun) {
  if (!data || !data.truncated) return '';
  const max = data.max_files || 0;
  return '<p class="scan-trunc">Showing the first ' + max + ' ' + noun +
         ' found — this scan path holds more. Add a narrower path to see the rest.</p>';
}

function _scanSuggestionsHtml(suggestions, inputId, addFn, expId) {
  if (!suggestions || !suggestions.length) return '';
  const chips = suggestions.map(s => {
    const path = typeof s === 'string' ? s : s.path;
    const why = (typeof s === 'string' ? '' : s.why) || '';
    return '<button type="button" class="scan-suggest-chip" title="' +
      esc(why ? path + ' — ' + why : path) + '" onclick="document.getElementById(\'' +
      escJsAttr(inputId) + '\').value=\'' + escJsAttr(path) + '\';' +
      escJsAttr(addFn) + '(\'' + escJsAttr(expId) + '\')">' +
      '<span class="scan-suggest-path">' + esc(path) + '</span>' +
      (why ? '<span class="scan-suggest-why">' + esc(why) + '</span>' : '') +
      '</button>';
  }).join('');
  return '<div class="scan-suggest"><span class="scan-suggest-label">Suggested:</span>' +
         chips + '</div>';
}

// ── Image gallery ────────────────────────────────────────────────────────────

let imageFilter = '';
let imageSearch = '';
let imageSort = 'date';
let imageLimit = 50;
let imageSortDir = 'desc';

// The last payload this tab drew, so a change to *how* it is drawn — a search,
// a folder filter, a sort, entering compare mode — repaints from what is
// already here instead of refetching.
let _imgDataCache = {expId: null, data: null};

// Repaint from the cached payload. Every control that only changes the view
// goes through this: `loadImages` blanked the tab with "Loading..." before its
// fetch, which destroyed the search box mid-keystroke (focus gone, the next
// character lost) and collapsed `#main-content`, so the scroller clamped the
// reader to the top. Typing one letter threw you to the top of the page.
function repaintImages(expId) {
  if (_imgDataCache.expId === expId && _imgDataCache.data) {
    _renderImages(expId, _imgDataCache.data);
    return Promise.resolve();
  }
  return loadImages(expId);
}

async function loadImages(expId) {
  const container = document.getElementById('detail-tab-images');
  if (!container) return;
  // Only when there is nothing to look at yet. A refresh keeps the current
  // contents on screen until the new ones are ready.
  if (!container.firstChild) {
    container.innerHTML = '<p style="color:var(--muted)">Loading...</p>';
  }

  const data = await api('/api/images/' + expId);
  if (!data) { container.innerHTML = _apiFailedHtml('images'); return; }
  if (data.error && data.error !== 'not found') {
    container.innerHTML = '<p style="color:var(--muted)">Error: ' + esc(data.error) + '</p>';
    return;
  }

  _imgDataCache = {expId: expId, data: data};
  _renderImages(expId, data);
}

// A run's scan folders: saved paths (click to edit), an add box, and the
// suggestions. One builder for the image and data lists, which the Files tab's
// Folders popover shows together — each view used to open on its own copy.
function _scanFoldersHtml(expId, data, o) {
  const id = escJsAttr(expId);
  const paths = data.paths || [];
  let html = '<p class="muted-note" style="margin-bottom:8px">' + o.blurb + ' Paths are relative to project root.</p>';
  for (let i = 0; i < paths.length; i++) {
    html += '<div class="img-path-row">'
      + '<span class="img-path-val" data-path="' + esc(paths[i]) + '" onclick="' + o.edit + '(\'' + id + '\',' + i + ',this)" title="Click to edit">' + esc(paths[i]) + '</span>'
      + '<button class="img-path-edit" onclick="' + o.edit + '(\'' + id + '\',' + i + ',this.parentNode.querySelector(&quot;.img-path-val&quot;))" title="Edit path">&#9998;</button>'
      + '<button class="img-path-del" onclick="' + o.del + '(\'' + id + '\',' + i + ')" title="Remove path">&times;</button>'
      + '</div>';
  }
  html += '<div class="img-path-add">'
    + '<input type="text" id="' + o.inputId + '" placeholder="' + o.placeholder + '" style="flex:1" onkeydown="if(event.key===&quot;Enter&quot;)' + o.add + '(&quot;' + id + '&quot;)">'
    + '<button onclick="' + o.add + '(\'' + id + '\')">Add Path</button></div>';
  html += _scanSuggestionsHtml(data.suggested_paths || [], o.inputId, o.add, expId);
  html += _scanTruncNotice(data, o.truncKind);
  return html;
}

function _imgFoldersHtml(expId, data) {
  return _scanFoldersHtml(expId, data, {
    blurb: 'Folders to scan for images.', inputId: 'img-path-input', placeholder: 'e.g. outputs/samples',
    edit: 'startEditImagePath', del: 'deleteImagePath', add: 'addImagePath', truncKind: 'images'});
}

function _logFoldersHtml(expId, data) {
  return _scanFoldersHtml(expId, data, {
    blurb: 'Folders to scan for logs, CSVs, JSON/JSONL, and TensorBoard event files.', inputId: 'log-path-input',
    placeholder: 'e.g. outputs/logs or logs/tensorboard',
    edit: 'startEditLogPath', del: 'deleteLogPath', add: 'addLogPath', truncKind: 'files'});
}

// Draw the tab from a payload. Split out of `loadImages` so a view change can
// use it without a request — see repaintImages.
function _renderImages(expId, data) {
  const container = document.getElementById('detail-tab-images');
  if (!container) return;

  const paths = data.paths || [];
  const images = (data.images || []).slice();

  mergeArtifactImages(images, data.artifact_images);

  let html = '';

  // Show images if we have any
  if (images.length) {
    // Collect unique directories for filtering
    const dirs = [...new Set(images.map(img => img.dir))].sort();

    // Apply filter
    let filtered = images;
    if (imageFilter) {
      filtered = filtered.filter(img => img.dir === imageFilter);
    }
    // A run that writes one image per sample has hundreds of them, and the
    // folder filter cannot reach a single file. Matching name *and* path keeps
    // `epoch3/` as usable a query as `ISIC_0042`.
    if (imageSearch) {
      const q = imageSearch.toLowerCase();
      filtered = filtered.filter(img =>
        (img.name || '').toLowerCase().includes(q)
        || (img.path || '').toLowerCase().includes(q));
    }

    // Apply sort
    if (imageSort === 'name') {
      filtered = [...filtered].sort((a, b) => imageSortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name));
    } else {
      // date sort
      filtered = [...filtered].sort((a, b) => imageSortDir === 'asc' ? a.modified - b.modified : b.modified - a.modified);
    }

    const totalFiltered = filtered.length;
    // Apply limit
    const displayLimit = imageLimit > 0 ? imageLimit : filtered.length;
    const limited = filtered.slice(0, displayLimit);

    // Compare mode floating bar. The two names and the button are addressable
    // (`#img-cmp-bar`, `.img-cmp-a`/`.img-cmp-b`) because picking an image
    // repaints them in place — see _imgCmpRepaint.
    if (imgCmpMode) {
      html += '<div class="img-cmp-floating-bar" id="img-cmp-bar">';
      html += '<span>A: <strong class="img-cmp-a">' + (imgCmpA ? esc(imgCmpA.name) : '(click to select)') + '</strong></span>';
      html += '<span style="color:var(--muted)">vs</span>';
      html += '<span>B: <strong class="img-cmp-b">' + (imgCmpB ? esc(imgCmpB.name) : '(click to select)') + '</strong></span>';
      html += '<button class="cmp-go" onclick="doIntraCompare()"' + (imgCmpA && imgCmpB ? '' : ' disabled') + '>Compare</button>';
      html += '<button class="cmp-clr" onclick="clearIntraCompare(\'' + expId + '\')">Clear</button>';
      html += '</div>';
    }

    html += '<div class="img-gallery-toolbar">';
    html += '<span style="color:var(--muted);font-size:13px">' + (totalFiltered < images.length ? totalFiltered + ' of ' : '') + images.length + ' image' + (images.length !== 1 ? 's' : '') + '</span>';

    // Compare toggle
    html += ' <button class="img-compare-toggle' + (imgCmpMode ? ' active' : '') + '" onclick="toggleImgCompare(\'' + expId + '\')">' + (imgCmpMode ? 'Cancel Compare' : 'Compare') + '</button>';

    // Refresh button
    html += ' <button class="img-filter-select" onclick="loadImages(\'' + expId + '\')" title="Refresh images" style="cursor:pointer">&#x21bb; Refresh</button>';

    if (dirs.length > 1) {
      html += ' <select class="img-filter-select" onchange="imageFilter=this.value;repaintImages(\'' + expId + '\')">';
      html += '<option value=""' + (imageFilter === '' ? ' selected' : '') + '>All folders</option>';
      for (const d of dirs) {
        html += '<option value="' + esc(d) + '"' + (imageFilter === d ? ' selected' : '') + '>' + esc(d) + '</option>';
      }
      html += '</select>';
    }

    // Sort by
    html += ' <select class="img-filter-select" onchange="imageSort=this.value;repaintImages(\'' + expId + '\')">';
    html += '<option value="date"' + (imageSort === 'date' ? ' selected' : '') + '>Sort by date</option>';
    html += '<option value="name"' + (imageSort === 'name' ? ' selected' : '') + '>Sort by name</option>';
    html += '</select>';

    // Sort direction toggle
    html += ' <button class="img-filter-select" onclick="imageSortDir=imageSortDir===\'asc\'?\'desc\':\'asc\';repaintImages(\'' + expId + '\')" title="Toggle sort direction" style="cursor:pointer">' + (imageSortDir === 'asc' ? '\u25B2 Asc' : '\u25BC Desc') + '</button>';

    // Show count
    html += ' <select class="img-filter-select" onchange="imageLimit=parseInt(this.value);repaintImages(\'' + expId + '\')">';
    const limits = [20, 50, 100, 200, 0];
    const limitLabels = ['Show 20', 'Show 50', 'Show 100', 'Show 200', 'Show all'];
    for (let i = 0; i < limits.length; i++) {
      html += '<option value="' + limits[i] + '"' + (imageLimit === limits[i] ? ' selected' : '') + '>' + limitLabels[i] + '</option>';
    }
    html += '</select>';

    html += '</div>';

    if (imageSearch && !totalFiltered) {
      html += '<div style="color:var(--yellow);font-size:12px;margin-bottom:8px">'
        + 'No file name matches &ldquo;' + esc(imageSearch) + '&rdquo;.</div>';
    }
    if (totalFiltered > displayLimit) {
      html += '<div style="font-size:12px;color:var(--muted);margin-bottom:8px">Showing ' + displayLimit + ' of ' + totalFiltered + ' images</div>';
    }

    // What the modal steps through: the images this gallery is showing, in the
    // order it shows them, so a search or a folder filter narrows the flipping
    // too. `name` is what the modal's jump box matches.
    _intraImgList = limited.map(img => ({src: fileUrl(img.path), name: img.name}));
    _intraRunName = data.name || '';

    html += '<div class="img-gallery">';
    for (const img of limited) {
      const src = fileUrl(img.path);
      const sizeKb = (img.size / 1024).toFixed(1);
      const modDate = img.modified ? new Date(img.modified * 1000).toLocaleString() : '';
      const isSelA = imgCmpMode && imgCmpA && imgCmpA.src === src;
      const isSelB = imgCmpMode && imgCmpB && imgCmpB.src === src;
      const selCls = (isSelA || isSelB) ? ' compare-sel' : '';
      const clickFn = imgCmpMode
        ? 'selectImgCompare(\'' + esc(src) + '\',\'' + esc(img.name) + '\',\'' + expId + '\')'
        : 'openImageModal(\'' + esc(src) + '\',\'' + esc(img.name) + '\')';
      html += '<div class="img-card' + selCls + '" data-src="' + esc(src)
           + '" onclick="' + clickFn + '" style="position:relative">';
      if (isSelA) html += '<div class="img-cmp-badge">A</div>';
      if (isSelB) html += '<div class="img-cmp-badge">B</div>';
      html += '<div class="img-thumb"><img src="' + src + '" alt="' + esc(img.name) + '" loading="lazy"></div>';
      html += '<div class="img-info">';
      html += '<div class="img-name" title="' + esc(img.path) + '">' + esc(img.name) + '</div>';
      if (img.dir !== '.') html += '<div class="img-dir">' + esc(img.dir) + '</div>';
      html += '<div class="img-meta">' + sizeKb + ' KB' + (modDate ? ' &middot; ' + modDate : '') + '</div>';
      html += '</div></div>';
    }
    html += '</div>';
  } else if (!paths.length) {
    html += '<p class="muted-note" style="margin-top:12px">No images yet. Add a folder to scan with ⚙ Folders above.</p>';
  } else {
    html += '<p style="color:var(--muted);margin-top:12px">No images found in the specified path(s).</p>';
    html += ' <button class="img-filter-select" onclick="loadImages(\'' + expId + '\')" title="Refresh images" style="cursor:pointer;margin-top:8px">&#x21bb; Refresh</button>';
  }

  // Entering compare mode, Refresh and the filter selects all rebuild the tab.
  // The gallery is the tallest thing in the detail view, so emptying it
  // collapses `#main-content` and the browser clamps the scroll to the top.
  const _restoreScroll = _holdMainScroll();
  const _focused = document.activeElement;
  const _wasSearch = !!(_focused && _focused.id === 'img-search-input');
  const _caret = _wasSearch ? _focused.selectionStart : null;
  container.innerHTML = html;
  if (_wasSearch) {
    const box = document.getElementById('img-search-input');
    if (box) {
      box.focus();
      if (_caret !== null) box.setSelectionRange(_caret, _caret);
    }
  }
  _restoreScroll();
  requestAnimationFrame(_restoreScroll);
}

let _imgSearchTimer = null;

// Debounced: typing must not rebuild a 200-thumbnail gallery per keystroke.
function _onImageSearch(value, expId) {
  imageSearch = value;
  if (_imgSearchTimer) clearTimeout(_imgSearchTimer);
  _imgSearchTimer = setTimeout(() => repaintImages(expId), 120);
}

// Repaint what picking an image changed, and nothing else.
//
// `selectImgCompare` used to call `loadImages(expId)`: a fresh request for the
// image list and a full rewrite of the tab, to move an A/B badge between two
// cards. With up to 200 thumbnails the gallery is the tallest thing on the page,
// so the rewrite collapsed `#main-content`, the browser clamped its scrollTop to
// 0, and the click threw the reader to the top — with the thumbnail they were
// aiming at now somewhere else. Identical to the Compare Within failure, and the
// same fix: touch the badge, the selected card and the bar that names the picks.
function _imgCmpRepaint() {
  const bar = document.getElementById('img-cmp-bar');
  if (bar) {
    const a = bar.querySelector('.img-cmp-a');
    const b = bar.querySelector('.img-cmp-b');
    if (a) a.textContent = imgCmpA ? imgCmpA.name : '(click to select)';
    if (b) b.textContent = imgCmpB ? imgCmpB.name : '(click to select)';
    const go = bar.querySelector('.cmp-go');
    if (go) go.disabled = !(imgCmpA && imgCmpB);
  }
  document.querySelectorAll('.img-gallery .img-card[data-src]').forEach(card => {
    const src = card.dataset.src;
    const isA = !!(imgCmpA && imgCmpA.src === src);
    const isB = !!(imgCmpB && imgCmpB.src === src);
    card.classList.toggle('compare-sel', isA || isB);
    let badge = card.querySelector('.img-cmp-badge');
    if (isA || isB) {
      if (!badge) {
        badge = document.createElement('div');
        badge.className = 'img-cmp-badge';
        card.prepend(badge);
      }
      badge.textContent = isA ? 'A' : 'B';
    } else if (badge) {
      badge.remove();
    }
  });
}

async function addImagePath(expId) {
  const input = document.getElementById('img-path-input');
  const path = input ? input.value.trim() : '';
  if (!path) return;
  await postApi('/api/experiment/' + expId + '/image-path', {action: 'add', path});
  _afterFolderChange(expId);
}

async function deleteImagePath(expId, index) {
  await postApi('/api/experiment/' + expId + '/image-path', {action: 'delete', index});
  _afterFolderChange(expId);
}

// Editing a saved scan path (Images + Data Files). One implementation for both
// tabs — they were byte-identical apart from the endpoint and the reload.
//
// Three things this has to get right, all of which it got wrong before:
//
// (1) The seed value comes from `data-path`, not from the cell's text. Clicking
//     into the editor bubbles back to the cell's own open-handler, which then
//     re-read `textContent` — by then the input had replaced the text, so it
//     re-opened the editor seeded with an empty string and the path you were
//     fixing a typo in vanished. That is also why the handler is detached
//     below and why re-entry short-circuits: three independent guards, because
//     silently wiping a path the user is mid-edit is not recoverable by undo.
// (2) The row's open-handler comes off for the duration; the reload restores it.
// (3) Clicks inside the editor never reach an ancestor handler.
function _startEditScanPath(expId, index, el, kind) {
  const api = kind === 'image' ? '/image-path' : '/log-path';
  const reload = () => _afterFolderChange(expId);

  const existing = el.querySelector('input');
  if (existing) { existing.focus(); return; }   // already editing this row

  const currentVal = (el.dataset.path || el.textContent).trim();
  el.onclick = null;
  el.removeAttribute('onclick');

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'name-edit-input';
  // Fills the row: a fixed 200px was narrower than most of the paths it had to
  // edit, so the text you were correcting scrolled out of view as you typed.
  input.value = currentVal;
  input.style.cssText = 'width:100%;box-sizing:border-box;font-size:13px;padding:5px 8px';
  input.onclick = (ev) => ev.stopPropagation();
  input.ondblclick = (ev) => ev.stopPropagation();
  // A second click inside the cell must not close the editor. Opening it
  // replaces the cell's text with an input, which reflows the row — so the
  // second press of a double-click lands on the cell rather than the input,
  // blurs it, and the blur-save snapped the editor shut a moment after it
  // opened. preventDefault on mousedown suppresses the focus change (and only
  // that: the ✎ and × buttons still receive their click).
  el.onmousedown = (ev) => { if (ev.target !== input) ev.preventDefault(); };
  el.innerHTML = '';
  el.appendChild(input);
  input.focus();
  input.select();

  let saved = false;
  async function doSave() {
    if (saved) return;
    // Focus can leave the input without leaving the edit — see the mousedown
    // guard above. Only a blur that actually lands outside finishes it.
    if (document.activeElement === input) return;
    saved = true;
    const newVal = input.value.trim();
    if (newVal && newVal !== currentVal) {
      await postApi('/api/experiment/' + expId + api,
                    {action: 'edit', index, path: newVal});
    }
    reload();
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; reload(); }
  });
}

function startEditImagePath(expId, index, el) {
  _startEditScanPath(expId, index, el, 'image');
}

function startEditLogPath(expId, index, el) {
  _startEditScanPath(expId, index, el, 'log');
}

function openImageModal(src, name) {
  // The overlay is fixed and appended to <body>, so it does not itself move the
  // scroller — but the grid it was opened from can collapse underneath it, and
  // then `#main-content` clamps. Held both ways round: opening and closing.
  const restore = _holdMainScroll();
  closeImageModal();
  const overlay = document.createElement('div');
  overlay.className = 'img-modal-overlay';
  overlay.id = 'img-modal-overlay';
  overlay.onclick = (ev) => { if (ev.target === overlay) closeImageModal(); };

  const content = document.createElement('div');
  content.className = 'img-modal-content';
  content.innerHTML = '<div class="img-modal-header"><span class="img-modal-name">' + esc(name) + '</span>'
    + modalBackdropPickerHtml()
    + '<button class="img-modal-close" onclick="closeImageModal()">&times;</button></div>' +
    '<img src="' + src + '" alt="' + esc(name) + '" style="max-width:100%;max-height:calc(100vh - 80px);object-fit:contain">';
  overlay.appendChild(content);
  document.body.appendChild(overlay);
  applyModalBackdrop();
  // Enlarging has to enlarge: a 128x128 image would otherwise render at 128px
  // in a full-screen overlay, smaller than the gallery thumb behind it.
  fitModalImages(content.querySelectorAll('img'),
                 window.innerWidth * 0.95, window.innerHeight - 80);

  // One handler, stored on the overlay, so every close path can take it off
  // again. Inlined `.remove()` on the backdrop and the × left this listener
  // attached for the life of the page, once per image ever opened.
  const handler = (ev) => { if (ev.key === 'Escape') closeImageModal(); };
  document.addEventListener('keydown', handler);
  overlay.__escHandler = handler;
  overlay.__restoreScroll = restore;
  restore();
  requestAnimationFrame(restore);
}

function closeImageModal() {
  const overlay = document.getElementById('img-modal-overlay');
  if (!overlay) return;
  if (overlay.__escHandler) document.removeEventListener('keydown', overlay.__escHandler);
  const restore = overlay.__restoreScroll;
  overlay.remove();
  if (restore) { restore(); requestAnimationFrame(restore); }
}

// ── Logs tab ─────────────────────────────────────────────────────────────────

let logSort = 'date';
let logSortDir = 'desc';
let logFilter = '';

let _logDataCache = null;

async function loadLogs(expId) {
  const container = document.getElementById('detail-tab-logs');
  if (!container) return;
  container.innerHTML = '<p style="color:var(--muted)">Loading...</p>';

  const data = await api('/api/logs/' + expId);
  if (!data) { container.innerHTML = _apiFailedHtml('logs'); return; }
  if (data.error && data.error !== 'not found') {
    container.innerHTML = '<p style="color:var(--muted)">Error: ' + esc(data.error) + '</p>';
    return;
  }
  _logDataCache = {expId: expId, data: data};
  _renderLogs(expId, data);
}

// Paint Files › Data from the cached listing when it is this run's — the
// counts fetch already has it, and a live run's rebuild must not refetch and
// flash "Loading…" every 5 s. Refresh and a sort change still go to loadLogs.
function repaintLogs(expId) {
  if (_logDataCache && _logDataCache.expId === expId) {
    _renderLogs(expId, _logDataCache.data);
    return Promise.resolve();
  }
  return loadLogs(expId);
}

function _renderLogs(expId, data) {
  const container = document.getElementById('detail-tab-logs');
  if (!container) return;
  const paths = data.paths || [];
  const files = data.files || [];
  let html = '';

  // Show files if we have any
  if (files.length) {
    const dirs = [...new Set(files.map(f => f.dir))].sort();

    // Apply filter
    let filtered = files;
    if (logFilter) {
      filtered = filtered.filter(f => f.dir === logFilter);
    }

    // Apply sort
    if (logSort === 'name') {
      filtered = [...filtered].sort((a, b) => logSortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name));
    } else {
      filtered = [...filtered].sort((a, b) => logSortDir === 'asc' ? a.modified - b.modified : b.modified - a.modified);
    }

    html += '<div class="img-gallery-toolbar">';
    html += '<span style="color:var(--muted);font-size:13px">' + files.length + ' file' + (files.length !== 1 ? 's' : '') + '</span>';

    // Refresh
    html += ' <button class="img-filter-select" onclick="loadLogs(\'' + expId + '\')" title="Refresh" style="cursor:pointer">&#x21bb; Refresh</button>';

    // Directory filter
    if (dirs.length > 1) {
      html += ' <select class="img-filter-select" onchange="logFilter=this.value;loadLogs(\'' + expId + '\')">';
      html += '<option value=""' + (logFilter === '' ? ' selected' : '') + '>All folders</option>';
      for (const d of dirs) {
        html += '<option value="' + esc(d) + '"' + (logFilter === d ? ' selected' : '') + '>' + esc(d) + '</option>';
      }
      html += '</select>';
    }

    // Sort
    html += ' <select class="img-filter-select" onchange="logSort=this.value;loadLogs(\'' + expId + '\')">';
    html += '<option value="date"' + (logSort === 'date' ? ' selected' : '') + '>Sort by date</option>';
    html += '<option value="name"' + (logSort === 'name' ? ' selected' : '') + '>Sort by name</option>';
    html += '</select>';

    html += ' <button class="img-filter-select" onclick="logSortDir=logSortDir===\'asc\'?\'desc\':\'asc\';loadLogs(\'' + expId + '\')" title="Toggle sort direction" style="cursor:pointer">' + (logSortDir === 'asc' ? '\u25B2 Asc' : '\u25BC Desc') + '</button>';

    html += '</div>';

    // File table
    html += '<table class="params-table" style="margin-top:8px">';
    html += '<tr><th>File</th><th>Size</th><th>Modified</th><th style="width:72px"></th></tr>';
    for (const f of filtered) {
      const sizeKb = (f.size / 1024).toFixed(1);
      const modDate = f.modified ? new Date(f.modified * 1000).toLocaleString() : '';
      const ext = f.ext || '';
      const logExts = ['log', 'txt', 'out', 'err'];
      const csvExts = ['csv', 'tsv'];
      const badge = logExts.includes(ext) ? '<span class="artifact-type-badge log">log</span>' : csvExts.includes(ext) ? '<span class="artifact-type-badge data">csv</span>' : '<span class="artifact-type-badge data">data</span>';
      html += '<tr data-fname="' + esc(f.path || f.name) + '">';
      html += '<td><div class="artifact-row">' + badge + ' ' + esc(f.name);
      if (f.dir !== '.') html += ' <span style="color:var(--muted);font-size:11px">(' + esc(f.dir) + ')</span>';
      html += '</div></td>';
      html += '<td style="font-size:12px;color:var(--muted)">' + sizeKb + ' KB</td>';
      html += '<td style="font-size:12px;color:var(--muted)">' + modDate + '</td>';
      html += '<td><button class="view-source-btn" onclick="viewLogFile(\'' + escJsAttr(f.path) + '\',\'' + escJsAttr(f.name) + '\')">view</button></td>';
      html += '</tr>';
    }
    html += '</table>';
  } else if (!paths.length) {
    html += '<p class="muted-note" style="margin-top:12px">No data files yet. Add a folder to scan with ⚙ Folders above.</p>';
  } else {
    html += '<p style="color:var(--muted);margin-top:12px">No log files found in the specified path(s).</p>';
    html += ' <button class="img-filter-select" onclick="loadLogs(\'' + expId + '\')" title="Refresh" style="cursor:pointer;margin-top:8px">&#x21bb; Refresh</button>';
  }

  container.innerHTML = html;
  filterFiles(_filesFilter);
}

async function addLogPath(expId) {
  const input = document.getElementById('log-path-input');
  const path = input ? input.value.trim() : '';
  if (!path) return;
  await postApi('/api/experiment/' + expId + '/log-path', {action: 'add', path});
  _afterFolderChange(expId);
}

async function deleteLogPath(expId, index) {
  await postApi('/api/experiment/' + expId + '/log-path', {action: 'delete', index});
  _afterFolderChange(expId);
}

// ── Result types management ──────────────────────────────────────────────────

let _resultTypes = null; // cached result types
let _metricPrefixes = null; // cached namespace prefixes

async function loadResultTypes() {
  if (_resultTypes !== null) return _resultTypes;
  try {
    const d = await api('/api/result-types');
    _resultTypes = d.types || [];
    _metricPrefixes = d.prefixes || ['train', 'val', 'test'];
  } catch(e) {
    _resultTypes = ['accuracy', 'loss', 'auroc', 'f1', 'precision', 'recall', 'mse', 'mae', 'r2'];
    _metricPrefixes = ['train', 'val', 'test'];
  }
  return _resultTypes;
}

async function loadMetricPrefixes() {
  if (_metricPrefixes !== null) return _metricPrefixes;
  await loadResultTypes();
  return _metricPrefixes;
}

async function populateResultTypeDropdown(expId) {
  const dl = document.getElementById('metric-suggestions-' + expId);
  if (!dl) return;
  const types = await loadResultTypes();
  const savedPrefixes = await loadMetricPrefixes();

  // Also pick up any prefixes already used in this experiment
  const exp = allExperiments.find(e => e.id === expId);
  const existingKeys = new Set();
  if (exp?.metrics) {
    for (const k of Object.keys(exp.metrics)) existingKeys.add(k);
  }
  const existingPrefixes = new Set();
  for (const k of existingKeys) {
    const si = k.indexOf('/');
    if (si > 0) existingPrefixes.add(k.slice(0, si));
  }
  const prefixes = [...new Set([...savedPrefixes, ...existingPrefixes])].sort();

  // Build suggestions: existing keys, bare types, prefixed types
  const suggestions = new Set();
  for (const k of existingKeys) suggestions.add(k);
  for (const t of types) {
    suggestions.add(t);
    for (const p of prefixes) suggestions.add(p + '/' + t);
  }

  dl.innerHTML = '';
  for (const s of suggestions) {
    const opt = document.createElement('option');
    opt.value = s;
    dl.appendChild(opt);
  }
}

async function logMetric(id) {
  const keyEl = document.getElementById('result-key-' + id);
  const valEl = document.getElementById('result-val-' + id);
  const stepEl = document.getElementById('result-step-' + id);
  if (!keyEl || !valEl) return;
  const key = keyEl.value.trim();
  if (!key) { alert('Enter a metric key'); return; }
  const value = valEl.value.trim();
  if (!value || isNaN(parseFloat(value))) { alert('Value must be a number'); return; }
  const step = stepEl ? stepEl.value.trim() : '';
  const payload = {key, value};
  if (step !== '') payload.step = step;
  const d = await postApi('/api/experiment/' + id + '/log-metric', payload);
  if (d.ok) {
    valEl.value = ''; if (stepEl) stepEl.value = '';
    // Auto-save new base type and prefix for future suggestions
    const hasSlash = key.includes('/');
    const baseType = hasSlash ? key.split('/').slice(1).join('/') : key;
    const types = await loadResultTypes();
    if (!types.includes(baseType)) {
      await postApi('/api/result-types', {action: 'add', name: baseType});
      _resultTypes = null;
    }
    if (hasSlash) {
      const prefix = key.split('/')[0];
      const prefixes = await loadMetricPrefixes();
      if (!prefixes.includes(prefix)) {
        await postApi('/api/result-types', {action: 'add', name: prefix, target: 'prefix'});
        _metricPrefixes = null;
      }
    }
    refreshDetail(id);
    loadExperiments();
    owlSay('Logged ' + key + ' = ' + d.value + ' (step ' + d.step + ')');
  }
  else alert(d.error || 'Failed to log metric');
}

async function deleteResult(id, key) {
  if (!confirm('Delete result "' + key + '"?')) return;
  const d = await postApi('/api/experiment/' + id + '/delete-result', {key});
  if (d.ok) { refreshDetail(id); loadExperiments(); }
  else alert(d.error || 'Failed to delete result');
}

async function deleteMetricLast(id, key) {
  const d = await postApi('/api/experiment/' + id + '/delete-metric', {key, mode: 'last'});
  if (d.ok) { refreshDetail(id); loadExperiments(); }
  else alert(d.error || 'Failed to delete metric point');
}

async function deleteMetric(id, key) {
  if (!confirm('Delete all data points for metric "' + key + '"?')) return;
  const d = await postApi('/api/experiment/' + id + '/delete-metric', {key, mode: 'all'});
  if (d.ok) { refreshDetail(id); loadExperiments(); }
  else alert(d.error || 'Failed to delete metric');
}

async function deleteMetricPoint(id, key, step) {
  const d = await postApi('/api/experiment/' + id + '/delete-metric', {key, mode: 'step', step});
  if (d.ok) { refreshDetail(id); loadExperiments(); owlSay('Deleted point (step ' + step + ')'); }
  else alert(d.error || 'Failed to delete metric point');
}

function startMetricRename(id, key, td) {
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
        const d = await postApi('/api/experiment/' + id + '/rename-metric', {old_key: key, new_key: newKey});
        if (d.ok) { refreshDetail(id); loadExperiments(); owlSay('Renamed: ' + newKey); return; }
        else alert(d.error || 'Failed to rename');
      }
    }
    td.innerHTML = savedHtml;
  };
  input.onkeydown = e => { if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false); };
  input.onblur = () => finish(false);
}

function startResultEdit(id, key, td) {
  if (td.querySelector('input')) return;
  const row = td.querySelector('.artifact-row');
  const valText = row ? row.childNodes[0].textContent.trim() : td.textContent.trim();
  const savedHtml = td.innerHTML;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = valText;
  input.style.cssText = 'width:100%;font-size:13px;padding:2px 4px;font-family:inherit;box-sizing:border-box';
  td.innerHTML = '';
  td.appendChild(input);
  input.focus();
  input.select();
  const restore = () => { td.innerHTML = savedHtml; };
  const save = async () => {
    const val = input.value.trim();
    if (!val || isNaN(parseFloat(val))) { alert('Value must be a number'); restore(); return; }
    if (val === valText) { restore(); return; }
    const d = await postApi('/api/experiment/' + id + '/edit-result', {key, value: val});
    if (d.ok) { refreshDetail(id); loadExperiments(); }
    else { restore(); alert(d.error || 'Failed'); }
  };
  input.onblur = save;
  input.onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } if (e.key === 'Escape') restore(); };
}


function openManageResultTypes() {
  const overlay = document.createElement('div');
  overlay.className = 'img-modal-overlay';
  overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };

  const content = document.createElement('div');
  content.className = 'img-modal-content';
  content.style.cssText = 'max-width:500px;width:90vw';

  async function render() {
    const types = await loadResultTypes();
    const prefixes = await loadMetricPrefixes();
    let html = '<div class="img-modal-header">';
    html += '<span class="img-modal-name">Manage Metrics</span>';
    html += '<button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button>';
    html += '</div>';
    html += '<div style="padding:16px">';

    // Namespace prefixes
    html += '<div style="margin-bottom:16px">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Namespace Prefixes</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">';
    for (let i = 0; i < prefixes.length; i++) {
      html += '<div class="result-type-chip"><span>' + esc(prefixes[i]) + '/</span>';
      html += '<button onclick="removeMetricItem(\'prefix\',' + i + ')" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px;padding:0 2px" title="Remove">&times;</button></div>';
    }
    html += '</div>';
    html += '<div class="artifact-add-form"><input type="text" id="new-metric-prefix" placeholder="New prefix (e.g. eval)" style="width:160px" onkeydown="if(event.key===\'Enter\')addMetricItem(\'prefix\')">';
    html += '<button onclick="addMetricItem(\'prefix\')">+ Add</button></div></div>';

    // Metric types
    html += '<div style="margin-bottom:8px">';
    html += '<div style="font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px">Metric Types</div>';
    html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">';
    for (let i = 0; i < types.length; i++) {
      html += '<div class="result-type-chip"><span>' + esc(types[i]) + '</span>';
      html += '<button onclick="removeMetricItem(\'type\',' + i + ')" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px;padding:0 2px" title="Remove">&times;</button></div>';
    }
    html += '</div>';
    html += '<div class="artifact-add-form"><input type="text" id="new-result-type" placeholder="New metric type (e.g. top5_acc)" style="width:160px" onkeydown="if(event.key===\'Enter\')addMetricItem(\'type\')">';
    html += '<button onclick="addMetricItem(\'type\')">+ Add</button></div></div>';

    html += '</div>';
    content.innerHTML = html;
  }

  overlay.appendChild(content);
  document.body.appendChild(overlay);
  render();

  window._rtOverlayRender = render;

  const handler = (ev) => { if (ev.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); } };
  document.addEventListener('keydown', handler);
}

async function addMetricItem(target) {
  const inputId = target === 'prefix' ? 'new-metric-prefix' : 'new-result-type';
  const input = document.getElementById(inputId);
  if (!input) return;
  const name = input.value.trim().toLowerCase();
  if (!name) return;
  const d = await postApi('/api/result-types', {action: 'add', name, target});
  if (d.ok) {
    _resultTypes = d.types; _metricPrefixes = d.prefixes;
    input.value = '';
    if (window._rtOverlayRender) window._rtOverlayRender();
    if (currentDetailId) populateResultTypeDropdown(currentDetailId);
  } else {
    alert(d.error || 'Failed');
  }
}

async function removeMetricItem(target, index) {
  const d = await postApi('/api/result-types', {action: 'remove', index, target});
  if (d.ok) {
    _resultTypes = d.types; _metricPrefixes = d.prefixes;
    if (window._rtOverlayRender) window._rtOverlayRender();
    if (currentDetailId) populateResultTypeDropdown(currentDetailId);
  }
}

// ── Within-experiment comparison ─────────────────────────────────────────────

let withinSeq1 = null, withinSeq2 = null;
let _withinEvents = []; // cache timeline events

// The checkpoints a run offers as comparison points. Derived from the cached
// events, never re-requested: which points exist is a property of the run, and
// picking one of them does not change it.
function _cwCheckpoints() {
  return _withinEvents.filter(e =>
    e.event_type === 'cell_exec' || e.event_type === 'artifact' || e.event_type === 'metric'
  );
}

function _cwDescribeEvent(ev) {
  if (!ev) return '';
  if (ev.event_type === 'cell_exec') {
    const info = ev.value || {};
    return (info.source_preview || ev.key || 'cell').split('\n')[0].slice(0, 50);
  }
  if (ev.event_type === 'metric') {
    return ev.key + ' = ' + (typeof ev.value === 'object' ? JSON.stringify(ev.value) : ev.value);
  }
  if (ev.event_type === 'artifact') return ev.key || 'artifact';
  return ev.key || ev.event_type;
}

function _cwEventIcon(type) {
  if (type === 'cell_exec') return '<span class="tl-type-label tl-type-cell_exec">CELL</span>';
  if (type === 'metric') return '<span class="tl-type-label tl-type-metric">METRIC</span>';
  if (type === 'artifact') return '<span class="tl-type-label tl-type-artifact">ARTIFACT</span>';
  return '<span class="tl-type-label">' + type.toUpperCase() + '</span>';
}

// How a chosen point reads in the selection bar.
function _cwPointText(seq, which) {
  if (seq === null) return which === 'a' ? 'Select start point' : 'Select end point';
  const ev = _cwCheckpoints().find(e => e.seq === seq);
  const label = _cwDescribeEvent(ev) || '#' + seq;
  return '#' + seq + ': ' + label;
}

function _cwSeqCellHtml(seq) {
  if (withinSeq1 === seq) return '<span class="cw-badge cw-badge-a">A</span>';
  if (withinSeq2 === seq) return '<span class="cw-badge cw-badge-b">B</span>';
  return String(seq);
}

async function loadCompareWithin(expId) {
  const events = await api('/api/timeline/' + expId);
  const container = document.getElementById('detail-tool-compare-within');
  if (!Array.isArray(events)) {
    if (container) container.innerHTML = _apiFailedHtml('the timeline');
    return;
  }
  _withinEvents = events;
  const checkpoints = _cwCheckpoints();

  let html = '<div class="cw-header">';
  html += '<h3>Snapshot Comparison</h3>';
  html += '<p class="cw-subtitle">Pick two points in the timeline to see what changed between them: variables, metrics, and artifacts.</p>';
  html += '</div>';

  // Selection bar
  html += '<div class="tl-compare-bar">';
  html += '<div class="cw-point cw-point-a' + (withinSeq1 !== null ? ' active' : '') + '">';
  html += '<span class="cw-point-label">A</span>';
  html += '<span class="cw-point-desc">' + esc(_cwPointText(withinSeq1, 'a')) + '</span>';
  html += '</div>';
  html += '<span class="cw-arrow">&#8594;</span>';
  html += '<div class="cw-point cw-point-b' + (withinSeq2 !== null ? ' active' : '') + '">';
  html += '<span class="cw-point-label">B</span>';
  html += '<span class="cw-point-desc">' + esc(_cwPointText(withinSeq2, 'b')) + '</span>';
  html += '</div>';
  html += '<div class="cw-actions">';
  html += '<button id="cw-go" onclick="doWithinCompare(\'' + escJsAttr(expId) + '\')"'
       + (withinSeq1 !== null && withinSeq2 !== null ? '' : ' disabled') + '>Compare</button>';
  html += '<button onclick="clearWithinSelection()" class="cw-clear">Clear</button>';
  html += '</div>';
  html += '</div>';

  // Visual timeline with markers
  html += '<div class="cw-timeline" style="max-height:400px;overflow-y:auto">';
  for (const ev of checkpoints) {
    const isA = withinSeq1 === ev.seq;
    const isB = withinSeq2 === ev.seq;
    const selCls = (isA || isB) ? ' tl-seq-select selected' : ' tl-seq-select';
    const markerCls = isA ? ' cw-marker-a' : (isB ? ' cw-marker-b' : '');
    // `data-seq` is what lets a pick repaint the two rows it touches instead of
    // the whole list they sit in.
    html += '<div class="tl-event tl-' + ev.event_type + selCls + markerCls
         + '" data-seq="' + ev.seq + '" onclick="selectWithinSeq(' + ev.seq + ')" style="cursor:pointer">';
    html += '<div class="tl-seq">' + _cwSeqCellHtml(ev.seq) + '</div>';
    html += '<div class="tl-body">';
    html += _cwEventIcon(ev.event_type);
    html += '<strong>' + esc(_cwDescribeEvent(ev)) + '</strong>';
    html += ' <span style="color:var(--muted);margin-left:8px;font-size:11px">' + fmtDt(ev.ts) + '</span>';
    html += '</div></div>';
  }
  if (!checkpoints.length) {
    html += '<p style="color:var(--muted);padding:20px">No timeline events recorded for this experiment. Timeline comparison works best with notebook runs.</p>';
  }
  html += '</div>';
  html += '<div id="within-compare-result"></div>';
  container.innerHTML = html;
}

// Repaint what the selection changed, and only that.
//
// This used to be `loadCompareWithin(expId)`: every click on a checkpoint
// re-requested the timeline and rewrote the tab's whole innerHTML. Two
// scrollers paid for it. The checkpoint list is its own overflow box, so it
// snapped back to the top and the row just clicked left the screen; and
// emptying `#main-content` collapses its content, so the browser clamped the
// page scroll to 0 as well -- the trap the detail refresh already documents
// (js/detail.js). Choosing a point moved the point out from under the cursor.
function _cwRepaintSelection() {
  const container = document.getElementById('detail-tool-compare-within');
  if (!container) return;
  const scroller = document.getElementById('main-content');
  const keptPage = scroller ? scroller.scrollTop : 0;
  const list = container.querySelector('.cw-timeline');
  const keptList = list ? list.scrollTop : 0;

  for (const which of ['a', 'b']) {
    const seq = which === 'a' ? withinSeq1 : withinSeq2;
    const el = container.querySelector('.cw-point-' + which);
    if (!el) continue;
    el.classList.toggle('active', seq !== null);
    const desc = el.querySelector('.cw-point-desc');
    if (desc) desc.textContent = _cwPointText(seq, which);
  }
  const go = container.querySelector('#cw-go');
  if (go) go.disabled = !(withinSeq1 !== null && withinSeq2 !== null);

  container.querySelectorAll('.cw-timeline .tl-event[data-seq]').forEach(row => {
    const seq = Number(row.dataset.seq);
    const isA = withinSeq1 === seq, isB = withinSeq2 === seq;
    row.classList.toggle('selected', isA || isB);
    row.classList.toggle('cw-marker-a', isA);
    row.classList.toggle('cw-marker-b', isB);
    const cell = row.querySelector('.tl-seq');
    if (cell) cell.innerHTML = _cwSeqCellHtml(seq);
  });

  // The panel below answered the previous pair of points; leaving it under a
  // bar that now names different ones is worse than clearing it.
  const res = document.getElementById('within-compare-result');
  if (res) res.innerHTML = '';

  if (list) list.scrollTop = keptList;
  if (scroller) scroller.scrollTop = keptPage;
}

function selectWithinSeq(seq) {
  if (withinSeq1 === null || (withinSeq1 !== null && withinSeq2 !== null)) {
    withinSeq1 = seq;
    withinSeq2 = null;
  } else {
    withinSeq2 = seq;
  }
  _cwRepaintSelection();
}

function clearWithinSelection() {
  withinSeq1 = null;
  withinSeq2 = null;
  _cwRepaintSelection();
}

async function doWithinCompare(expId) {
  if (withinSeq1 === null || withinSeq2 === null) return;
  const lo = Math.min(withinSeq1, withinSeq2);
  const hi = Math.max(withinSeq1, withinSeq2);

  const [vars1, vars2, metricsData] = await Promise.all([
    api('/api/vars-at/' + expId + '?seq=' + lo),
    api('/api/vars-at/' + expId + '?seq=' + hi),
    api('/api/metrics/' + expId),
  ]);

  let html = '<div class="within-compare">';

  // Summary header
  const evA = _withinEvents.find(e => e.seq === lo);
  const evB = _withinEvents.find(e => e.seq === hi);
  html += '<div class="cw-result-header">';
  html += '<div class="cw-result-point"><span class="cw-badge cw-badge-a">A</span> #' + lo + (evA ? ' &mdash; ' + esc((evA.key||evA.event_type).slice(0,40)) : '') + '</div>';
  html += '<span class="cw-arrow">&#8594;</span>';
  html += '<div class="cw-result-point"><span class="cw-badge cw-badge-b">B</span> #' + hi + (evB ? ' &mdash; ' + esc((evB.key||evB.event_type).slice(0,40)) : '') + '</div>';
  html += '</div>';

  // Filter controls
  html += '<div class="cw-filters">';
  html += '<label><input type="checkbox" id="cw-only-changed" checked onchange="filterWithinResults()"> Show only changes</label>';
  html += '</div>';

  // Variables section
  const allVarKeys = [...new Set([...Object.keys(vars1), ...Object.keys(vars2)])].sort();
  const changedVars = allVarKeys.filter(k => String(vars1[k]) !== String(vars2[k]));
  html += '<h4 class="cw-section-title">Variables <span class="cw-change-count">' + changedVars.length + ' changed / ' + allVarKeys.length + ' total</span></h4>';
  if (allVarKeys.length) {
    html += '<table class="params-table cw-table">';
    html += '<tr><th>Variable</th><th>Point A (#' + lo + ')</th><th>Point B (#' + hi + ')</th><th>Delta</th></tr>';
    for (const k of allVarKeys) {
      const v1 = vars1[k] !== undefined ? String(vars1[k]).slice(0, 60) : '--';
      const v2 = vars2[k] !== undefined ? String(vars2[k]).slice(0, 60) : '--';
      const differs = String(vars1[k]) !== String(vars2[k]);
      const cls = differs ? ' class="differs cw-changed"' : ' class="cw-unchanged"';
      let delta = '';
      if (differs) {
        const n1 = parseFloat(vars1[k]), n2 = parseFloat(vars2[k]);
        if (!isNaN(n1) && !isNaN(n2)) {
          const d = n2 - n1;
          delta = '<span class="cw-delta ' + (d > 0 ? 'cw-delta-up' : 'cw-delta-down') + '">' + (d > 0 ? '+' : '') + (Number.isInteger(d) ? d : d.toFixed(4)) + '</span>';
        } else {
          delta = '<span class="cw-delta cw-delta-changed">changed</span>';
        }
      }
      html += '<tr' + cls + '><td class="var-name">' + esc(k) + '</td><td>' + esc(v1) + '</td><td>' + esc(v2) + '</td><td>' + delta + '</td></tr>';
    }
    html += '</table>';
  } else {
    html += '<p style="color:var(--muted);font-size:13px">No variable snapshots between these points.</p>';
  }

  // Metrics section — show metrics logged between the two seq points
  const metricEvents = _withinEvents.filter(e => e.event_type === 'metric' && e.seq >= lo && e.seq <= hi);
  if (metricEvents.length || Object.keys(metricsData).length) {
    html += '<h4 class="cw-section-title" style="margin-top:16px">Metrics between A and B <span class="cw-change-count">' + metricEvents.length + ' logged</span></h4>';
    if (metricEvents.length) {
      html += '<table class="params-table cw-table">';
      html += '<tr><th>Metric</th><th>Value</th><th>Step</th><th>When</th></tr>';
      for (const me of metricEvents) {
        const val = typeof me.value === 'object' ? JSON.stringify(me.value) : String(me.value);
        html += '<tr class="cw-changed"><td>' + esc(me.key||'') + '</td><td>' + esc(val) + '</td><td>#' + me.seq + '</td><td>' + fmtDt(me.ts) + '</td></tr>';
      }
      html += '</table>';
    } else {
      html += '<p style="color:var(--muted);font-size:13px">No metrics logged between these timeline points.</p>';
    }
  }

  // Artifacts section — show artifacts logged between the two seq points
  const artifactEvents = _withinEvents.filter(e => e.event_type === 'artifact' && e.seq >= lo && e.seq <= hi);
  if (artifactEvents.length) {
    html += '<h4 class="cw-section-title" style="margin-top:16px">Artifacts between A and B <span class="cw-change-count">' + artifactEvents.length + '</span></h4>';
    html += '<table class="params-table cw-table">';
    html += '<tr><th>Artifact</th><th>Step</th><th>When</th></tr>';
    for (const ae of artifactEvents) {
      html += '<tr class="cw-changed"><td>' + esc(ae.key||'') + '</td><td>#' + ae.seq + '</td><td>' + fmtDt(ae.ts) + '</td></tr>';
    }
    html += '</table>';
  }

  html += '</div>';
  document.getElementById('within-compare-result').innerHTML = html;
}

function filterWithinResults() {
  const onlyChanged = document.getElementById('cw-only-changed');
  if (!onlyChanged) return;
  const show = onlyChanged.checked;
  document.querySelectorAll('.cw-unchanged').forEach(el => {
    el.style.display = show ? 'none' : '';
  });
}
