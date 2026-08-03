
// ── Stage inline editing ─────────────────────────────────────────────────────

function startInlineStage(id, td) {
  closeOpenCellEditor();
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  const curStage = exp.stage != null ? exp.stage : '';
  const curName = exp.stage_name || '';
  td.removeAttribute('title');   // the "Double-click to edit" hint is stale once open
  // `.cell-edit-pop` floats the editor clear of the Stage column, which is
  // narrower than these two inputs plus the ✓ ever fit — the old in-flow editor
  // overflowed onto whatever cell came next.
  td.innerHTML = '<div class="cell-edit-pop" onclick="event.stopPropagation()">'
    + '<input type="number" class="inline-edit-input" style="width:46px;box-sizing:border-box;font-size:13px;padding:4px 6px" placeholder="#" value="' + esc(String(curStage)) + '" id="stage-num-' + id + '">'
    + '<input type="text" class="inline-edit-input" style="flex:1 1 60px;min-width:0;box-sizing:border-box;font-size:13px;padding:4px 6px" placeholder="label" value="' + esc(curName) + '" id="stage-name-' + id + '">'
    + '<button style="font-size:12px;padding:3px 8px;cursor:pointer;border:1px solid var(--border);border-radius:3px;background:var(--code-bg)" onclick="closeOpenCellEditor()">&#10003;</button>'
    + '</div>';
  const numInput = document.getElementById('stage-num-' + id);
  if (numInput) { numInput.focus(); numInput.select(); }
  // ✓ and Enter both go through closeOpenCellEditor, so saving and being
  // closed by another editor take one path — the token that identifies this
  // editor stays in this closure and can't be mixed up with a later editor on
  // the same cell.
  let editToken = 0;
  const onKey = function(ev) {
    if (ev.key === 'Enter') closeOpenCellEditor();
    if (ev.key === 'Escape') _afterInlineEdit(editToken);
  };
  numInput.addEventListener('keydown', onKey);
  const nameInput = document.getElementById('stage-name-' + id);
  nameInput.addEventListener('keydown', onKey);
  editToken = _registerCellEdit(td, () => saveInlineStage(id, editToken));
}

async function saveInlineStage(id, editToken) {
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
    _afterInlineEdit(editToken);
    if (currentDetailId === id) refreshDetail(id);
  }
}

function startDetailStageEdit(id, el) {
  const exp = allExperiments.find(e => e.id === id);
  if (!exp) return;
  // Opens on a single click, so drop the handler while the editor is up — a
  // click on its own inputs bubbles back here and would rebuild it under the
  // cursor. refreshDetail restores the span, handler and all.
  el.onclick = null;
  el.removeAttribute('onclick');
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
