"""Page initialization and event binding."""

JS_INIT = r"""

// Init — sidebar starts collapsed (opens when entering detail view)
document.getElementById('exp-sidebar').classList.add('collapsed');
syncHighlightCheckbox();
loadTimezoneConfig();
renderTableHeader();
loadAllTags();
loadAllStudies();
loadResultTypes();
loadStats();
loadExperiments().then(() => {
  if (highlightMode) { buildHighlightColors(); renderHighlightLegend(); }
  // owl only speaks when clicked, not on page load
});
"""

# Study management UI — column-based studies with inline editing
