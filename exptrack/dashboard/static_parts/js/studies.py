"""Study management UI."""

JS_STUDIES = r"""
// ── Study management ─────────────────────────────────────────────────────────

async function deleteStudyGlobal(name) {
  const count = allExperiments.filter(e => (e.studies||[]).includes(name)).length;
  if (!confirm('Delete study "' + name + '" from ' + count + ' experiment(s)? This cannot be undone.')) return;
  const res = await postApi('/api/studies/delete', {name});
  if (res.ok) {
    if (studyFilter === name) studyFilter = '';
    await loadAllStudies();
    await loadExperiments();
    renderManagePanel();
  }
}

async function createStudyFromPanel() {
  const input = document.getElementById('new-study-name');
  const name = input ? input.value.trim() : '';
  if (!name) return;
  const ids = [...selectedIds];
  if (ids.length > 0) {
    const res = await postApi('/api/studies/create', {name, experiment_ids: ids});
    if (res.ok) owlSay('Study "' + name + '" created with ' + ids.length + ' experiment(s)!');
  } else {
    owlSay('Select experiments first, then create a study.');
    return;
  }
  if (input) input.value = '';
  await loadAllStudies();
  await loadExperiments();
  renderManagePanel();
}

async function promptBulkAddToStudy() {
  const name = prompt('Study name to add ' + selectedIds.size + ' experiment(s) to:');
  if (!name || !name.trim()) return;
  const res = await postApi('/api/bulk-add-to-study', {study: name.trim(), ids: [...selectedIds]});
  if (res.ok) {
    await loadAllStudies();
    await loadExperiments();
    owlSay('Added ' + res.added + ' to "' + name.trim() + '"');
  } else {
    alert(res.error || 'Failed');
  }
}

async function deleteStudyInline(id, study) {
  const exp = allExperiments.find(e => e.id === id);
  if (exp) exp.studies = (exp.studies||[]).filter(s => s !== study);
  const area = document.getElementById('detail-studies-area');
  if (area) {
    area.querySelectorAll('.tag-removable').forEach(el => {
      if (el.textContent.trim().replace(/\u00d7$/, '').trim() === study) el.remove();
    });
  }
  const d = await postApi('/api/experiment/' + id + '/delete-study', {study});
  if (d.ok) { loadAllStudies(); loadExperiments().then(() => { if (currentDetailId === id) refreshDetail(id); }); }
}
"""

# Stage inline editing
