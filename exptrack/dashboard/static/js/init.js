

// Init — sidebar starts collapsed unless the user left it open (it also opens
// when entering the detail view).
restoreSidebarState();
syncHighlightCheckbox();
syncFilterControls();
renderTableHeader();

// Filmstrip keyboard nav: ←/→ step through runs while the detail view is open.
// Ignored while typing in a field so it never fights inline editing/search.
document.addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
  // A modal or a pinned side panel is its own focus context — stepping the run
  // behind it (re-rendering the panel under an open confirm dialog) is never
  // what an arrow key means there.
  if (document.querySelector('.dc-overlay, .img-modal-overlay, #exptrack-login-overlay')) return;
  const cmpEl = document.getElementById('compare-view');
  if (cmpEl && cmpEl.style.display !== 'none') return;
  const detailEl = document.getElementById('detail-view');
  const detailVisible = detailEl && detailEl.style.display !== 'none' &&
    !document.body.classList.contains('sessions-active') &&
    !document.body.classList.contains('trash-active');
  if (!detailVisible || !currentDetailId) return;
  // Only when the page itself (or something inside the detail view) has focus —
  // not while the user is working in a pinned Todos/Commands panel.
  const active = document.activeElement;
  if (active && active !== document.body && !detailEl.contains(active)) return;
  e.preventDefault();
  filmstripStep(e.key === 'ArrowLeft' ? -1 : 1);
});

function _bootDashboard() {
  // `loadProjects()` is the only load exempt from project activation, so it is
  // the only one that survives a stored project id the server no longer knows
  // — and the only one that can recover it. Every other load carries that id
  // and 400s. The auth probe already asked the server whether the id resolves
  // (`_pingProjectState`), so when it does not, the loads wait for the
  // recovery instead of all failing first: firing them anyway left an empty
  // table under a "Couldn't load data … 400" banner for as long as the first,
  // uncached /api/projects took. The healthy case stays parallel.
  if (_activeProjectId && _pingProjectState && _pingProjectState !== 'ok') {
    loadProjects().then(() => _bootProjectData());
  } else {
    // A probe that said nothing (an older server, the login overlay's path)
    // keeps the old safety net: re-run the loads against a recovered id.
    loadProjects().then(res => { if (res && res.recovered) _bootProjectData(); });
    _bootProjectData();
  }
  if (_toolboxPinned) _syncToolboxUI();
}

function _bootProjectData() {
  loadTimezoneConfig();
  loadMetricSettings();
  loadCaptureSettings();
  loadAllTags();
  loadAllStudies();
  loadResultTypes();
  loadStats();
  loadExperiments().then(() => {
    if (highlightMode) { buildHighlightColors(); renderHighlightLegend(); }
    // The address names the view a reload or a shared link should reopen — a
    // comparison, the matrix or a run. Runs after the list so the pickers
    // have their cache; the compare view injects any id the cache doesn't
    // hold, so an old run in a shared link still opens.
    _restoreViewFromHash();
  });
}

// Gate data-loading on auth so we don't fire ~8 requests that all 401 at once
// and leave downstream renderers reading {} responses.
ensureAuth().then(ok => { if (ok) _bootDashboard(); });
