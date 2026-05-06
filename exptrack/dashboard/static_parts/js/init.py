"""Page initialization and event binding."""

JS_INIT = r"""

// Init — sidebar starts collapsed (opens when entering detail view)
document.getElementById('exp-sidebar').classList.add('collapsed');
syncHighlightCheckbox();
renderTableHeader();

function _bootDashboard() {
  loadTimezoneConfig();
  loadMetricSettings();
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
"""

# Study management UI — column-based studies with inline editing
