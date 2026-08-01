

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
  loadTimezoneConfig();
  loadMetricSettings();
  loadCaptureSettings();
  loadAllTags();
  loadAllStudies();
  loadResultTypes();
  loadStats();
  loadExperiments().then(() => {
    if (highlightMode) { buildHighlightColors(); renderHighlightLegend(); }
  });
  if (_toolboxPinned) _syncToolboxUI();
}

// Gate data-loading on auth so we don't fire ~8 requests that all 401 at once
// and leave downstream renderers reading {} responses.
ensureAuth().then(ok => { if (ok) _bootDashboard(); });
