"""Stage/pipeline state tracking."""

JS_STAGE = r"""
// ── Stage inline editing ─────────────────────────────────────────────────────

function startInlineStage(id, td) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const curStage = exp.stage != null ? exp.stage : '';
  const curName = exp.stage_name || '';
  td.style.overflow = 'visible';
  td.innerHTML = '<div style="display:flex;gap:4px;align-items:center;white-space:nowrap" onclick="event.stopPropagation()">'
    + '<input type="number" class="inline-edit-input" style="width:50px;font-size:13px;padding:4px 6px" placeholder="#" value="' + esc(String(curStage)) + '" id="stage-num-' + id + '">'
    + '<input type="text" class="inline-edit-input" style="width:70px;font-size:13px;padding:4px 6px" placeholder="label" value="' + esc(curName) + '" id="stage-name-' + id + '">'
    + '<button style="font-size:12px;padding:3px 8px;cursor:pointer;border:1px solid var(--border);border-radius:3px;background:var(--code-bg)" onclick="saveInlineStage(\'' + id + '\')">&#10003;</button>'
    + '</div>';
  const numInput = document.getElementById('stage-num-' + id);
  if (numInput) { numInput.focus(); numInput.select(); }
  numInput.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveInlineStage(id);
    if (ev.key === 'Escape') { renderExperiments(); }
  });
  const nameInput = document.getElementById('stage-name-' + id);
  nameInput.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveInlineStage(id);
    if (ev.key === 'Escape') { renderExperiments(); }
  });
}

async function saveInlineStage(id) {
  const numInput = document.getElementById('stage-num-' + id);
  const nameInput = document.getElementById('stage-name-' + id);
  const stageVal = numInput ? numInput.value.trim() : '';
  const nameVal = nameInput ? nameInput.value.trim() : '';
  const body = {};
  if (stageVal !== '') body.stage = parseInt(stageVal, 10);
  else body.stage = null;
  if (nameVal) body.stage_name = nameVal;
  const res = await postApi('/api/experiment/' + id + '/stage', body);
  if (res.ok) {
    const exp = allExperiments.find(e => e.id === id);
    if (exp) { exp.stage = body.stage; exp.stage_name = nameVal; }
    renderExperiments();
    if (currentDetailId === id) refreshDetail(id);
  }
}

function startDetailStageEdit(id, el) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const curStage = exp.stage != null ? exp.stage : '';
  const curName = exp.stage_name || '';
  el.innerHTML = '<div style="display:inline-flex;gap:4px;align-items:center">'
    + '<input type="number" class="inline-edit-input" style="width:70px;font-size:13px;padding:4px 6px" placeholder="stage #" value="' + esc(String(curStage)) + '" id="detail-stage-num">'
    + '<input type="text" class="inline-edit-input" style="width:130px;font-size:13px;padding:4px 6px" placeholder="label (optional)" value="' + esc(curName) + '" id="detail-stage-name">'
    + '<button style="font-size:12px;padding:2px 8px;cursor:pointer" onclick="saveDetailStage(\'' + id + '\')">Save</button>'
    + '<button style="font-size:12px;padding:2px 8px;cursor:pointer" onclick="refreshDetail(\'' + id + '\')">Cancel</button>'
    + '</div>';
  const numInput = document.getElementById('detail-stage-num');
  if (numInput) { numInput.focus(); numInput.select(); }
  numInput.addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveDetailStage(id);
    if (ev.key === 'Escape') refreshDetail(id);
  });
  document.getElementById('detail-stage-name').addEventListener('keydown', function(ev) {
    if (ev.key === 'Enter') saveDetailStage(id);
    if (ev.key === 'Escape') refreshDetail(id);
  });
}

async function saveDetailStage(id) {
  const numInput = document.getElementById('detail-stage-num');
  const nameInput = document.getElementById('detail-stage-name');
  const stageVal = numInput ? numInput.value.trim() : '';
  const nameVal = nameInput ? nameInput.value.trim() : '';
  const body = {};
  if (stageVal !== '') body.stage = parseInt(stageVal, 10);
  else body.stage = null;
  if (nameVal) body.stage_name = nameVal;
  const res = await postApi('/api/experiment/' + id + '/stage', body);
  if (res.ok) {
    const exp = allExperiments.find(e => e.id === id);
    if (exp) { exp.stage = body.stage; exp.stage_name = nameVal; }
    renderExperiments();
    refreshDetail(id);
  }
}
"""

# ── Script / Command inline editing + Manual experiment creation ──────────────
