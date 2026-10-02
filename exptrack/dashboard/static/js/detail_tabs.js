// Run detail tabs: the tab/view names and switching between them.

// ── Detail tabs ──────────────────────────────────────────────────────────────

let currentDetailTab = 'overview';
// The sub-view picked in each tab that has them; '' means "the run's default"
// (Code: Timeline for a notebook run, Changes for a script run). A pick
// survives moving between runs, like the tab does.
let currentDetailView = {files: '', code: ''};

// Tab and sub-view names. Buttons carry `data-tab`, so nothing depends on the
// order here — it used to be index-coupled to the button row, and a mismatch
// silently showed the wrong panel.
const DETAIL_TABS = ['overview', 'charts', 'files', 'code'];
// Opened from the header's Tools menu, not a tab button; still addressable.
const DETAIL_TOOLS = ['compare-within', 'confusion'];
const DETAIL_VIEWS = {files: ['images', 'data', 'artifacts'], code: ['timeline', 'changes', 'source', 'env']};
// Tabs that became sub-views in 2.1. Old links (`#run=…&tab=timeline`) and
// callers still say these.
const _LEGACY_TABS = {timeline: ['code', 'timeline'], images: ['files', 'images'], logs: ['files', 'data']};

// The one place a tab/view name is validated. Unknown tab → Overview; a view
// the tab does not have → '' (the default).
function _resolveDetailTab(tab, view) {
  const legacy = _LEGACY_TABS[tab];
  if (legacy) return {tab: legacy[0], view: legacy[1]};
  if (DETAIL_TOOLS.includes(tab)) return {tab: tab, view: ''};
  if (!DETAIL_TABS.includes(tab)) return {tab: 'overview', view: ''};
  const views = DETAIL_VIEWS[tab] || [];
  return {tab: tab, view: views.includes(view) ? view : ''};
}

// ── Split view ───────────────────────────────────────────────────────────────
// A second tab beside the first, so Overview and Charts (or Files, or Code) can
// be read at once. `detailSplit` names the right pane's tab ('' = no split).
// It is part of the address and survives moving between runs, like the tab.
let detailSplit = '';

// The right pane shows any full tab except the one on the left. A Tools view
// takes the whole width, and an unknown name turns the split off rather than
// leaving a blank pane.
function _resolveSplit(main, split) {
  if (!split || DETAIL_TOOLS.includes(main) || !DETAIL_TABS.includes(split) || split === main) return '';
  // Below the breakpoint CSS hides the right pane; say so here too, or the
  // live poll keeps reloading a pane nobody can see.
  if (typeof matchMedia === 'function' && !matchMedia('(min-width: 1201px)').matches) return '';
  return split;
}

// Whether a tab is on screen in either pane — what a live run's poll asks.
function _detailTabVisible(tab) {
  return currentDetailTab === tab || _resolveSplit(currentDetailTab, detailSplit) === tab;
}

function toggleDetailSplit(expId) {
  const next = detailSplit ? ''
    : (currentDetailTab === 'charts' ? 'overview' : 'charts');
  setDetailSplit(next, expId);
}

function setDetailSplit(tab, expId) {
  detailSplit = DETAIL_TABS.includes(tab) ? tab : '';
  if (expId && expId === currentDetailId) _pushViewHash(_currentRunHash(expId), true);
  _showDetailTab(currentDetailTab, expId);
}

function switchDetailTab(tab, expId) {
  const r = _resolveDetailTab(tab, '');
  if (r.view) currentDetailView[r.tab] = r.view;
  // Picking the tab the right pane shows swaps the two sides, so the split
  // never collapses into the same tab twice.
  if (detailSplit && r.tab === detailSplit && DETAIL_TABS.includes(currentDetailTab)) {
    detailSplit = currentDetailTab;
  }
  currentDetailTab = r.tab;
  // The tab is part of the run's address, so a reload lands on the tab the
  // reader was on. Replaced, never pushed: a tab is not a place Back returns to.
  if (expId && expId === currentDetailId) _pushViewHash(_currentRunHash(expId), true);
  _showDetailTab(r.tab, expId);
}

// The run on screen, so a sub-view's default can depend on it (a notebook
// run's Code opens on Timeline). Set by refreshDetail.
let _detailExp = null;
// Where a Tools view's × returns to.
let _detailPrevTab = 'overview';

function _showDetailTab(tab, expId) {
  if (!DETAIL_TOOLS.includes(tab)) _detailPrevTab = tab;
  const right = _resolveSplit(tab, detailSplit);
  document.querySelectorAll('#detail-tabs .tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === tab);
  });
  const splitBtn = document.querySelector('#detail-tabs .tab-split');
  if (splitBtn) splitBtn.classList.toggle('active', !!right);
  const panes = document.getElementById('detail-panes');
  if (panes) panes.classList.toggle('split', !!right);
  DETAIL_TABS.concat(DETAIL_TOOLS).forEach(t => {
    const el = document.getElementById('detail-tab-' + t);
    if (!el) return;
    el.style.display = (t === tab || t === right) ? '' : 'none';
    el.classList.toggle('pane-left', !!right && t === tab);
    el.classList.toggle('pane-right', !!right && t === right);
  });
  _renderSplitHead(tab, right, expId);
  // A pane carried across a same-run rebuild keeps what it shows; Charts
  // still reloads, since new metrics are why the poll rebuilt at all.
  for (const t of [tab, right]) {
    if (t && (!_keptPanes[t] || t === 'charts')) _loadDetailTab(t, expId);
  }
}

// Panes refreshDetail carried across its rebuild (see there); empty otherwise.
let _keptPanes = {};

// Focus and caret in the detail panel survive a rebuild — typing in the params
// filter while a live run polls lost the box mid-word, and ←/→ then stepped
// to another run. Elements are found again by id.
function _holdDetailFocus() {
  const a = document.activeElement;
  if (!a || !a.id || !document.getElementById('detail-panel')?.contains(a)) return () => {};
  const id = a.id, start = a.selectionStart, end = a.selectionEnd;
  return () => {
    const el = document.getElementById(id);
    if (!el || el === document.activeElement) return;
    el.focus();
    if (start != null && el.setSelectionRange) { try { el.setSelectionRange(start, end); } catch (e) { /* not a text field */ } }
  };
}

// What showing a tab needs: its loader, and for Files/Code the sub-view.
function _loadDetailTab(tab, expId) {
  if (tab === 'overview') { renderOverviewChartPreview(_chartsMetricsData); _syncNotesCap(); }
  if (tab === 'charts') loadChartsTab(expId);
  if (tab === 'compare-within') loadCompareWithin(expId);
  if (tab === 'confusion') loadConfusionTab(expId);
  if (tab === 'files' && _filesCounts.expId !== expId) {
    // The listings decide the default view and feed both views, so they are
    // fetched once (loadFilesCounts) before the view paints from the cache.
    _filesCounts.expId = expId;
    loadFilesCounts(expId).then(() => {
      if (_detailTabVisible('files') && currentDetailId === expId) {
        _showSubview('files', currentDetailView.files || _filesDefaultView(), expId);
      }
    });
    return;
  }
  if (tab === 'files') _paintFilesCounts();
  if (DETAIL_VIEWS[tab]) _showSubview(tab, currentDetailView[tab] || _detailDefaultView(tab), expId);
}

// The right pane's own tab picker, above it; the main tab row picks the left.
function _renderSplitHead(main, right, expId) {
  const head = document.getElementById('split-head');
  if (!head) return;
  if (!right) { head.innerHTML = ''; return; }
  const id = escJsAttr(expId || currentDetailId);
  const labels = {overview: 'Overview', charts: 'Charts', files: 'Files', code: 'Code'};
  head.innerHTML = '<div class="subview-bar">' + DETAIL_TABS.filter(t => t !== main).map(t =>
    '<button class="seg' + (t === right ? ' active' : '') + '" onclick="setDetailSplit(\'' + t + '\',\'' + id + '\')">'
    + labels[t] + '</button>').join('') + '</div>'
    + '<button class="close-btn" onclick="setDetailSplit(\'\',\'' + id + '\')" title="Close the split">&times;</button>';
}

function switchDetailView(tab, view, expId) {
  const r = _resolveDetailTab(tab, view);
  currentDetailView[r.tab] = r.view;
  // Replaced, never pushed, like a tab switch. The address carries the left
  // pane's view; a view picked in the right pane is kept in memory.
  if (expId && expId === currentDetailId) _pushViewHash(_currentRunHash(expId), true);
  _showSubview(r.tab, r.view || _detailDefaultView(r.tab), expId);
}

function _showSubview(tab, view, expId) {
  const host = document.getElementById('detail-tab-' + tab);
  if (!host) return;
  host.querySelectorAll('.subview-bar .seg').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  host.querySelectorAll('.subview').forEach(p => { p.style.display = p.dataset.view === view ? '' : 'none'; });
  if (view === 'timeline') loadTimeline(expId);
  if (view === 'images') repaintImages(expId);
  if (view === 'data') repaintLogs(expId);
  if (view === 'source') loadRunSource(expId);
}

// A notebook run's "code" is its executed cells, in order — the Timeline — so
// Code opens there for one; a script run opens on its diff. `script` is the
// notebook path, or the literal 'notebook' when the path was not resolvable.
function _isNotebookRun(exp) {
  if (!exp) return false;
  const s = String(exp.script || '').toLowerCase();
  return s.endsWith('.ipynb') || (s === 'notebook' && !exp.has_script_capture);
}

// How many images / data files / artifacts this run has (null until the
// listing has loaded, or when it failed), and which run they are for. Filled
// by loadFilesCounts; refreshDetail replaces it on another run.
let _filesCounts = {expId: '', images: null, data: null, artifacts: 0};

// The first Files view with something in it; Images when nothing has loaded or
// everything is empty, since adding an image folder is where that starts.
function _filesDefaultView() {
  const c = _filesCounts || {};
  if (c.images) return 'images';
  if (c.data) return 'data';
  if (c.artifacts) return 'artifacts';
  return 'images';
}

// The view a tab opens on when the reader has not picked one.
function _detailDefaultView(tab) {
  if (tab === 'code') return _isNotebookRun(_detailExp) ? 'timeline' : 'changes';
  if (tab === 'files') return _filesDefaultView();
  return '';
}

function closeDetailTool(expId) { switchDetailTab(_detailPrevTab, expId); }

// ── Tab shells ───────────────────────────────────────────────────────────────
// Files and Code each hold a segmented switch over panes. The existing loaders
// keep their container ids (`detail-tab-timeline`, `-images`, `-logs`), now
// nested in a pane, so they did not have to change.

function _subviewBarHtml(tab, views, exp) {
  const id = escJsAttr(exp.id);
  return '<div class="subview-bar">' + views.map(([v, label]) =>
    '<button class="seg" data-view="' + v + '" onclick="switchDetailView(\'' + tab + '\',\'' + v + '\',\'' + id + '\')">'
    + label + '<span class="seg-count" id="seg-count-' + v + '"></span></button>').join('') + '</div>';
}

function _filesShellHtml(exp) {
  const id = escJsAttr(exp.id);
  return '<div class="files-bar">'
    + _subviewBarHtml('files', [['images', 'Images'], ['data', 'Data'], ['artifacts', 'Artifacts']], exp)
    + '<div class="files-tools"><input type="search" placeholder="filter…" value="' + esc(_filesFilter)
    + '" oninput="filterFiles(this.value)">'
    + '<button class="action-btn" onclick="toggleFilesFolders(\'' + id + '\')" title="Folders scanned for images and data files">⚙ Folders</button></div>'
    + '<div id="files-folders-pop" class="files-folders-pop" style="display:none"></div></div>'
    + '<div class="subview" data-view="images"><div id="detail-tab-images"></div></div>'
    + '<div class="subview" data-view="data" style="display:none"><div id="detail-tab-logs"></div></div>'
    + '<div class="subview" data-view="artifacts" style="display:none"><div id="detail-files-artifacts"></div></div>';
}

function _codeShellHtml(exp) {
  return _subviewBarHtml('code', [['timeline', 'Timeline'], ['changes', 'Changes'], ['source', 'Source'], ['env', 'Env']], exp)
    + '<div class="subview" data-view="timeline"><div id="detail-tab-timeline"></div></div>'
    + '<div class="subview" data-view="changes" style="display:none"><div id="detail-code-changes"></div></div>'
    + '<div class="subview" data-view="source" style="display:none"><div id="detail-code-source">'
    + '<div id="tl-source-body"><p class="muted-note">Loading source…</p></div></div></div>'
    + '<div class="subview" data-view="env" style="display:none"><div id="detail-code-env"></div></div>';
}

// A Tools view: the analysis under a bar that names it and closes back to the
// tab the reader came from. Its loader writes the inner container.
function _toolShellHtml(tool, label, exp) {
  return '<div id="detail-tab-' + tool + '" style="display:none"><div class="tool-head"><span>' + label + '</span>'
    + '<button class="close-btn" onclick="closeDetailTool(\'' + escJsAttr(exp.id) + '\')" title="Close">&times;</button></div>'
    + '<div id="detail-tool-' + tool + '"></div></div>';
}

// ── Files tab: counts, folders, filter ──────────────────────────────────────

// Both listings in parallel, so the switch shows "Images 48 · Data 112" before
// either view is opened. Caches the payloads the views render from.
async function loadFilesCounts(expId) {
  const [img, logs] = await Promise.all([
    api('/api/images/' + expId), api('/api/logs/' + expId)]);
  if (currentDetailId !== expId) return;
  if (!img || img.error) _filesCounts.images = null;
  else {
    const all = (img.images || []).slice();
    mergeArtifactImages(all, img.artifact_images);
    _filesCounts.images = all.length;
    _imgDataCache = {expId: expId, data: img};
  }
  if (!logs || logs.error) _filesCounts.data = null;
  else {
    _filesCounts.data = (logs.files || []).length;
    _logDataCache = {expId: expId, data: logs};
  }
  _paintFilesCounts();
  _renderFilesFolders(expId);
}

function _paintFilesCounts() {
  for (const v of DETAIL_VIEWS.files) {
    const el = document.getElementById('seg-count-' + v);
    if (!el) continue;
    const n = _filesCounts[v];
    el.textContent = n == null ? '' : String(n);
    // Greyed but clickable: an empty Images view is where you add a folder.
    el.parentElement.classList.toggle('empty', n === 0);
  }
}

function toggleFilesFolders(expId) {
  const pop = document.getElementById('files-folders-pop');
  if (!pop) return;
  const open = pop.style.display === 'none';
  pop.style.display = open ? '' : 'none';
  if (!open) return;
  _renderFilesFolders(expId);
  _dismissOnOutsideClick(pop, '.files-tools .action-btn', () => { pop.style.display = 'none'; });
}

// Image and data scan folders in one place; it used to be a block at the top of
// each view, which opened on a wall of suggestion chips.
function _renderFilesFolders(expId) {
  const pop = document.getElementById('files-folders-pop');
  if (!pop || pop.style.display === 'none') return;
  const img = (_imgDataCache && _imgDataCache.expId === expId) ? _imgDataCache.data : null;
  const logs = (_logDataCache && _logDataCache.expId === expId) ? _logDataCache.data : null;
  pop.innerHTML = '<div class="ffp-head"><strong>Folders to scan</strong>'
    + '<button class="close-btn" onclick="toggleFilesFolders(\'' + escJsAttr(expId) + '\')" title="Close">&times;</button></div>'
    + '<h3>Images</h3>' + (img ? _imgFoldersHtml(expId, img) : _apiFailedHtml('image folders'))
    + '<h3>Data files</h3>' + (logs ? _logFoldersHtml(expId, logs) : _apiFailedHtml('data folders'));
}

// A saved folder changed: one fetch refreshes the counts, both caches and
// the popover; the open view repaints from the cache.
async function _afterFolderChange(expId) {
  await loadFilesCounts(expId);
  const view = currentDetailView.files || _filesDefaultView();
  if (view === 'images') repaintImages(expId);
  if (view === 'data') repaintLogs(expId);
}

// One box for whichever Files view is open. Images go through the gallery's
// own search (it pages, so hiding cards would undercount); data rows and
// artifacts filter in place.
let _filesFilter = '';

function filterFiles(q) {
  _filesFilter = q || '';
  const view = currentDetailView.files || _filesDefaultView();
  if (view === 'images' && imageSearch !== _filesFilter) {
    _onImageSearch(_filesFilter, currentDetailId);
  }
  const n = _filesFilter.toLowerCase();
  document.querySelectorAll('#detail-tab-logs tr[data-fname]').forEach(r => {
    r.classList.toggle('filter-hidden', !!n && !r.dataset.fname.toLowerCase().includes(n));
  });
  if (currentDetailId) filterArtifacts(currentDetailId, _filesFilter);
}

// ── Code tab: Changes and Env ───────────────────────────────────────────────

// Every diff a run has, in one fixed place, each with its buttons or the
// reason it is missing: since the previous run of this script, and the
// uncommitted working tree against its commit. Sections never just vanish —
// that made the buttons look like they came and went at random.
function _codeChangesHtml(exp, codeHtml, prevId) {
  const script = esc(String(exp.script || '').split(/[\\/]/).pop() || 'this script');
  const prev = prevId
    ? _wcCodeBlockHtml(prevId, exp.id)
    : '<p class="muted-note">No earlier run of ' + script + ' to compare against.'
      + (_isNotebookRun(exp) ? ' A notebook run\'s cells, in order, are under Timeline.' : '') + '</p>';
  // No commit means nothing was compared — "matched" would be a false all-clear.
  const tree = codeHtml || ('<h2 class="cc-head">Uncommitted changes</h2><p class="muted-note">'
    + (exp.git_commit ? 'None — the run matched its commit, ' + esc(String(exp.git_commit).slice(0, 7)) + '.'
                      : 'Not in a git repository, so there is no working-tree diff.') + '</p>');
  // With a previous run the arrow header names the section itself.
  return (prevId ? '' : '<h2 class="cc-head">Since the previous run</h2>') + prev + tree;
}

// Where and with what the run ran. Host and Python moved here from Overview.
function _codeEnvHtml(exp, varHtml, datasetsHtml) {
  const extra = (datasetsHtml || '') + (varHtml || '');
  return '<div class="info-grid"><span class="label">Host</span><span>' + esc(exp.hostname || '--') + '</span>'
    + '<span class="label">Python</span><span>' + esc(exp.python_ver || '--') + '</span></div>'
    + (extra || '<p class="muted-note">No variables, datasets or environment details were captured.</p>');
}
