

// Init — sidebar starts collapsed (opens when entering detail view)
document.getElementById('exp-sidebar').classList.add('collapsed');
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
  const detailEl = document.getElementById('detail-view');
  const detailVisible = detailEl && detailEl.style.display !== 'none' &&
    !document.body.classList.contains('sessions-active') &&
    !document.body.classList.contains('trash-active');
  if (!detailVisible || !currentDetailId) return;
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
