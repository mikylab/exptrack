"""Timeline rendering, cell lineage viewer, and variable state reconstruction."""

JS_TIMELINE = r"""
// ── Detail sub-tabs ──────────────────────────────────────────────────────────

let currentDetailTab = 'overview';
let currentDetailExpId = '';

function switchDetailTab(tab, expId) {
  currentDetailTab = tab;
  currentDetailExpId = expId;
  document.querySelectorAll('#detail-tabs .tab').forEach((t,i) => {
    const tabs = ['overview','timeline','charts','images','logs','compare-within'];
    t.classList.toggle('active', tabs[i] === tab);
  });
  ['overview','timeline','charts','images','logs','compare-within'].forEach(t => {
    const el = document.getElementById('detail-tab-'+t);
    if (el) el.style.display = t === tab ? '' : 'none';
  });
  if (tab === 'overview') renderOverviewChartPreview(_chartsMetricsData);
  if (tab === 'charts') loadChartsTab(expId);
  if (tab === 'timeline') loadTimeline(expId);
  if (tab === 'images') loadImages(expId);
  if (tab === 'logs') loadLogs(expId);
  if (tab === 'compare-within') loadCompareWithin(expId);
}

// ── Timeline visualization ───────────────────────────────────────────────────

let timelineFilter = '';

async function loadTimeline(expId, filter) {
  if (filter !== undefined) timelineFilter = filter;
  // 'lineage' is a client-side filter — fetch all cell_exec events then filter
  const isLineageFilter = timelineFilter === 'lineage';
  const serverFilter = isLineageFilter ? 'cell_exec' : timelineFilter;
  const url = serverFilter
    ? '/api/timeline/' + expId + '?type=' + serverFilter
    : '/api/timeline/' + expId;
  let events = await api(url);
  if (isLineageFilter) {
    events = events.filter(ev => ev.parent_hash);
  }
  const container = document.getElementById('detail-tab-timeline');

  let html = '<div class="tl-filters">';
  const types = ['', 'cell_exec', 'var_set', 'artifact', 'observational', 'lineage'];
  const labels = ['All', 'Code', 'Variables', 'Artifacts', 'Observational', 'Lineage'];
  types.forEach((t, i) => {
    html += '<button class="' + (timelineFilter===t?'active':'') + '" onclick="loadTimeline(\'' + expId + '\',\'' + t + '\')">' + labels[i] + '</button>';
  });
  html += '</div>';

  if (!events.length) {
    html += '<p style="color:var(--muted)">No timeline events recorded.</p>';
    container.innerHTML = html;
    return;
  }

  html += '<p style="color:var(--muted);font-size:12px;margin-bottom:8px">' + events.length + ' events. Click "view source" on cells to see full code.</p>';

  const varState = {};

  html += '<div class="timeline">';
  for (const ev of events) {
    const cls = 'tl-event tl-' + ev.event_type;
    const ts = fmtDt(ev.ts);
    const icons = {cell_exec:'&gt;&gt;', var_set:'=', artifact:'&#9633;', metric:'#', observational:'..'};
    const colors = {cell_exec:'var(--tl-cell)', var_set:'var(--tl-var)', artifact:'var(--tl-artifact)', metric:'var(--tl-metric)', observational:'var(--tl-obs)'};
    const typeLabels = {cell_exec:'code', var_set:'var', artifact:'artifact', metric:'metric', observational:'observe'};
    const icon = icons[ev.event_type] || '?';
    const iconColor = colors[ev.event_type] || 'var(--fg)';
    const typeLabel = '<span class="tl-type-label tl-type-' + ev.event_type + '">' + (typeLabels[ev.event_type]||ev.event_type) + '</span>';

    if (ev.event_type === 'cell_exec' || ev.event_type === 'observational') {
      const info = ev.value || {};
      const preview = (info.source_preview || '').split('\n')[0].slice(0, 80);
      let badges = '';
      if (info.code_is_new) badges += '<span class="tl-badge tl-badge-new">new</span>';
      if (info.code_changed) badges += '<span class="tl-badge tl-badge-edited">edited</span>';
      if (info.is_rerun) badges += '<span class="tl-badge tl-badge-rerun">rerun</span>';
      if (info.has_output) badges += '<span class="tl-badge tl-badge-output">output</span>';
      if (ev.parent_hash) badges += '<span class="tl-badge tl-badge-lineage" title="Derived from cell ' + ev.parent_hash + '" onclick="event.stopPropagation();viewCellSource(\'' + ev.parent_hash + '\',this.closest(\'.tl-body\').querySelector(\'.view-source-btn\') || this)">&#8592; ' + ev.parent_hash.slice(0,6) + '</span>';

      // View source button - uses cell_hash to fetch from lineage
      const viewSrcBtn = ev.cell_hash ? ' <button class="view-source-btn" onclick="event.stopPropagation();viewCellSource(\'' + ev.cell_hash + '\',this)">view source</button>' : '';

      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong>' + esc(ev.key||'') + '</strong>' + badges + viewSrcBtn;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      if (preview) html += '<div class="tl-code-preview">' + esc(preview) + '</div>';
      if (info.output_preview) {
        html += '<div style="margin-top:3px;font-size:11px;color:var(--green)">output: ' + esc(String(info.output_preview).slice(0,80)) + '</div>';
      }

      if (ev.source_diff && ev.source_diff.length) {
        html += '<div class="tl-diff">';
        for (const d of ev.source_diff.slice(0, 8)) {
          if (d.op === 'summary') html += '<div style="color:var(--muted);font-style:italic">' + esc(d.line) + '</div>';
          else if (d.op === '+') html += '<div class="diff-add">+ ' + esc(d.line.slice(0,80)) + '</div>';
          else if (d.op === '-') html += '<div class="diff-del">- ' + esc(d.line.slice(0,80)) + '</div>';
        }
        if (ev.source_diff.length > 8) html += '<div style="color:var(--muted)">... ' + (ev.source_diff.length - 8) + ' more lines</div>';
        html += '</div>';
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
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-var)">' + esc(ev.key) + '</strong> = ' + esc(valStr) + prevHtml;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';

    } else if (ev.event_type === 'artifact') {
      html += '<div class="' + cls + '">';
      html += '<div class="tl-seq">' + ev.seq + '</div>';
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
      html += '<div class="tl-seq">' + ev.seq + '</div>';
      html += '<div class="tl-icon" style="color:' + iconColor + '">' + icon + '</div>';
      html += '<div class="tl-body">';
      html += typeLabel + '<strong style="color:var(--tl-metric)">' + esc(ev.key) + '</strong> = ' + ev.value;
      html += ' <span style="color:var(--muted);margin-left:8px">' + ts + '</span>';
      html += '</div></div>';
    }
  }
  html += '</div>';
  container.innerHTML = html;
}

async function viewCellSource(cellHash, btnEl) {
  // Toggle: if source is already showing, hide it
  const existing = btnEl.parentElement.querySelector('.source-view');
  if (existing) {
    existing.remove();
    btnEl.textContent = 'view source';
    return;
  }
  btnEl.textContent = 'loading...';
  const data = await api('/api/cell-source/' + cellHash);
  btnEl.textContent = 'hide source';
  if (data.error || !data.source) {
    const div = document.createElement('div');
    div.className = 'source-view';
    div.innerHTML = '<span style="color:var(--yellow)">Source was compacted to save space.</span>'
      + '<br><span style="color:var(--muted);font-size:12px">Cell hash: ' + cellHash + '</span>'
      + '<br><span style="color:var(--muted);font-size:12px">The cell lineage and variable changes are still tracked in the timeline.</span>';
    btnEl.parentElement.appendChild(div);
    return;
  }
  let html = '<div class="source-view">';
  // Show current source with line numbers
  html += '<div style="margin-bottom:8px;color:var(--blue);font-size:11px;text-transform:uppercase">Current cell source (hash: ' + cellHash + ')</div>';
  const lines = data.source.split('\n');
  for (let i = 0; i < lines.length; i++) {
    html += '<span class="line-num">' + (i+1) + '</span>' + esc(lines[i]) + '\n';
  }
  // If there's a parent, show it too
  if (data.parent_source) {
    html += '<div style="margin-top:12px;border-top:1px solid var(--border);padding-top:8px;color:var(--muted);font-size:11px;text-transform:uppercase">Previous version (hash: ' + data.parent_hash + ')</div>';
    const plines = data.parent_source.split('\n');
    for (let i = 0; i < plines.length; i++) {
      html += '<span class="line-num">' + (i+1) + '</span><span style="color:var(--muted)">' + esc(plines[i]) + '</span>\n';
    }
  }
  html += '</div>';
  btnEl.parentElement.insertAdjacentHTML('beforeend', html);
}

// ── Image gallery ────────────────────────────────────────────────────────────

let imageFilter = '';
let imageSort = 'date';
let imageLimit = 50;
let imageSortDir = 'desc';

async function loadImages(expId) {
  const container = document.getElementById('detail-tab-images');
  if (!container) return;
  container.innerHTML = '<p style="color:var(--muted)">Loading...</p>';

  const data = await api('/api/images/' + expId);
  if (data.error && data.error !== 'not found') {
    container.innerHTML = '<p style="color:var(--muted)">Error: ' + esc(data.error) + '</p>';
    return;
  }

  const paths = data.paths || [];
  const suggestedPaths = data.suggested_paths || [];
  let images = data.images || [];

  // Also include image artifacts from the experiment's artifact table
  const artImages = data.artifact_images || [];
  if (artImages.length) {
    const existingPaths = new Set(images.map(img => img.path));
    for (const ai of artImages) {
      if (!existingPaths.has(ai.path)) {
        images.push(ai);
      }
    }
  }

  let html = '<div class="img-paths-section">';
  html += '<h3 style="font-size:14px;margin-bottom:8px">Image Paths</h3>';
  html += '<p style="font-size:12px;color:var(--muted);margin-bottom:8px">Add folders to scan for images. Paths are relative to project root.</p>';

  // Show saved paths
  if (paths.length) {
    for (let i = 0; i < paths.length; i++) {
      const p = paths[i];
      html += '<div class="img-path-row">';
      html += '<span class="img-path-val" ondblclick="startEditImagePath(\'' + expId + '\',' + i + ',this)">' + esc(p) + '</span>';
      html += '<button class="img-path-del" onclick="deleteImagePath(\'' + expId + '\',' + i + ')" title="Remove path">&times;</button>';
      html += '</div>';
    }
  }

  // Add path form
  html += '<div class="img-path-add">';
  html += '<input type="text" id="img-path-input" placeholder="e.g. outputs/samples" style="flex:1">';
  html += '<button onclick="addImagePath(\'' + expId + '\')">Add Path</button>';
  html += '</div>';

  // Suggested paths from output_dir or params
  if (suggestedPaths.length && paths.length === 0) {
    html += '<div style="margin-top:6px;font-size:11px;color:var(--muted)">Suggestions: ';
    html += suggestedPaths.map(s => '<a href="#" style="color:var(--blue)" onclick="event.preventDefault();document.getElementById(\'img-path-input\').value=\'' + esc(s) + '\';addImagePath(\'' + expId + '\')">' + esc(s) + '</a>').join(', ');
    html += '</div>';
  }
  html += '</div>';

  // Show images if we have any
  if (images.length) {
    // Collect unique directories for filtering
    const dirs = [...new Set(images.map(img => img.dir))].sort();

    // Apply filter
    let filtered = images;
    if (imageFilter) {
      filtered = filtered.filter(img => img.dir === imageFilter);
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

    // Compare mode floating bar
    if (imgCmpMode) {
      html += '<div class="img-cmp-floating-bar">';
      html += '<span>A: <strong>' + (imgCmpA ? esc(imgCmpA.name) : '(click to select)') + '</strong></span>';
      html += '<span style="color:var(--muted)">vs</span>';
      html += '<span>B: <strong>' + (imgCmpB ? esc(imgCmpB.name) : '(click to select)') + '</strong></span>';
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
      html += ' <select class="img-filter-select" onchange="imageFilter=this.value;loadImages(\'' + expId + '\')">';
      html += '<option value=""' + (imageFilter === '' ? ' selected' : '') + '>All folders</option>';
      for (const d of dirs) {
        html += '<option value="' + esc(d) + '"' + (imageFilter === d ? ' selected' : '') + '>' + esc(d) + '</option>';
      }
      html += '</select>';
    }

    // Sort by
    html += ' <select class="img-filter-select" onchange="imageSort=this.value;loadImages(\'' + expId + '\')">';
    html += '<option value="date"' + (imageSort === 'date' ? ' selected' : '') + '>Sort by date</option>';
    html += '<option value="name"' + (imageSort === 'name' ? ' selected' : '') + '>Sort by name</option>';
    html += '</select>';

    // Sort direction toggle
    html += ' <button class="img-filter-select" onclick="imageSortDir=imageSortDir===\'asc\'?\'desc\':\'asc\';loadImages(\'' + expId + '\')" title="Toggle sort direction" style="cursor:pointer">' + (imageSortDir === 'asc' ? '\u25B2 Asc' : '\u25BC Desc') + '</button>';

    // Show count
    html += ' <select class="img-filter-select" onchange="imageLimit=parseInt(this.value);loadImages(\'' + expId + '\')">';
    const limits = [20, 50, 100, 200, 0];
    const limitLabels = ['Show 20', 'Show 50', 'Show 100', 'Show 200', 'Show all'];
    for (let i = 0; i < limits.length; i++) {
      html += '<option value="' + limits[i] + '"' + (imageLimit === limits[i] ? ' selected' : '') + '>' + limitLabels[i] + '</option>';
    }
    html += '</select>';

    html += '</div>';

    if (totalFiltered > displayLimit) {
      html += '<div style="font-size:12px;color:var(--muted);margin-bottom:8px">Showing ' + displayLimit + ' of ' + totalFiltered + ' images</div>';
    }

    html += '<div class="img-gallery">';
    for (const img of limited) {
      const src = '/api/file/' + encodeURIComponent(img.path).replace(/%2F/g, '/');
      const sizeKb = (img.size / 1024).toFixed(1);
      const modDate = img.modified ? new Date(img.modified * 1000).toLocaleString() : '';
      const isSelA = imgCmpMode && imgCmpA && imgCmpA.src === src;
      const isSelB = imgCmpMode && imgCmpB && imgCmpB.src === src;
      const selCls = (isSelA || isSelB) ? ' compare-sel' : '';
      const clickFn = imgCmpMode
        ? 'selectImgCompare(\'' + esc(src) + '\',\'' + esc(img.name) + '\',\'' + expId + '\')'
        : 'openImageModal(\'' + esc(src) + '\',\'' + esc(img.name) + '\')';
      html += '<div class="img-card' + selCls + '" onclick="' + clickFn + '" style="position:relative">';
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
  } else if (paths.length) {
    html += '<p style="color:var(--muted);margin-top:12px">No images found in the specified path(s).</p>';
    html += ' <button class="img-filter-select" onclick="loadImages(\'' + expId + '\')" title="Refresh images" style="cursor:pointer;margin-top:8px">&#x21bb; Refresh</button>';
  }

  container.innerHTML = html;
}

async function addImagePath(expId) {
  const input = document.getElementById('img-path-input');
  const path = input ? input.value.trim() : '';
  if (!path) return;
  await postApi('/api/experiment/' + expId + '/image-path', {action: 'add', path});
  loadImages(expId);
}

async function deleteImagePath(expId, index) {
  await postApi('/api/experiment/' + expId + '/image-path', {action: 'delete', index});
  loadImages(expId);
}

function startEditImagePath(expId, index, el) {
  const currentVal = el.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'name-edit-input';
  input.value = currentVal; input.style.cssText = 'width:200px;font-size:12px;padding:2px 4px';
  el.innerHTML = ''; el.appendChild(input); input.focus(); input.select();
  let saved = false;
  async function doSave() {
    if (saved) return; saved = true;
    const newVal = input.value.trim();
    if (newVal && newVal !== currentVal) {
      await postApi('/api/experiment/' + expId + '/image-path', {action: 'edit', index, path: newVal});
    }
    loadImages(expId);
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; loadImages(expId); }
  });
}

function openImageModal(src, name) {
  const overlay = document.createElement('div');
  overlay.className = 'img-modal-overlay';
  overlay.onclick = (ev) => { if (ev.target === overlay) overlay.remove(); };

  const content = document.createElement('div');
  content.className = 'img-modal-content';
  content.innerHTML = '<div class="img-modal-header"><span class="img-modal-name">' + esc(name) + '</span><button class="img-modal-close" onclick="this.closest(\'.img-modal-overlay\').remove()">&times;</button></div>' +
    '<img src="' + src + '" alt="' + esc(name) + '" style="max-width:100%;max-height:calc(100vh - 80px);object-fit:contain">';
  overlay.appendChild(content);
  document.body.appendChild(overlay);

  const handler = (ev) => { if (ev.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', handler); } };
  document.addEventListener('keydown', handler);
}

// ── Logs tab ─────────────────────────────────────────────────────────────────

let logSort = 'date';
let logSortDir = 'desc';
let logFilter = '';

async function loadLogs(expId) {
  const container = document.getElementById('detail-tab-logs');
  if (!container) return;
  container.innerHTML = '<p style="color:var(--muted)">Loading...</p>';

  const data = await api('/api/logs/' + expId);
  if (data.error && data.error !== 'not found') {
    container.innerHTML = '<p style="color:var(--muted)">Error: ' + esc(data.error) + '</p>';
    return;
  }

  const paths = data.paths || [];
  const suggestedPaths = data.suggested_paths || [];
  let files = data.files || [];

  let html = '<div class="img-paths-section">';
  html += '<h3 style="font-size:14px;margin-bottom:8px">Scan Paths</h3>';
  html += '<p style="font-size:12px;color:var(--muted);margin-bottom:8px">Add folders to scan for logs, CSVs, JSON/JSONL, and TensorBoard event files. Paths are relative to project root.</p>';

  // Show saved paths
  if (paths.length) {
    for (let i = 0; i < paths.length; i++) {
      const p = paths[i];
      html += '<div class="img-path-row">';
      html += '<span class="img-path-val" ondblclick="startEditLogPath(\'' + expId + '\',' + i + ',this)">' + esc(p) + '</span>';
      html += '<button class="img-path-del" onclick="deleteLogPath(\'' + expId + '\',' + i + ')" title="Remove path">&times;</button>';
      html += '</div>';
    }
  }

  // Add path form
  html += '<div class="img-path-add">';
  html += '<input type="text" id="log-path-input" placeholder="e.g. outputs/logs or logs/tensorboard" style="flex:1">';
  html += '<button onclick="addLogPath(\'' + expId + '\')">Add Path</button>';
  html += '</div>';

  // Suggested paths
  if (suggestedPaths.length && paths.length === 0) {
    html += '<div style="margin-top:6px;font-size:11px;color:var(--muted)">Suggestions: ';
    html += suggestedPaths.map(s => '<a href="#" style="color:var(--blue)" onclick="event.preventDefault();document.getElementById(\'log-path-input\').value=\'' + esc(s) + '\';addLogPath(\'' + expId + '\')">' + esc(s) + '</a>').join(', ');
    html += '</div>';
  }
  html += '</div>';

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
    html += '<tr><th>File</th><th>Size</th><th>Modified</th><th style="width:60px"></th></tr>';
    for (const f of filtered) {
      const sizeKb = (f.size / 1024).toFixed(1);
      const modDate = f.modified ? new Date(f.modified * 1000).toLocaleString() : '';
      const ext = f.ext || '';
      const logExts = ['log', 'txt', 'out', 'err'];
      const csvExts = ['csv', 'tsv'];
      const badge = logExts.includes(ext) ? '<span class="artifact-type-badge log">log</span>' : csvExts.includes(ext) ? '<span class="artifact-type-badge data">csv</span>' : '<span class="artifact-type-badge data">data</span>';
      html += '<tr>';
      html += '<td><div class="artifact-row">' + badge + ' ' + esc(f.name);
      if (f.dir !== '.') html += ' <span style="color:var(--muted);font-size:11px">(' + esc(f.dir) + ')</span>';
      html += '</div></td>';
      html += '<td style="font-size:12px;color:var(--muted)">' + sizeKb + ' KB</td>';
      html += '<td style="font-size:12px;color:var(--muted)">' + modDate + '</td>';
      html += '<td><button class="view-source-btn" onclick="viewLogFile(\'' + esc(f.path) + '\',\'' + esc(f.name) + '\')">view</button></td>';
      html += '</tr>';
    }
    html += '</table>';
  } else if (paths.length) {
    html += '<p style="color:var(--muted);margin-top:12px">No log files found in the specified path(s).</p>';
    html += ' <button class="img-filter-select" onclick="loadLogs(\'' + expId + '\')" title="Refresh" style="cursor:pointer;margin-top:8px">&#x21bb; Refresh</button>';
  }

  container.innerHTML = html;
}

async function addLogPath(expId) {
  const input = document.getElementById('log-path-input');
  const path = input ? input.value.trim() : '';
  if (!path) return;
  await postApi('/api/experiment/' + expId + '/log-path', {action: 'add', path});
  loadLogs(expId);
}

async function deleteLogPath(expId, index) {
  await postApi('/api/experiment/' + expId + '/log-path', {action: 'delete', index});
  loadLogs(expId);
}

function startEditLogPath(expId, index, el) {
  const currentVal = el.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text'; input.className = 'name-edit-input';
  input.value = currentVal; input.style.cssText = 'width:200px;font-size:12px;padding:2px 4px';
  el.innerHTML = ''; el.appendChild(input); input.focus(); input.select();
  let saved = false;
  async function doSave() {
    if (saved) return; saved = true;
    const newVal = input.value.trim();
    if (newVal && newVal !== currentVal) {
      await postApi('/api/experiment/' + expId + '/log-path', {action: 'edit', index, path: newVal});
    }
    loadLogs(expId);
  }
  input.addEventListener('blur', doSave);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') { ev.preventDefault(); input.blur(); }
    if (ev.key === 'Escape') { saved = true; loadLogs(expId); }
  });
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

async function loadCompareWithin(expId) {
  const events = await api('/api/timeline/' + expId);
  _withinEvents = events;
  const container = document.getElementById('detail-tab-compare-within');

  // Group events into meaningful checkpoints: cell_exec, metric, artifact
  const checkpoints = events.filter(e =>
    e.event_type === 'cell_exec' || e.event_type === 'artifact' || e.event_type === 'metric'
  );

  // Helper to describe an event
  function describeEvent(ev) {
    if (ev.event_type === 'cell_exec') {
      const info = ev.value || {};
      return (info.source_preview || ev.key || 'cell').split('\n')[0].slice(0, 50);
    }
    if (ev.event_type === 'metric') return ev.key + ' = ' + (typeof ev.value === 'object' ? JSON.stringify(ev.value) : ev.value);
    if (ev.event_type === 'artifact') return ev.key || 'artifact';
    return ev.key || ev.event_type;
  }

  function eventIcon(type) {
    if (type === 'cell_exec') return '<span class="tl-type-label tl-type-cell_exec">CELL</span>';
    if (type === 'metric') return '<span class="tl-type-label tl-type-metric">METRIC</span>';
    if (type === 'artifact') return '<span class="tl-type-label tl-type-artifact">ARTIFACT</span>';
    return '<span class="tl-type-label">' + type.toUpperCase() + '</span>';
  }

  let html = '<div class="cw-header">';
  html += '<h3>Snapshot Comparison</h3>';
  html += '<p class="cw-subtitle">Pick two points in the timeline to see what changed between them: variables, metrics, and artifacts.</p>';
  html += '</div>';

  // Selection bar
  html += '<div class="tl-compare-bar">';
  const a1Label = withinSeq1 !== null ? describeEvent(checkpoints.find(e => e.seq === withinSeq1) || {event_type:'',value:null,key:'#'+withinSeq1}) : 'click below';
  const a2Label = withinSeq2 !== null ? describeEvent(checkpoints.find(e => e.seq === withinSeq2) || {event_type:'',value:null,key:'#'+withinSeq2}) : 'click below';
  html += '<div class="cw-point cw-point-a' + (withinSeq1 !== null ? ' active' : '') + '">';
  html += '<span class="cw-point-label">A</span>';
  html += '<span class="cw-point-desc">' + esc(withinSeq1 !== null ? '#' + withinSeq1 + ': ' + a1Label : 'Select start point') + '</span>';
  html += '</div>';
  html += '<span class="cw-arrow">&#8594;</span>';
  html += '<div class="cw-point cw-point-b' + (withinSeq2 !== null ? ' active' : '') + '">';
  html += '<span class="cw-point-label">B</span>';
  html += '<span class="cw-point-desc">' + esc(withinSeq2 !== null ? '#' + withinSeq2 + ': ' + a2Label : 'Select end point') + '</span>';
  html += '</div>';
  html += '<div class="cw-actions">';
  html += '<button onclick="doWithinCompare(\'' + expId + '\')"' + (withinSeq1 !== null && withinSeq2 !== null ? '' : ' disabled') + '>Compare</button>';
  html += '<button onclick="withinSeq1=null;withinSeq2=null;loadCompareWithin(\'' + expId + '\')" class="cw-clear">Clear</button>';
  html += '</div>';
  html += '</div>';

  // Visual timeline with markers
  html += '<div class="cw-timeline" style="max-height:400px;overflow-y:auto">';
  for (const ev of checkpoints) {
    const isA = withinSeq1 === ev.seq;
    const isB = withinSeq2 === ev.seq;
    const selCls = (isA || isB) ? ' tl-seq-select selected' : ' tl-seq-select';
    const markerCls = isA ? ' cw-marker-a' : (isB ? ' cw-marker-b' : '');
    html += '<div class="tl-event tl-' + ev.event_type + selCls + markerCls + '" onclick="selectWithinSeq(' + ev.seq + ',\'' + expId + '\')" style="cursor:pointer">';
    html += '<div class="tl-seq">';
    if (isA) html += '<span class="cw-badge cw-badge-a">A</span>';
    else if (isB) html += '<span class="cw-badge cw-badge-b">B</span>';
    else html += ev.seq;
    html += '</div>';
    html += '<div class="tl-body">';
    html += eventIcon(ev.event_type);
    html += '<strong>' + esc(describeEvent(ev)) + '</strong>';
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

function selectWithinSeq(seq, expId) {
  if (withinSeq1 === null || (withinSeq1 !== null && withinSeq2 !== null)) {
    withinSeq1 = seq;
    withinSeq2 = null;
  } else {
    withinSeq2 = seq;
  }
  loadCompareWithin(expId);
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
"""

# Initialization
