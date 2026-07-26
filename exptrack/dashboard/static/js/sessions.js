
// ── Session Trees ──────────────────────────────────────────────────────────

let _sessionsCache = [];
let _activeSessionId = null;
let _selectedNodeId = null;
let _treeCache = {};  // sessionId -> last-fetched tree (avoid re-fetch per click)
let _lastSessionsLoad = 0;
let _compareMode = false;          // when on, clicking nodes toggles compare set
let _compareNodes = [];            // ordered list of node ids chosen to compare

// Branch-graph rendering: lane palette (lane 0 / trunk uses --accent), max lanes
// before clamping, and a per-session collapsed-subtree set persisted to
// localStorage so big sessions stay scannable across reloads.
const _MAX_LANES = 6;
function _collapseKey(sid) { return 'exptrack-tree-collapsed:' + sid; }
function _getCollapsed(sid) {
  try { return new Set(JSON.parse(localStorage.getItem(_collapseKey(sid)) || '[]')); }
  catch (e) { return new Set(); }
}
function _setCollapsed(sid, set) {
  try { localStorage.setItem(_collapseKey(sid), JSON.stringify([...set])); } catch (e) {}
}
function toggleNodeCollapse(nodeId) {
  if (!_activeSessionId) return;
  const set = _getCollapsed(_activeSessionId);
  if (set.has(nodeId)) set.delete(nodeId); else set.add(nodeId);
  _setCollapsed(_activeSessionId, set);
  _rerenderTreeContainer();
}
// Lane color is bounded and state-based — NOT per-branch. Lane position already
// tells branches apart (a tree's lanes never merge), so color only says what KIND
// of line this is: neutral spine, one teal for every branch, amber for abandoned.
// This is what keeps the palette from growing with the number of branches.
function _laneClass(nodeType, lane) {
  if ((nodeType || '') === 'abandoned') return 'tc-ab';
  if (lane === 0) return 'tc-spine';
  return 'tc-branch';
}

function toggleSessionsTab() {
  // If already active, refresh instead of closing — closing is rarely what the
  // user wants and a stale list is the most common reason they re-click.
  const wasActive = document.body.classList.contains('sessions-active');
  if (wasActive) {
    loadSessionsList();
    return;
  }
  document.body.classList.add('sessions-active');
  const tab = document.getElementById('sessions-tab');
  const welcome = document.getElementById('welcome-state');
  const detail = document.getElementById('detail-view');
  const compare = document.getElementById('compare-view');
  if (tab) tab.style.display = 'flex';
  if (welcome) welcome.style.display = 'none';
  if (detail) detail.style.display = 'none';
  if (compare) compare.style.display = 'none';
  loadSessionsList();
}

function closeSessionsTab() {
  document.body.classList.remove('sessions-active');
  const tab = document.getElementById('sessions-tab');
  const welcome = document.getElementById('welcome-state');
  if (tab) tab.style.display = 'none';
  if (welcome) welcome.style.display = '';
}

// Auto-refresh the sessions list when the dashboard tab regains focus
// (the most common moment a session was just created in the notebook).
if (typeof window !== 'undefined' && !window._sessionsFocusBound) {
  window._sessionsFocusBound = true;
  // Both focus and visibilitychange can fire on tab switches; debounce so the
  // pair doesn't trigger two HTTP calls back-to-back.
  const _maybeReload = () => {
    if (!document.body.classList.contains('sessions-active')) return;
    if (Date.now() - _lastSessionsLoad < 500) return;
    loadSessionsList();
  };
  window.addEventListener('focus', _maybeReload);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') _maybeReload();
  });
}

async function loadSessionsList() {
  _lastSessionsLoad = Date.now();
  _treeCache = {};  // explicit refresh always re-fetches the tree
  const root = document.getElementById('sessions-list-items');
  if (root) root.classList.add('refreshing');
  const data = await api('/api/sessions');
  _sessionsCache = (data && data.sessions) || [];
  renderSessionsList();
  // Stamp the header so the user can see the refresh actually ran
  const stamp = document.getElementById('sessions-updated-stamp');
  if (stamp) {
    const now = new Date();
    const t = now.toTimeString().slice(0, 8);
    stamp.textContent = 'updated ' + t;
  }
  if (root) {
    setTimeout(() => root.classList.remove('refreshing'), 300);
  }
  if (_sessionsCache.length && !_activeSessionId) {
    selectSession(_sessionsCache[0].id);
  } else if (_activeSessionId) {
    renderSessionTree(_activeSessionId);
  }
}

function renderSessionsList() {
  const root = document.getElementById('sessions-list-items');
  if (!root) return;
  if (!_sessionsCache.length) {
    root.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">No sessions yet.</div>';
    return;
  }
  const html = _sessionsCache.map(s => {
    const cls = (s.id === _activeSessionId) ? 'session-card active' : 'session-card';
    const status = s.status || 'active';
    const rel = s.created_at ? fmtTimeAgo(s.created_at * 1000) : '';
    const cps = s.checkpoints || 0;
    const promoted = s.promoted || 0;
    const promotedStr = promoted ? ` · ${promoted} exp` : '';
    return `<div class="${cls}" onclick="selectSession('${s.id}')">
      <div class="session-card-header">
        <div class="name">${escapeHtml(s.name || '(unnamed)')}</div>
        <span class="pill pill-${status}">${status}</span>
        <button class="session-delete-btn" title="Delete session"
          onclick="event.stopPropagation();deleteSession('${s.id}','${escJsAttr(s.name||'')}')">&times;</button>
      </div>
      <div class="session-card-sub">
        <span class="sc-notebook" title="${escapeHtml(s.notebook || '')}">${escapeHtml(s.notebook || '(no notebook)')}</span>
        <span class="sc-meta-tail">${cps} checkpoint${cps===1?'':'s'}${promotedStr}${rel ? ' · ' + rel : ''}</span>
      </div>
    </div>`;
  }).join('');
  root.innerHTML = html;
}


async function deleteSession(id, name) {
  if (!confirm(`Move session "${name || id}" to the Trash?\n\n` +
      `It stays recoverable from Settings → 🗑 Open Trash. Linked experiments ` +
      `are preserved.`)) return;
  const r = await postApi('/api/session/' + id + '/delete', {});
  if (r && r.ok) {
    if (_activeSessionId === id) {
      _activeSessionId = null;
      _selectedNodeId = null;
      const view = document.getElementById('session-tree-view');
      if (view) view.innerHTML = '';
    }
    loadSessionsList();
  } else {
    alert('Could not delete session: ' + ((r && r.error) || 'unknown error'));
  }
}

// ── Finalize a session ───────────────────────────────────────────────────────
// Open an interactive modal: list the session's nodes (already-promoted vs not),
// let the user pick which un-promoted nodes to materialize into standalone
// experiments, choose the study name, and whether to move the session to Trash
// afterwards. POSTs /api/session/<id>/finalize.
async function openFinalizeSession(id, name) {
  const data = await api('/api/session/' + id + '/finalize-preview');
  if (!data || data.error) {
    alert('Could not load session: ' + ((data && data.error) || 'unknown error'));
    return;
  }
  const study = data.study || name || '';
  const rows = (data.nodes || []).map(n => {
    const label = escapeHtml(n.label || '(unlabeled)');
    const lin = (n.lineage || []).join(' › ');
    const meta = `${escapeHtml(n.node_type)}${n.cell_count ? ' · ' + n.cell_count + ' cell' + (n.cell_count===1?'':'s') : ''}` +
                 (lin ? ' · <span class="fz-lineage">' + escapeHtml(lin) + '</span>' : '');
    if (n.linked_exp) {
      return `<label class="fz-row fz-linked">
        <input type="checkbox" disabled checked>
        <span class="fz-main"><span class="fz-label">${label}</span>
          <span class="fz-meta">${meta}</span></span>
        <span class="fz-badge fz-badge-done">→ exp ${escapeHtml(n.linked_exp.slice(0,8))}</span>
      </label>`;
    }
    const disabled = n.cell_count ? '' : 'disabled';
    const checked = n.recommended ? 'checked' : '';
    const note = n.cell_count ? 'materialize → experiment'
                              : 'marker only — its branches carry the code';
    return `<label class="fz-row">
      <input type="checkbox" class="fz-node" value="${n.id}" ${checked} ${disabled}>
      <span class="fz-main"><span class="fz-label">${label}</span>
        <span class="fz-meta">${meta}</span></span>
      <span class="fz-badge">${note}</span>
    </label>`;
  }).join('');

  const overlay = document.createElement('div');
  overlay.className = 'dc-overlay';
  overlay.id = 'dc-overlay';
  overlay.addEventListener('click', (ev) => { if (ev.target === overlay) _closeDeleteModal(); });
  overlay.innerHTML =
    '<div class="dc-dialog fz-dialog">' +
      '<div class="dc-header">' +
        '<h3>Finalize session: ' + escapeHtml(name || '') + '</h3>' +
        '<button class="dc-close" onclick="_closeDeleteModal()">&times;</button>' +
      '</div>' +
      '<div class="dc-body">' +
        '<p class="fz-intro">Graduate this session into self-contained ' +
          'experiments. Each selected node becomes a standalone run carrying ' +
          'its <b>own code plus the setup code from its parent checkpoints</b> ' +
          '(imports, data prep, helper defs) &amp; plots — so the run is ' +
          'complete and re-runnable on its own. Every run is grouped under a ' +
          'study so it stays together after the session is gone.</p>' +
        '<div class="fz-study-row"><label>Study name ' +
          '<input type="text" id="fz-study" value="' + escapeHtml(study) + '"></label></div>' +
        '<div class="fz-nodes">' + (rows || '<div class="fz-empty">No nodes to graduate.</div>') + '</div>' +
      '</div>' +
      '<div class="dc-footer">' +
        '<div class="dc-footer-left">' +
          '<label class="dc-files-checkbox"><input type="checkbox" id="fz-softdel" checked>' +
            '<span class="dc-files-checkbox-label">Move session to Trash after finalizing' +
              '<span class="dc-files-checkbox-hint">recoverable from the unified Trash</span>' +
            '</span></label>' +
        '</div>' +
        '<div class="dc-footer-right">' +
          '<button class="dc-button" onclick="_closeDeleteModal()">Cancel</button>' +
          '<button class="dc-button primary" onclick="confirmFinalizeSession(\'' + id + '\')">✓ Finalize</button>' +
        '</div>' +
      '</div>' +
    '</div>';
  document.body.appendChild(overlay);
}

async function confirmFinalizeSession(id) {
  const studyEl = document.getElementById('fz-study');
  const softEl = document.getElementById('fz-softdel');
  const study = studyEl ? studyEl.value.trim() : '';
  const node_ids = Array.from(document.querySelectorAll('.fz-node:checked'))
    .map(el => el.value);
  const r = await postApi('/api/session/' + id + '/finalize', {
    node_ids, study, soft_delete: softEl ? softEl.checked : true,
  });
  _closeDeleteModal();
  if (r && r.ok) {
    const made = (r.materialized || []).length;
    owlSay(`Finalized: ${made} experiment${made===1?'':'s'} created, ` +
          `${r.grouped} grouped under "${r.study}"` +
          (r.deleted ? ' · session moved to Trash' : ''));
    if (r.deleted && _activeSessionId === id) {
      _activeSessionId = null;
      _selectedNodeId = null;
      const view = document.getElementById('session-tree-view');
      if (view) view.innerHTML = '';
    } else if (_activeSessionId === id) {
      renderSessionTree(id);
    }
    loadSessionsList();
    if (typeof loadExperiments === 'function') loadExperiments();
  } else {
    alert('Could not finalize: ' + ((r && r.error) || 'unknown error'));
  }
}

function selectSession(id) {
  _activeSessionId = id;
  _selectedNodeId = null;
  // Reset compare selection — node ids don't carry across sessions.
  _compareMode = false;
  _compareNodes = [];
  document.body.classList.remove('session-compare-mode');
  renderSessionsList();
  renderSessionTree(id);
}

// Open the Sessions tab focused on a specific session + node. Used by the
// experiment detail view's "From session" back-link so exp → tree navigation
// works (the link only existed tree → exp before).
async function openSessionNode(sessionId, nodeId) {
  if (!document.body.classList.contains('sessions-active')) toggleSessionsTab();
  _activeSessionId = sessionId;
  _selectedNodeId = null;
  _compareMode = false;
  _compareNodes = [];
  document.body.classList.remove('session-compare-mode');
  renderSessionsList();
  await renderSessionTree(sessionId);
  if (nodeId) selectNode(nodeId);
}

async function renderSessionTree(sid) {
  const view = document.getElementById('session-tree-view');
  if (!view) return;
  view.innerHTML = '<div style="color:var(--muted);padding:12px">Loading...</div>';
  const data = await api('/api/session/' + sid);
  if (!data || data.error) {
    view.innerHTML = '<div style="color:var(--muted);padding:12px">' +
      escapeHtml((data && data.error) || 'Could not load session') + '</div>';
    return;
  }
  _treeCache[sid] = data;
  const s = data.session || {};
  const root = data.root || null;
  const oc = s.outcomes || {};
  const ocExps = oc.experiments || [];
  const ocCountBits = [];
  if (oc.checkpoints) ocCountBits.push(`${oc.checkpoints} checkpoint${oc.checkpoints===1?'':'s'}`);
  if (oc.branches) ocCountBits.push(`${oc.branches} branch${oc.branches===1?'':'es'}`);
  if (oc.abandoned) ocCountBits.push(`${oc.abandoned} abandoned`);
  const ocExpChips = ocExps.length
    ? ocExps.map(e => `<a href="#" class="outcome-chip status-${escapeHtml(e.status || '')}" title="${escapeHtml(e.status || '')}" onclick="showDetail('${e.id}');return false">${escapeHtml(truncate(e.name || e.id, 36))}</a>`).join('')
    : '';
  const outcomeHtml = (ocExps.length || ocCountBits.length)
    ? `<div class="session-outcomes">
         <span class="section-title">Produced</span>
         ${ocExps.length ? `<span class="outcome-chips">${ocExpChips}</span>` : '<span class="outcome-none">no experiments yet</span>'}
         ${ocCountBits.length ? `<span class="outcome-counts">${ocCountBits.join(' · ')}</span>` : ''}
       </div>`
    : '';
  // A trashed session is still reachable (an experiment's back-link opens it,
  // and inspecting one before restoring is legitimate) but it is not live:
  // finalizing or ending it would mutate something the sessions list doesn't
  // show. So it gets a tag, Restore in place of Finalize, and no End button.
  const trashTag = s.session_deleted
    ? ' <span class="session-trashed-tag" title="This session is in the Trash — restore it to bring it back to the sessions list">in Trash</span>'
    : '';
  const primaryBtn = s.session_deleted
    ? `<button class="session-restore-btn" onclick="restoreSession('${escJsAttr(s.id)}')"
         title="Restore this session — it reappears in the sessions list">↺ Restore session</button>`
    : `<button class="session-finalize-btn" onclick="openFinalizeSession('${escJsAttr(s.id)}','${escJsAttr(s.name || '')}')"
         title="Graduate this session: turn un-promoted nodes into experiments, group them under a study, then move the session to Trash">✓ Finalize</button>`;
  const endBtn = s.session_deleted ? ''
    : (s.status || 'active') === 'active'
    ? `<button class="session-end-btn" onclick="endSession()"
         title="End this session — open branches are marked abandoned">⏹ End session</button>`
    : '<span class="session-ended-tag" title="This session has been ended">session ended</span>';
  const headerHtml = `
    <div class="session-view-header" style="margin-bottom:12px">
      <h2 style="margin:0 0 4px 0">${escapeHtml(s.name || '')}${trashTag}</h2>
      <div style="color:var(--muted);font-size:12px">
        ${escapeHtml(s.notebook || '(no notebook)')}
        ${s.git_branch ? '· branch ' + escapeHtml(s.git_branch) : ''}
        ${s.git_commit ? '· ' + escapeHtml(s.git_commit) : ''}
        ${s.status ? '· ' + escapeHtml(s.status) : ''}
      </div>
      ${outcomeHtml}
      <div class="session-view-actions">
        <button class="session-compare-toggle" id="session-compare-toggle" onclick="toggleCompareMode()">
          ⇄ Compare branches
        </button>
        ${primaryBtn}
        <button class="session-trash-toggle" onclick="openTrashView()"
          title="Trashed nodes now live in the unified Trash (with trashed experiments)">
          🗑 Trash<span id="session-trash-count"></span>
        </button>
        ${endBtn}
      </div>
    </div>`;
  const treeHtml = renderTreeRows(root);
  view.innerHTML = headerHtml +
    '<div id="session-compare-bar" style="display:none"></div>' +
    '<div id="session-tree-container">' + treeHtml + '</div>' +
    '<div id="session-compare" style="display:none"></div>' +
    '<div id="session-detail"></div>';
  document.body.classList.toggle('session-compare-mode', _compareMode);
  // Refresh the count chip in the background — doesn't block tree render.
  _refreshTrashCount();
}

async function _refreshTrashCount() {
  if (!_activeSessionId) return;
  const data = await api('/api/session/' + _activeSessionId + '/trash');
  const n = (data && data.nodes && data.nodes.length) || 0;
  const chip = document.getElementById('session-trash-count');
  if (chip) chip.textContent = n ? ' (' + n + ')' : '';
}

// Trashed session nodes now live in the unified Trash view (alongside trashed
// experiments) — see js/trash.py. The session header's 🗑 Trash button opens
// it via openTrashView(); restore / delete-forever / empty happen there. The
// per-session #session-trash-count chip is still kept current by
// _refreshTrashCount() above (reads /api/session/<sid>/trash).

// ── Branch graph (git-graph lane rail) ──────────────────────────────────────

// Flatten the nested tree into ordered rows with lane assignment. Pre-order DFS
// over seq-ordered children: the first child inherits the parent's lane (the
// trunk continues straight); each later child forks into a freshly allocated,
// color-keyed lane. Colors are keyed to the branch's root node id (not the lane
// number) so a branch keeps its color across re-renders even if lanes shift.
function computeTreeLayout(root, collapsed) {
  collapsed = collapsed || new Set();
  const rows = [];
  let maxLane = 0, nextLane = 1;   // lane 0 reserved for the checkpoint spine
  function visit(node, lane, colorClass, parentRowIdx) {
    const kids = node.children || [];
    const rowIdx = rows.length;
    const isCollapsed = collapsed.has(node.id) && kids.length > 0;
    const row = {
      node, lane, colorClass,
      isDivergence: kids.length > 1, hasChildren: kids.length > 0,
      collapsed: isCollapsed,
      hiddenCount: isCollapsed ? _countDescendants(node) : 0,
      rowIdx, parentRowIdx,
      forkChildren: [], hasSpineChild: false,
    };
    rows.push(row);
    if (lane > maxLane) maxLane = lane;
    if (isCollapsed) return;
    // The spine (the parent's lane) is the checkpoint chain: exactly one child
    // continues it — the first checkpoint/root child (`spineIdx`). Every branch
    // (and abandoned dead-end) forks into its OWN lane that descends straight
    // from this node's dot, so two experiments tried from the same checkpoint
    // read as equal siblings rather than a main-line + offshoot. (Promoting a
    // branch to a checkpoint makes it rejoin the spine on the next render.)
    const spineIdx = kids.findIndex(c => {
      const ct = c.node_type || '';
      return ct === 'checkpoint' || ct === 'root';
    });
    row.hasSpineChild = spineIdx >= 0;
    kids.forEach((ch, i) => {
      let cl, cc;
      if (i === spineIdx) { cl = lane; cc = _laneClass(ch.node_type, lane); }
      else { cl = Math.min(nextLane++, _MAX_LANES); cc = _laneClass(ch.node_type, cl);
             row.forkChildren.push({lane: cl, cls: cc}); }
      visit(ch, cl, cc, rowIdx);
    });
  }
  if (root) visit(root, 0, 'tc-spine', -1);
  return { rows, maxLane };
}

function _countDescendants(node) {
  let n = 0;
  for (const ch of (node.children || [])) n += 1 + _countDescendants(ch);
  return n;
}

const _LANE_W = 18;
const _TITLE_Y = 16;   // px from the row top to the node's title line — the dot
                       // and every line junction anchor here, so the dot stays on
                       // its own title no matter how tall the row grows.
const _FORK_H = 20;    // px of the fixed-height elbow that jogs a fork from the
                       // parent lane to the child lane. Bounded, so a fork curve
                       // can never run long or overshoot regardless of row height.
function _laneX(lane) { return lane * _LANE_W + _LANE_W / 2; }

// Per-row rail. EVERY vertical is a pixel-anchored CSS div, so junctions land at
// an exact px offset (the title line) instead of a percentage of a stretched,
// variable-height row. A fork is a small fixed-height elbow (one tiny SVG) right
// under the parent dot, then the child lane is a straight vertical the rest of
// the way down — through the parent row, any rows between, and into the child.
// Result: no long curves, no line overshooting past its own dot.
function _railHtml(row, layout, edges) {
  const railW = (layout.maxLane + 1) * _LANE_W;
  const ri = row.rowIdx;
  const ox = _laneX(row.lane);
  const ocls = row.colorClass || 'tc-spine';
  const parts = [];
  const vline = (x, cls, top, extra) =>
    parts.push(`<span class="rail-v ${cls||'tc-spine'}" style="left:${x}px;top:${top}px;${extra}"></span>`);
  // Pass-through verticals: any lane whose edge spans across this row (full
  // height, own branch color), skipping this node's own lane (handled below).
  for (const e of edges) {
    if (e.lane === row.lane) continue;
    if (e.fromRow < ri && e.toRow > ri) vline(_laneX(e.lane), e.cls, 0, 'bottom:0');
  }
  // Incoming: this node's lane runs from the top down to its dot (the title line).
  if (row.parentRowIdx >= 0) vline(ox, ocls, 0, `height:${_TITLE_Y}px`);
  // Continuation: only when a checkpoint/spine child keeps this lane going down.
  if (row.hasSpineChild && !row.collapsed) vline(ox, ocls, _TITLE_Y, 'bottom:0');
  // Forks: a bounded elbow from this dot into each child's lane, then a straight
  // vertical filling the rest of THIS (parent) row in the child's lane so the
  // line is continuous into the rows below (which carry it as pass-through).
  if (!row.collapsed && row.forkChildren.length) {
    for (const fc of row.forkChildren) {
      const cx = _laneX(fc.lane);
      const cls = fc.cls || 'tc-branch';
      parts.push(`<svg class="rail-fork ${cls}" style="top:${_TITLE_Y}px;height:${_FORK_H}px" `
        + `viewBox="0 0 ${railW} ${_FORK_H}" preserveAspectRatio="none" aria-hidden="true">`
        + `<path d="M ${ox} 0 C ${ox} ${_FORK_H*0.6}, ${cx} ${_FORK_H*0.4}, ${cx} ${_FORK_H}" `
        + `class="rail-line" fill="none"/></svg>`);
      vline(cx, cls, _TITLE_Y + _FORK_H, 'bottom:0');
    }
  }
  // Dot colored by node TYPE (CSS), not lane — a checkpoint is a neutral filled
  // dot even on a teal branch line. Anchored to the title line.
  const dotCls = 'rail-dot ' + (row.node.node_type || 'root') + (row.isDivergence ? ' diverge' : '');
  parts.push(`<span class="${dotCls}" style="left:${ox}px;top:${_TITLE_Y}px"></span>`);
  return `<div class="tree-rail" style="width:${railW}px">${parts.join('')}</div>`;
}

// Render the whole tree as a flat list of lane-rail rows.
function renderTreeRows(root) {
  if (!root) return '<div style="color:var(--muted)">(empty tree)</div>';
  const collapsed = _activeSessionId ? _getCollapsed(_activeSessionId) : new Set();
  const layout = computeTreeLayout(root, collapsed);
  // Parent→child edges drive the rail's vertical spans. Every edge lives in the
  // CHILD's lane (a branch keeps its own colored lane straight from its parent
  // dot), so a fork is never drawn as a stray line in the parent/spine lane.
  const edges = layout.rows.filter(r => r.parentRowIdx >= 0).map(r => ({
    fromRow: r.parentRowIdx, toRow: r.rowIdx, lane: r.lane, cls: r.colorClass,
  }));
  // Frontier = most recent live (non-root) node, for the "← latest" tag.
  let latestId = null, latestT = -1;
  for (const r of layout.rows) {
    const n = r.node;
    if ((n.node_type || 'root') !== 'root' && (n.created_at || 0) > latestT) {
      latestT = n.created_at || 0; latestId = n.id;
    }
  }
  const body = layout.rows.map(r => {
    const isRoot = (r.node.node_type || 'root') === 'root';
    return `<div class="tree-row ${r.node.node_type||'root'}${isRoot?' root':''}" data-node-id="${escapeHtml(r.node.id)}">
      ${_railHtml(r, layout, edges)}
      ${_renderNodeContent(r, isRoot, latestId)}
    </div>`;
  }).join('');
  return _treeLegendHtml() +
    `<div id="session-tree-graph" style="--max-lane:${layout.maxLane}">${body}</div>`;
}

// A compact key for the graph so the marks are self-explanatory: the dark spine
// is the checkpoint chain, each branch gets its own color so you can follow its
// lane, dot shape = node type, ⑂ marks a fork, ← latest = where you left off.
function _treeLegendHtml() {
  return `<div class="tree-legend">
    <span class="tl-k"><span class="tl-dot cp"></span> checkpoint — stable point</span>
    <span class="tl-k"><span class="tl-dot br"></span> branch — a tried direction</span>
    <span class="tl-k"><span class="tl-dot ab"></span> abandoned</span>
    <span class="tl-k">⑂ fork point</span>
    <span class="tl-k">← latest = where you left off</span>
    <span class="tl-k">⟨⟩ / ✎ = code</span>
    <span class="tl-k tl-note">dot shape = node type · line color = spine vs. branch</span>
  </div>`;
}

// Render one node's content cell (the clickable .node-row, identical wiring to
// before — selection/compare/promote/delete all key off data-node-id/onclick).
function _renderNodeContent(row, isRoot, latestId) {
  const node = row.node;
  const t = node.node_type || 'root';
  const time = node.created_at ? new Date(node.created_at * 1000).toLocaleTimeString() : '';
  const diffSummary = summarizeDiff(node.git_diff);
  const cellCount = _cellCount(node.cell_source);
  const expBadge = node.exp_id
    ? `<a class="node-exp-badge" href="#" onclick="event.stopPropagation();showDetail('${node.exp_id}');return false">→ exp ${escapeHtml(node.exp_id.slice(0,8))}</a>`
    : '';
  const abandonedPill = t === 'abandoned'
    ? '<span class="pill pill-abandoned">abandoned</span>' : '';
  const divergeBadge = row.isDivergence
    ? `<span class="tree-diverge-badge" title="${node.children.length} branches diverge from here">⑂ ${node.children.length}</span>` : '';
  const latestTag = node.id === latestId
    ? '<span class="node-latest-tag" title="Most recent activity — where you left off">← latest</span>' : '';
  const note = node.note ? `<div class="node-note-mini">${escapeHtml(truncate(node.note, 120))}</div>` : '';
  const _latest = _getLatestOutput(node);
  const resultMini = _latest
    ? `<div class="node-result-mini" title="${escapeHtml(_latest)}">⤷ ${escapeHtml(truncate(_latest.replace(/\s+/g, ' '), 100))}</div>`
    : '';
  const labelText = isRoot ? ('session start: ' + (node.label || '')) : (node.label || '(unlabeled)');
  const imgCount = _validImages(node).length;
  const setupCount = _cellCount(node.setup_source);
  const metaBits = [];
  if (time) metaBits.push(`<span class="nm-time">${time}</span>`);
  if (cellCount) metaBits.push(`<span class="nm-cells">${cellCount} cell${cellCount===1?'':'s'}</span>`);
  if (setupCount) metaBits.push(`<span class="nm-setup" title="${setupCount} %%setup prep cell${setupCount===1?'':'s'}">🛠 ${setupCount}</span>`);
  if (imgCount) metaBits.push(`<span class="nm-imgs" title="${imgCount} plot${imgCount===1?'':'s'}">🖼 ${imgCount}</span>`);
  if (diffSummary) metaBits.push(`<span class="nm-diff">${diffSummary}</span>`);
  const metaLine = metaBits.length
    ? `<div class="node-meta">${metaBits.join('<span class="nm-sep">·</span>')}</div>` : '';
  const isEmpty = !cellCount && !row.hasChildren && (t === 'branch' || t === 'checkpoint');
  const awaitingLine = isEmpty
    ? '<div class="node-awaiting">awaiting first cell…</div>' : '';
  // While comparing, suppress the single-select highlight so it can't be
  // mistaken for a pick — the only blue accent in compare mode is a pick.
  const pickIdx = _compareNodes.indexOf(node.id);
  const selectedCls = (!_compareMode && node.id === _selectedNodeId ? ' selected' : '')
    + (pickIdx >= 0 ? ' compare-picked' : '');
  const pickBadge = pickIdx >= 0
    ? `<span class="compare-pick-num">${pickIdx + 1}</span>` : '';
  const deleteBtn = isRoot ? '' :
    `<button class="node-delete-btn" title="Delete this node and all descendants"
       onclick="event.stopPropagation();confirmDeleteNode('${node.id}')">&times;</button>`;
  const promoteBtn = (t === 'branch' || t === 'abandoned')
    ? `<button class="node-promote-btn" title="Promote this branch to a checkpoint"
         onclick="event.stopPropagation();promoteBranch('${node.id}')">↑ checkpoint</button>`
    : '';
  // Always-available "add to comparison" pin — works without first toggling the
  // global Compare-branches mode (pinCompareNode enables it on demand).
  const compareBtn = isRoot ? '' :
    `<button class="node-compare-btn${pickIdx >= 0 ? ' picked' : ''}"
       title="${pickIdx >= 0 ? 'Remove from branch comparison' : 'Add to branch comparison'}"
       onclick="event.stopPropagation();pinCompareNode('${node.id}')">⇄</button>`;
  // Inline code trace: an always-visible "defining change" line + a ⟨⟩ toggle
  // that expands the full cell source right in the row (no detour to the detail).
  const defining = isRoot ? '' : _definingChange(node);
  const definingHtml = defining
    ? `<div class="node-defining" title="defining change vs parent">✎ ${escapeHtml(defining)}</div>` : '';
  const codePeek = _nodeCodePeek(node);
  const codeToggle = codePeek
    ? `<button class="node-code-toggle" id="ncodebtn-${escapeHtml(node.id)}"
         title="Show the code this node ran"
         onclick="event.stopPropagation();toggleNodeCode('${node.id}')">⟨⟩</button>` : '';
  const codeBlock = codePeek
    ? `<div class="node-code" id="ncode-${escapeHtml(node.id)}" style="display:none"
         onclick="event.stopPropagation()">${codePeek}</div>` : '';
  // Collapse caret for any node with children; collapsed rows show the count.
  const caret = row.hasChildren
    ? `<button class="node-collapse-btn" title="${row.collapsed ? 'Expand' : 'Collapse'} subtree"
         onclick="event.stopPropagation();toggleNodeCollapse('${node.id}')">${row.collapsed ? '▸' : '▾'}</button>`
    : '';
  const hiddenHint = row.collapsed
    ? `<span class="node-hidden-hint">${row.hiddenCount} hidden</span>` : '';
  return `<div class="node-row${selectedCls}" data-node-id="${escapeHtml(node.id)}" onclick="selectNode('${node.id}')">
      <div class="node-row-main">
        ${caret}
        ${pickBadge}
        <span class="node-label">${escapeHtml(labelText)}</span>
        ${divergeBadge}
        ${latestTag}
        ${abandonedPill}
        ${expBadge}
        ${hiddenHint}
        <span class="node-actions">${codeToggle}${compareBtn}${promoteBtn}${deleteBtn}</span>
      </div>
      ${metaLine}
      ${awaitingLine}
      ${definingHtml}
      ${resultMini}
      ${note}
      ${codeBlock}
    </div>`;
}

function summarizeDiff(diff) {
  if (!diff) return '';
  let plus = 0, minus = 0;
  const lines = diff.split('\n');
  for (const ln of lines) {
    if (ln.startsWith('+') && !ln.startsWith('+++')) plus++;
    else if (ln.startsWith('-') && !ln.startsWith('---')) minus++;
  }
  if (!plus && !minus) return '';
  return `+${plus} −${minus}`;
}

function truncate(s, n) {
  if (!s) return '';
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

// ── Inline code tracing on tree nodes ───────────────────────────────────────

// The one-line "defining change" for a node: prefer the first added line of its
// diff-vs-parent (paired with a similar removed line as `old → new` when one
// exists, e.g. threshold tweaks); fall back to the first meaningful line of the
// cell source. Lets you read "what made this branch different" without expanding.
function _similarHead(a, b) {
  const ha = (a.split('=')[0] || '').trim(), hb = (b.split('=')[0] || '').trim();
  return !!ha && ha === hb;
}
function _definingChange(node) {
  const diff = node.git_diff || '';
  if (diff) {
    const adds = [], dels = [];
    for (const ln of diff.split('\n')) {
      if (ln.startsWith('+') && !ln.startsWith('+++')) { const t = ln.slice(1).trim(); if (t) adds.push(t); }
      else if (ln.startsWith('-') && !ln.startsWith('---')) { const t = ln.slice(1).trim(); if (t) dels.push(t); }
    }
    if (adds.length) {
      const a = adds[0];
      const d = dels.find(x => _similarHead(x, a));
      return d ? (truncate(d, 30) + ' → ' + truncate(a, 30)) : truncate(a, 64);
    }
  }
  const src = (node.cell_source || '').split(_CELL_SEP_RE)[0] || '';
  for (const ln of src.split('\n')) {
    const t = ln.trim();
    if (t && !t.startsWith('#') && !t.startsWith('%') && !t.startsWith('!')) return truncate(t, 64);
  }
  return '';
}

// Full cell source highlighted, for the inline ⟨⟩ peek (all cells joined).
function _nodeCodePeek(node) {
  const cells = (node.cell_source || '').split(_CELL_SEP_RE).filter(s => s.trim());
  if (!cells.length) return '';
  const lines = cells.join('\n').split('\n');
  return '<pre class="node-code-pre">' +
    lines.map(l => (typeof _highlightPy === 'function' ? _highlightPy(l) : escapeHtml(l))).join('\n') +
    '</pre>';
}

// Toggle a node's inline code block (no re-render — just flip display).
function toggleNodeCode(id) {
  const el = document.getElementById('ncode-' + id);
  const btn = document.getElementById('ncodebtn-' + id);
  if (!el) return;
  const show = el.style.display === 'none';
  el.style.display = show ? 'block' : 'none';
  if (btn) btn.classList.toggle('open', show);
}

function selectNode(nodeId) {
  if (_compareMode) { toggleCompareNode(nodeId); return; }
  _selectedNodeId = nodeId;
  const view = document.getElementById('session-tree-view');
  if (!view || !_activeSessionId) return;
  document.querySelectorAll('.node-row.selected').forEach(el => el.classList.remove('selected'));
  const target = view.querySelector('.node-row[data-node-id="' + CSS.escape(nodeId) + '"]');
  if (target) target.classList.add('selected');
  renderSelectedNodeDetail(nodeId);
}

// ── Branch comparison ──────────────────────────────────────────────────────

// Re-render the tree from the cached data so picked/selected marks and the
// pick-order badges all reflect current state in one pass (removing a middle
// pick renumbers the rest, which a per-row class toggle can't do).
function _rerenderTreeContainer() {
  const data = _treeCache[_activeSessionId];
  const container = document.getElementById('session-tree-container');
  if (container && data && data.root) {
    container.innerHTML = renderTreeRows(data.root);
  }
}

function toggleCompareMode() {
  _compareMode = !_compareMode;
  _compareNodes = [];
  _applyCompareMode();
  _rerenderTreeContainer();
  _renderCompareBar();
  const panel = document.getElementById('session-compare');
  if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
}

// Sync the toggle button / body class / detail panel to the current
// `_compareMode` flag. Shared by toggleCompareMode (on+off) and pinCompareNode
// (on only) so the mode-state wiring lives in one place.
function _applyCompareMode() {
  const btn = document.getElementById('session-compare-toggle');
  if (btn) btn.classList.toggle('active', _compareMode);
  document.body.classList.toggle('session-compare-mode', _compareMode);
  // Hide single-node detail while comparing.
  const detail = document.getElementById('session-detail');
  if (detail) detail.classList.remove('visible');
}

function toggleCompareNode(nodeId) {
  const i = _compareNodes.indexOf(nodeId);
  if (i >= 0) _compareNodes.splice(i, 1);
  else _compareNodes.push(nodeId);
  _rerenderTreeContainer();  // renumber badges across all rows
  _renderCompareBar();
}

// Per-node "⇄" pin: add/remove a node from the comparison directly, enabling
// Compare-branches mode on the fly so you don't have to hunt for the global
// toggle first when the tree is long.
function pinCompareNode(nodeId) {
  if (!_compareMode) { _compareMode = true; _applyCompareMode(); }
  toggleCompareNode(nodeId);
}

// Small "⧉ Copy" button that copies `raw` (the unhighlighted source/output, with
// newlines intact — the rendered <pre> interleaves line-number spans, so we copy
// from this stashed attribute rather than textContent).
function _copyBtn(raw, extraClass) {
  return `<button class="sess-copy-btn${extraClass ? ' ' + extraClass : ''}"
    title="Copy to clipboard" data-raw="${escapeHtml(raw)}"
    onclick="copySessionText(this, event)">⧉ Copy</button>`;
}

// Copy `raw` to the clipboard and flash a "copied" state on `btn`, restoring its
// original label after a beat. stopPropagation keeps the click off any enclosing
// <summary> so a copy never toggles the cell. Shared by the per-cell and
// per-line copy buttons.
function _copyToClipboard(btn, raw, doneLabel, ev) {
  if (ev) { ev.stopPropagation(); ev.preventDefault(); }
  if (!(navigator.clipboard && navigator.clipboard.writeText)) return;
  navigator.clipboard.writeText(raw).then(() => {
    const orig = btn.innerHTML;
    btn.classList.add('copied');
    btn.innerHTML = doneLabel;
    setTimeout(() => { btn.classList.remove('copied'); btn.innerHTML = orig; }, 1100);
  }).catch(() => {});
}

function copySessionText(btn, ev) {
  _copyToClipboard(btn, btn.dataset.raw || '', '✓ Copied', ev);
}

// Guard a cell's <details> toggle: if the user is mid-selection *inside this
// cell* (e.g. drag-selecting a line of code to copy and releasing on the
// summary), don't let the click collapse the cell out from under them.
function _cellSummaryClick(ev) {
  const sel = window.getSelection();
  if (sel && sel.toString().length > 0) {
    const details = ev.currentTarget.closest('details');
    if (details && sel.anchorNode && details.contains(sel.anchorNode)) {
      ev.preventDefault();
      return false;
    }
  }
  return true;
}

// Per-line copy: the gutter-free raw source lives on the .cl's data-line.
function copyCellLine(btn, ev) {
  const cl = btn.closest('.cl');
  _copyToClipboard(btn, cl ? (cl.dataset.line || '') : '', '✓', ev);
}

// Create a standalone experiment from a node's captured data (dashboard
// equivalent of %exptrack promote when there's no live notebook run). On
// success the node gains its → exp badge; we refresh the tree and reopen detail.
async function materializeExperiment(nodeId) {
  const r = await postApi('/api/session/' + _activeSessionId + '/materialize-experiment',
                          {node_id: nodeId});
  if (!r || r.error) {
    alert((r && r.error) || 'Could not create experiment');
    return;
  }
  delete _treeCache[_activeSessionId];
  // Pull the freshly-created run into the sidebar/table immediately so it's
  // clickable without waiting for the next auto-refresh.
  if (typeof loadExperiments === 'function') await loadExperiments();
  await renderSessionTree(_activeSessionId);
  selectNode(nodeId);
}

function _renderCompareBar() {
  const bar = document.getElementById('session-compare-bar');
  if (!bar) return;
  if (!_compareMode) { bar.style.display = 'none'; bar.innerHTML = ''; return; }
  bar.style.display = 'flex';
  const n = _compareNodes.length;
  bar.innerHTML = `
    <span class="compare-bar-hint">${n
      ? n + ' node' + (n === 1 ? '' : 's') + ' selected — pick checkpoints/branches to compare'
      : 'Click nodes to add them to the comparison'}</span>
    <span class="compare-bar-actions">
      <button onclick="runCompare()" ${n < 2 ? 'disabled' : ''}>Compare ${n || ''}</button>
      <button class="ghost" onclick="clearCompare()" ${n ? '' : 'disabled'}>Clear</button>
      <button class="ghost" onclick="toggleCompareMode()" title="Exit branch comparison">Done</button>
    </span>`;
}

function clearCompare() {
  _compareNodes = [];
  _rerenderTreeContainer();
  _renderCompareBar();
  const panel = document.getElementById('session-compare');
  if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
}

function runCompare() {
  const data = _treeCache[_activeSessionId];
  if (!data || _compareNodes.length < 2) return;
  const nodes = _compareNodes
    .map(id => findNodeInTree(data.root, id))
    .filter(Boolean);
  const panel = document.getElementById('session-compare');
  if (!panel) return;
  const cols = nodes.map(node => {
    const latest = _getLatestOutput(node);
    const cellCount = node.cell_source ? node.cell_source.split(_CELL_SEP_RE).length : 0;
    const diff = summarizeDiff(node.git_diff);
    const expBadge = node.exp_id
      ? `<a href="#" onclick="showDetail('${node.exp_id}');return false">→ exp ${escapeHtml(node.exp_id.slice(0,8))}</a>`
      : '<span class="cmp-noexp">not promoted</span>';
    const ci = _imgThumbs(node);
    const imgRow = ci.count
      ? `<div class="cmp-result-label">Plots</div>${ci.html}` : '';
    return `<div class="cmp-col">
      <div class="cmp-col-head">
        <span class="cmp-type cmp-type-${escapeHtml(node.node_type)}">${escapeHtml(node.node_type)}</span>
        <span class="cmp-label">${escapeHtml(node.label || '(unlabeled)')}</span>
      </div>
      <div class="cmp-meta">${cellCount} cell${cellCount===1?'':'s'}${diff ? ' · ' + diff : ''} · ${expBadge}</div>
      <div class="cmp-result-label">Result${latest ? _copyBtn(latest) : ''}</div>
      <pre class="cmp-result">${latest ? escapeHtml(latest) : '<span class="cmp-empty">(no captured output)</span>'}</pre>
      ${imgRow}
    </div>`;
  }).join('');
  panel.innerHTML = `
    <div class="cmp-head">
      <span class="section-title">Comparing ${nodes.length} nodes</span>
      <button class="ghost" onclick="clearCompare()">Close</button>
    </div>
    <div class="cmp-grid" style="grid-template-columns:repeat(${nodes.length}, minmax(220px, 1fr))">${cols}</div>`;
  panel.style.display = 'block';
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

async function renderSelectedNodeDetail(nodeId) {
  const detail = document.getElementById('session-detail');
  if (!detail) return;
  let data = _treeCache[_activeSessionId];
  if (!data) {
    data = await api('/api/session/' + _activeSessionId);
    if (data && !data.error) _treeCache[_activeSessionId] = data;
  }
  const node = findNodeInTree(data && data.root, nodeId);
  if (!node) { detail.classList.remove('visible'); return; }
  detail.classList.add('visible');
  const noteVal = node.note || '';
  const expLink = (node.node_type === 'root') ? '' : _renderNodeExpLink(node);
  const latest = _getLatestOutput(node);
  const resultBlock = latest
    ? `<div><span class="section-title">Latest result${_copyBtn(latest)}</span>
        <pre class="node-latest-result">${escapeHtml(latest)}</pre></div>`
    : '';
  const _imgs = _imgThumbs(node);
  const imgBlock = _imgs.count
    ? `<div><span class="section-title">Plots (${_imgs.count})</span>${_imgs.html}</div>`
    : '';
  const renameable = node.node_type !== 'root';
  const labelHtml = renameable
    ? `<span class="node-label-text" id="node-label-text" title="Double-click to rename"
         ondblclick="startNodeRename('${node.id}')">${escapeHtml(node.label || '')}</span>`
    : escapeHtml(node.label || '');
  // Clickable lineage breadcrumb (root → … → this node) so you can see where
  // this node sits in the tree and jump to any ancestor.
  const lineage = node.lineage || [];
  const breadcrumb = lineage.length
    ? `<div class="node-lineage">` +
      lineage.map(a => `<a href="#" onclick="selectNode('${a.id}');return false" title="${escapeHtml(a.node_type || '')}">${escapeHtml(a.label || '(unlabeled)')}</a>`).join('<span class="bc-sep">›</span>') +
      `<span class="bc-sep">›</span><span class="bc-current">${escapeHtml(node.label || '')}</span></div>`
    : '';
  // Remember which cell blocks are expanded so a re-render (note save, diff-mode
  // toggle) doesn't collapse them out from under the user.
  const _prevOpen = new Set();
  detail.querySelectorAll('details.cell-block[data-ck]').forEach(d => {
    if (d.open) _prevOpen.add(d.dataset.ck);
  });
  detail.innerHTML = `
    ${breadcrumb}
    <div><span class="section-title">${escapeHtml(node.node_type || '')}: ${labelHtml}</span></div>
    ${expLink}
    ${resultBlock}
    ${imgBlock}
    <div><span class="section-title">Note</span>
      <textarea class="note-edit" id="node-note-input" placeholder="(no note)">${escapeHtml(noteVal)}</textarea>
      <div class="note-actions">
        <button id="node-note-save" onclick="saveNodeNote('${node.id}')" disabled>Save note</button>
        <span class="note-save-status" id="node-note-status"></span>
      </div>
    </div>
    ${renderNodeCells(node)}
    ${renderSetupCells(node)}
    ${renderDiffSection(node.git_diff, _diffTitleForNode(node))}
  `;
  // Restore previously-expanded cell blocks across the re-render.
  _prevOpen.forEach(ck => {
    const d = detail.querySelector(`details.cell-block[data-ck="${CSS.escape(ck)}"]`);
    if (d) d.open = true;
  });
  const ta = document.getElementById('node-note-input');
  const btn = document.getElementById('node-note-save');
  if (ta && btn) {
    const orig = ta.value;
    ta.addEventListener('input', () => {
      btn.disabled = (ta.value === orig);
      const s = document.getElementById('node-note-status');
      if (s) s.textContent = '';
    });
  }
}

const _CELL_SEP_RE = /\n\n# ── cell ──\n\n/;

// Number of cells in a SEP-joined source/setup blob (0 when empty).
function _cellCount(blob) {
  return blob ? blob.split(_CELL_SEP_RE).length : 0;
}

// Split the SEP-joined outputs blob into a list aligned 1:1 with cells.
function _nodeOutputs(node) {
  if (!node.cell_outputs) return [];
  return node.cell_outputs.split(_CELL_SEP_RE);
}

// The most recent non-empty cell output for a node, or '' if none.
function _getLatestOutput(node) {
  const outs = _nodeOutputs(node).map(o => (o || '').trim()).filter(Boolean);
  return outs.length ? outs[outs.length - 1] : '';
}

// Images attached to a node that can actually be served (have a url).
function _validImages(node) {
  return (node.images || []).filter(im => im && im.url);
}

// Render a node's attached plots (captured by reference from savefig) as a
// thumbnail grid. Returns {count, html}; count excludes images outside the
// project root (can't be served). Missing-on-disk images degrade to a caption.
function _imgThumbs(node) {
  const all = node.images || [];
  const imgs = _validImages(node);
  if (!imgs.length) return {count: 0, html: ''};
  const thumbs = imgs.map(im => {
    const src = fileUrl(im.url);
    const cap = im.label || im.url.split('/').pop();
    return `<figure class="node-img">
      <a href="${src}" target="_blank" rel="noopener" title="${escapeHtml(im.path || im.url)}">
        <img src="${src}" alt="${escapeHtml(cap)}" loading="lazy"
          onerror="this.closest('.node-img').classList.add('img-missing')">
      </a>
      <figcaption>${escapeHtml(truncate(cap, 40))}</figcaption>
    </figure>`;
  }).join('');
  const missing = all.length - imgs.length;
  const note = missing
    ? `<div class="node-img-note">${missing} plot file${missing === 1 ? '' : 's'} outside the project root (not shown)</div>`
    : '';
  return {count: imgs.length, html: `<div class="node-img-grid">${thumbs}</div>${note}`};
}

// Python syntax highlighting (_highlightPy) + word-level diff helpers now live
// in the shared js/highlight.py module — used here and by the experiment view.

// Render a SEP-joined (source, output) blob pair as collapsible cell blocks.
// Every block defaults collapsed — session code is reference material; expand
// individually or via the "expand all" hint above the list.
function _cellBlocksHtml(srcBlob, outBlob, extraClass) {
  const cells = srcBlob.split(_CELL_SEP_RE);
  const outputs = outBlob ? outBlob.split(_CELL_SEP_RE) : [];
  const ckPrefix = extraClass ? extraClass : 'cell';
  return cells.map((c, i) => {
    const srcLines = c.split('\n');
    let staleCount = 0;
    const numbered = srcLines.map((ln, k) => {
      const stale = _isStalePrintLine(ln);
      if (stale) staleCount++;
      // Per-line copy button (hover-revealed) so a single line can be grabbed
      // without dragging a selection — manual selection picks up the line-number
      // gutter spans and a stray click can collapse the cell. `data-line` stashes
      // the raw, gutter-free source for copyCellLine.
      return `<span class="cl${stale ? ' cl-stale' : ''}" data-line="${escapeHtml(ln)}">`
        + `<span class="ln">${k + 1}</span>${_highlightPy(ln)}`
        + (stale ? `<span class="cl-stale-mark" title="${STALE_PRINT_TITLE}">⚠</span>` : '')
        + `<button class="cl-copy" title="Copy this line" onclick="copyCellLine(this, event)">⧉</button>`
        + `</span>`;
    }).join('');
    const out = (outputs[i] || '').trim();
    const outHtml = out
      ? `<div class="cell-output-label">Out${_copyBtn(out)}</div><pre class="cell-output">${escapeHtml(out)}</pre>`
      : '';
    const staleChip = staleCount
      ? ` <span class="stale-print-badge" title="${STALE_PRINT_TITLE}">⚠ ${staleCount} stale?</span>` : '';
    return `<details class="cell-block${extraClass ? ' ' + extraClass : ''}" data-ck="${ckPrefix}-${i}">
      <summary onclick="return _cellSummaryClick(event)">
        <span class="cell-idx">cell ${i + 1}${cells.length > 1 ? ' / ' + cells.length : ''}</span>
        <span class="cell-meta">${srcLines.length} line${srcLines.length === 1 ? '' : 's'}${out ? ' · has output' : ''}</span>${staleChip}
        ${_copyBtn(c, 'cell-code-copy')}
      </summary>
      <pre class="cell-code">${numbered}</pre>
      ${outHtml}
    </details>`;
  }).join('');
}

function _collapsedHint(count, noun) {
  return `<div class="cells-collapsed-hint" onclick="_expandAllCells(this)">
       <span class="cch-chevron">▸</span>
       ${count} ${noun}${count === 1 ? '' : 's'} collapsed — expand all
     </div>`;
}

function renderNodeCells(node) {
  if (!node.cell_source) return '';
  const n = _cellCount(node.cell_source);
  const blocks = _cellBlocksHtml(node.cell_source, node.cell_outputs, '');
  const heading = n > 1
    ? `Cells run since previous node (${n})`
    : 'Cell run since previous node';
  return `<div><span class="section-title">${heading}</span>${_collapsedHint(n, 'cell')}${blocks}</div>`;
}

// %%setup prep cells — recorded but secondary; rendered dimmed under their own
// heading and collapsed by default so they don't crowd the real cells.
function renderSetupCells(node) {
  if (!node.setup_source) return '';
  const n = _cellCount(node.setup_source);
  const blocks = _cellBlocksHtml(node.setup_source, node.setup_outputs, 'setup-cell');
  return `<div class="setup-section">
    <span class="section-title">Setup / prep
      <span class="pill pill-setup" title="Recorded but secondary — %%setup cells">prep</span>
      (${n})</span>
    ${_collapsedHint(n, 'setup cell')}${blocks}</div>`;
}

function _expandAllCells(el) {
  const parent = el.parentNode;
  if (!parent) return;
  parent.querySelectorAll('details.cell-block').forEach(d => { d.open = true; });
  el.remove();
}

function _diffTitleForNode(node) {
  const t = node.node_type;
  if (t === 'branch') return 'Diff vs parent checkpoint';
  if (t === 'checkpoint') return 'Diff since previous checkpoint';
  return 'Git diff';
}

function _diffMode() {
  return localStorage.getItem('exptrack-diff-mode') || 'split';
}
function setDiffMode(mode) {
  localStorage.setItem('exptrack-diff-mode', mode);
  if (_selectedNodeId) renderSelectedNodeDetail(_selectedNodeId);
}

function _parseDiff(diff) {
  const files = [];
  let curFile = null;
  let curHunk = null;
  let totalAdd = 0, totalDel = 0;
  const newFile = (header) => {
    curFile = { header: header || '', hunks: [], plus: 0, minus: 0 };
    files.push(curFile);
    curHunk = null;
  };
  for (const ln of diff.split('\n')) {
    if (ln.startsWith('diff --git')) { newFile(ln); continue; }
    if (ln.startsWith('--- ') || ln.startsWith('+++ ')
        || ln.startsWith('index ') || ln.startsWith('new file')
        || ln.startsWith('deleted file') || ln.startsWith('similarity')
        || ln.startsWith('rename ')) {
      if (!curFile) newFile('');
      curFile.header += (curFile.header ? '\n' : '') + ln;
      continue;
    }
    if (ln.startsWith('@@')) {
      if (!curFile) newFile('');
      curHunk = { header: ln, rows: [] };
      curFile.hunks.push(curHunk);
      continue;
    }
    if (!curHunk) continue;
    let kind = 'ctx';
    if (ln.startsWith('+')) { kind = 'add'; curFile.plus++; totalAdd++; }
    else if (ln.startsWith('-')) { kind = 'del'; curFile.minus++; totalDel++; }
    curHunk.rows.push({ kind, text: ln.length ? ln.slice(1) : '' });
  }
  return { files, plus: totalAdd, minus: totalDel };
}

function _pairHunkRows(rows) {
  const pairs = [];
  let i = 0;
  while (i < rows.length) {
    const r = rows[i];
    if (r.kind === 'ctx') {
      pairs.push({ left: r, right: r });
      i++;
      continue;
    }
    const dels = [], adds = [];
    while (i < rows.length && rows[i].kind === 'del') { dels.push(rows[i]); i++; }
    while (i < rows.length && rows[i].kind === 'add') { adds.push(rows[i]); i++; }
    const n = Math.max(dels.length, adds.length);
    for (let k = 0; k < n; k++) {
      pairs.push({ left: dels[k] || null, right: adds[k] || null });
    }
  }
  return pairs;
}

function _shortFileLabel(header) {
  if (!header) return '(file)';
  const m = header.match(/^diff --git a\/(.+?) b\/(.+)$/m);
  if (m) return m[1] === m[2] ? m[1] : m[1] + ' → ' + m[2];
  const mm = header.match(/^\+\+\+ b\/(.+)$/m);
  if (mm) return mm[1];
  return header.split('\n')[0].slice(0, 80);
}

function renderDiffSection(diff, title) {
  if (!diff) return '';
  if (diff.startsWith('[capture-failed')) {
    return `<div><span class="section-title">${escapeHtml(title)}</span>
      <pre class="diff plain" style="color:var(--yellow,#e8a735);font-style:italic">git diff failed to capture for this checkpoint (not a clean tree).</pre></div>`;
  }
  const parsed = _parseDiff(diff);
  if (!parsed.files.length) {
    return `<div><span class="section-title">${escapeHtml(title)}</span>
      <pre class="diff plain">${escapeHtml(diff)}</pre></div>`;
  }
  const mode = _diffMode();
  const summary = parsed.plus || parsed.minus
    ? `<span class="diff-summary"><span class="d-stat-add">+${parsed.plus}</span> <span class="d-stat-del">−${parsed.minus}</span></span>` : '';
  const toggle = `
    <span class="diff-mode-toggle">
      <button class="diff-mode-btn ${mode==='split'?'active':''}" onclick="setDiffMode('split')">Split</button>
      <button class="diff-mode-btn ${mode==='unified'?'active':''}" onclick="setDiffMode('unified')">Unified</button>
    </span>`;
  const openByDefault = parsed.files.length <= 4;
  const filesHtml = parsed.files.map(f =>
    _renderFileBlock(f, mode, openByDefault)
  ).join('');
  return `<div class="diff-section">
    <div class="diff-section-head">
      <span class="section-title">${escapeHtml(title)}</span>
      ${summary}
      ${toggle}
    </div>
    ${filesHtml}
  </div>`;
}

function _renderFileBlock(f, mode, openByDefault) {
  const label = _shortFileLabel(f.header);
  const head = `<summary class="diff-file-head">
    <span class="diff-file-name">${escapeHtml(label)}</span>
    <span class="diff-file-stats">
      <span class="d-stat-add">+${f.plus}</span>
      <span class="d-stat-del">−${f.minus}</span>
    </span>
  </summary>`;
  const body = f.hunks.map(h =>
    mode === 'split' ? _renderHunkSplit(h) : _renderHunkUnified(h)
  ).join('');
  return `<details class="diff-file"${openByDefault ? ' open' : ''}>${head}
    <div class="diff-file-body">${body || '<div class="diff-empty">(no hunks)</div>'}</div>
  </details>`;
}

function _renderHunkUnified(h) {
  const rows = h.rows.map(r => {
    const cls = 'du-' + r.kind;
    const sign = r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ' ';
    return `<div class="du-row ${cls}">
      <span class="du-sign">${sign}</span>
      <span class="du-text">${escapeHtml(r.text) || '&nbsp;'}</span>
    </div>`;
  }).join('');
  return `<div class="diff-hunk-head">${escapeHtml(h.header)}</div>
    <div class="diff-unified">${rows}</div>`;
}

function _renderHunkSplit(h) {
  const cell = (r) => {
    if (!r) return `<td class="ds-cell ds-empty"></td>`;
    return `<td class="ds-cell ds-${r.kind}"><span class="ds-text">${escapeHtml(r.text) || '&nbsp;'}</span></td>`;
  };
  const rowsHtml = _pairHunkRows(h.rows).map(p =>
    `<tr>${cell(p.left)}${cell(p.right)}</tr>`
  ).join('');
  return `<div class="diff-hunk-head">${escapeHtml(h.header)}</div>
    <table class="diff-split"><tbody>${rowsHtml}</tbody></table>`;
}

function findNodeInTree(root, id) {
  if (!root) return null;
  if (root.id === id) return root;
  for (const ch of (root.children || [])) {
    const found = findNodeInTree(ch, id);
    if (found) return found;
  }
  return null;
}

async function saveNodeNote(nodeId) {
  const ta = document.getElementById('node-note-input');
  if (!ta || !_activeSessionId) return;
  const btn = document.getElementById('node-note-save');
  const status = document.getElementById('node-note-status');
  if (btn) btn.disabled = true;
  if (status) status.textContent = 'Saving…';
  const r = await postApi('/api/session/' + _activeSessionId + '/note-node',
    {node_id: nodeId, text: ta.value});
  if (r && r.ok) {
    delete _treeCache[_activeSessionId];
    if (status) {
      const t = new Date().toTimeString().slice(0, 5);
      status.textContent = 'Saved · ' + t;
      status.classList.add('ok');
    }
    // Refresh the tree silently — but keep the detail open with the new value.
    const data = await api('/api/session/' + _activeSessionId);
    if (data && !data.error) {
      _treeCache[_activeSessionId] = data;
      // Re-render just the tree, not the detail (preserves saved indicator).
      const container = document.getElementById('session-tree-container');
      if (container && data.root) {
        container.innerHTML = renderTreeRows(data.root);
      }
    }
  } else {
    if (status) {
      status.textContent = 'Error: ' + ((r && r.error) || 'save failed');
      status.classList.remove('ok');
      status.classList.add('err');
    }
    if (btn) btn.disabled = false;
  }
}

// Inline-rename a node label from the detail header (double-click). Mirrors
// the experiment inline-edit pattern: Enter/blur saves, Escape cancels.
function startNodeRename(nodeId) {
  const span = document.getElementById('node-label-text');
  if (!span) return;
  const cur = span.textContent;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = cur;
  input.className = 'node-label-input';
  span.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const val = input.value.trim();
    if (!save || !val || val === cur) { renderSelectedNodeDetail(nodeId); return; }
    const r = await postApi('/api/session/' + _activeSessionId + '/rename-node',
      {node_id: nodeId, label: val});
    if (!r || r.error) {
      alert('Could not rename node: ' + ((r && r.error) || 'unknown error'));
      renderSelectedNodeDetail(nodeId);
      return;
    }
    // Refresh the cached tree so both the tree and detail show the new label.
    _refreshTreeAndDetail(nodeId);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', () => finish(true));
}

// Re-fetch the session tree (busting the cache) and re-render the tree plus the
// open node detail. Shared by mutations that change a node in place.
async function _refreshTreeAndDetail(nodeId) {
  delete _treeCache[_activeSessionId];
  const data = await api('/api/session/' + _activeSessionId);
  if (data && !data.error) _treeCache[_activeSessionId] = data;
  _rerenderTreeContainer();
  if (_selectedNodeId === nodeId) renderSelectedNodeDetail(nodeId);
}

async function promoteBranch(nodeId) {
  if (!_activeSessionId) return;
  if (!confirm('Promote this branch to a checkpoint?\n\n' +
      'Its current diff is frozen as the checkpoint snapshot, and later ' +
      'branches will attach under it.')) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/promote-to-checkpoint',
    {node_id: nodeId});
  if (!r || r.error) {
    alert('Could not promote: ' + ((r && r.error) || 'unknown error'));
    return;
  }
  _refreshTreeAndDetail(nodeId);
}

// ── Linking experiments to nodes (dashboard "promote") ─────────────────────

// Render the node-detail "Linked experiment" block. When a run is linked: a
// jump-link + Change/Unlink. When not: a "+ Link experiment" affordance (point
// the node at an existing run) alongside "＋ Promote to experiment" (materialize
// a brand-new run from the node). The container id is stable (one detail panel
// at a time) so the inline picker can replace it.
function _renderNodeExpLink(node) {
  let inner;
  if (node.exp_id) {
    const nm = node.exp_name ? ' — ' + escapeHtml(truncate(node.exp_name, 50)) : '';
    inner = `<a href="#" onclick="showDetail('${node.exp_id}');return false"
         title="${escapeHtml(node.exp_id)}">${escapeHtml(node.exp_id.slice(0, 8))}${nm}</a>
      <button class="node-exp-link-btn" onclick="startLinkExperiment('${node.id}')">Change</button>
      <button class="node-exp-link-btn ghost" onclick="unlinkExperiment('${node.id}')">Unlink</button>`;
  } else {
    inner = `<span class="node-exp-none">none</span>
      <button class="node-exp-link-btn" onclick="startLinkExperiment('${node.id}')">+ Link experiment</button>
      <button class="node-materialize-btn" onclick="materializeExperiment('${node.id}')"
        title="Create a standalone experiment from this node's code, git state & output, and link it">
        ＋ Promote to experiment</button>`;
  }
  return `<div id="node-exp-link" class="node-exp-link">
    <span class="section-title">Linked experiment</span>
    ${inner}
  </div>`;
}

// Swap the link block for an inline experiment picker (populated from the
// already-loaded experiment list).
function startLinkExperiment(nodeId) {
  const box = document.getElementById('node-exp-link');
  if (!box) return;
  const opts = (allExperiments || [])
    .map(e => `<option value="${escapeHtml(e.id)}">${escapeHtml(e.name || e.id)} · ${escapeHtml(e.id.slice(0, 8))}</option>`)
    .join('');
  box.innerHTML = `<span class="section-title">Link experiment</span>
    <select id="link-exp-select" class="link-exp-select">${opts || '<option value="">(no experiments)</option>'}</select>
    <button class="node-exp-link-btn" onclick="saveLinkExperiment('${nodeId}')">Link</button>
    <button class="node-exp-link-btn ghost" onclick="renderSelectedNodeDetail('${nodeId}')">Cancel</button>`;
}

async function saveLinkExperiment(nodeId) {
  const sel = document.getElementById('link-exp-select');
  if (!sel || !_activeSessionId || !sel.value) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/link-experiment',
    {node_id: nodeId, exp_id: sel.value});
  if (!r || r.error) {
    alert('Could not link experiment: ' + ((r && r.error) || 'unknown error'));
    return;
  }
  _refreshTreeAndDetail(nodeId);
  loadSessionsList();  // refresh the "N exp" card count
}

async function unlinkExperiment(nodeId) {
  if (!_activeSessionId) return;
  if (!confirm('Unlink the experiment from this node?\n\n' +
      'The experiment itself is NOT deleted — only the session link is removed.')) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/link-experiment',
    {node_id: nodeId, exp_id: ''});
  if (!r || r.error) {
    alert('Could not unlink: ' + ((r && r.error) || 'unknown error'));
    return;
  }
  _refreshTreeAndDetail(nodeId);
  loadSessionsList();
}

// End the active session (UI equivalent of `%exptrack session end`): open
// branches (no checkpoint after them) flip to abandoned, status → ended.
async function endSession() {
  if (!_activeSessionId) return;
  if (!confirm('End this session?\n\n' +
      'Any open branches (with no checkpoint after them) are marked abandoned. ' +
      'Everything stays viewable; this just closes the session.')) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/end', {});
  if (!r || r.error) {
    alert('Could not end session: ' + ((r && r.error) || 'unknown error'));
    return;
  }
  delete _treeCache[_activeSessionId];
  renderSessionTree(_activeSessionId);
  loadSessionsList();
}

async function confirmDeleteNode(nodeId) {
  if (!_activeSessionId) return;
  const preview = await postApi('/api/session/' + _activeSessionId + '/delete-node-preview',
    {node_id: nodeId});
  if (!preview || preview.error) {
    alert('Could not preview delete: ' + ((preview && preview.error) || 'unknown error'));
    return;
  }
  if (preview.is_root) {
    alert('Cannot delete the session root — use the session delete button instead.');
    return;
  }
  const label = preview.label || '(unlabeled)';
  const nodes = preview.nodes || 0;
  const desc = preview.descendants || 0;
  const exps = preview.experiments || 0;
  const lines = [];
  lines.push(`Delete ${preview.node_type} "${label}"?`);
  lines.push('');
  if (desc > 0) {
    lines.push(`This will also remove ${desc} descendant node${desc === 1 ? '' : 's'} ` +
               `(${nodes} total).`);
  } else {
    lines.push('This node has no descendants.');
  }
  if (exps > 0) {
    lines.push(`${exps} linked experiment${exps === 1 ? '' : 's'} will be preserved ` +
               '(their session_node_id is cleared).');
  }
  const imgs = preview.images || 0;
  if (imgs > 0) {
    lines.push(`${imgs} attached plot file${imgs === 1 ? '' : 's'} stay on disk for now — ` +
               'they move to your OS Trash only if you later permanently delete (purge) the node.');
  }
  lines.push('');
  lines.push('Moves the node(s) to this session\'s Trash — restore from the Trash panel.');
  if (!confirm(lines.join('\n'))) return;
  const r = await postApi('/api/session/' + _activeSessionId + '/delete-node',
    {node_id: nodeId});
  if (r && r.ok) {
    if (_selectedNodeId === nodeId) {
      _selectedNodeId = null;
      const detail = document.getElementById('session-detail');
      if (detail) { detail.innerHTML = ''; detail.classList.remove('visible'); }
    }
    delete _treeCache[_activeSessionId];
    renderSessionTree(_activeSessionId);
    // Refresh session card counts (checkpoint/exp totals).
    loadSessionsList();
  } else {
    alert('Could not delete node: ' + ((r && r.error) || 'unknown error'));
  }
}

// Alias for the shared esc() (identical body) — kept because many lines here
// reference escapeHtml by name. See esc()/escJs() in js/mutations.py.
function escapeHtml(s) { return esc(s); }
