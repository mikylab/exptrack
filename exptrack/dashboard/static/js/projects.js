// The project switcher. One dashboard, many projects; the databases stay
// separate and this chooses which one every request reads.

// Names by project id, remembered by whichever surface fetched /api/projects.
// Compare can hold a run from another project and has to label it with
// something a human recognizes, and the run picker lists the projects too —
// neither should re-fetch the listing just to print a name.
const _projectNames = {};

function rememberProjects(list) {
  for (const p of (list || [])) {
    if (p && p.id) _projectNames[p.id] = p.name || p.id;
  }
}

// Falls back to the id prefix rather than rendering nothing: an unnamed
// project is still a project the reader has to be able to tell apart.
function projectName(id) {
  return _projectNames[id] || String(id || '').slice(0, 8);
}

// Whether the "manage projects" panel (the dismiss/forget list) is expanded.
// Not persisted — it's a one-off action surface, not a view worth remembering
// across reloads the way the sidebar's own collapsed state is.
let _projectManageOpen = false;

// The picker itself, rendered once for the rail and once for the page header.
// Both go through `switchProject(id)` — there is one switch path, and a second
// copy of this markup would be a second place for the "stale entries are shown,
// not hidden" rule to be forgotten. A project the server could not read keeps
// its row, carries the reason, and is `disabled`, so it can be seen but never
// selected by accident.
function _projectOptionHtml(p, current, inGroup) {
  const bad = p.status !== 'ok';
  // Inside a group the directory names are usually identical — three
  // checkouts of one repository — so the branch is the only thing that tells
  // them apart, and it leads. Outside a group the name is what the reader
  // knows the project by.
  const base = (inGroup && p.branch) ? p.branch : p.name;
  const label = base + (bad ? '  (' + p.status + ')' : '');
  // The reason rides on the option too: the note below the picker only ever
  // describes the *current* project, so without this a stale entry further
  // down the list is greyed out with nothing saying why.
  const why = bad ? (p.message || p.status) : p.path;
  return '<option value="' + escJsAttr(p.id) + '"'
       + (p.id === current ? ' selected' : '')
       + (bad ? ' disabled' : '')
       + ' title="' + esc(why || '') + '">' + esc(label) + '</option>';
}

function _projectSelectHtml(projects, current, selectId) {
  let html = '<select id="' + escJsAttr(selectId) + '" onchange="switchProject(this.value)"'
           + ' title="Switch project">';
  // Worktrees of one repository go under one <optgroup>. The server decides
  // the grouping (`group` / `group_name` / `branch`, from the repository's
  // git common dir) and only ever sets it for a repository with more than
  // one project in the list — a lone project is not a group of one, and a
  // heading over every row would be noise in the single-project case.
  //
  // Order is preserved rather than reshuffled into group blocks: a group's
  // members sort adjacently already (same name, so the path breaks the tie),
  // and moving rows around under a reader who knows where their project sits
  // in the list is a worse trade than a group that appears twice.
  const list = projects || [];
  const groupSize = {};
  for (const p of list) if (p.group) groupSize[p.group] = (groupSize[p.group] || 0) + 1;
  let openGroup = '';
  for (const p of list) {
    const group = p.group || '';
    if (group !== openGroup) {
      if (openGroup) html += '</optgroup>';
      openGroup = group;
      if (group) {
        html += '<optgroup label="' + esc((p.group_name || '') + ' ('
              + groupSize[group] + ' worktrees)') + '">';
      }
    }
    html += _projectOptionHtml(p, current, !!group);
  }
  if (openGroup) html += '</optgroup>';
  return html + '</select>';
}

// The siblings of the project on screen, as links. The switcher moves this
// tab; these move a *new* one, because the project now rides in the URL —
// ctrl/cmd-click or middle-click is how three worktrees end up side by side
// in three windows, which is the whole point of the release and is not
// something a <select> can express.
//
// Rendered only when the current project actually has siblings, and a
// sibling the server refused (stale, schema-skewed) is shown with its reason
// and not linked, the same rule its <option> follows.
function _worktreeSiblingsHtml(projects, current) {
  const me = (projects || []).find(p => p.id === current);
  if (!me || !me.group) return '';
  const siblings = projects.filter(p => p.group === me.group && p.id !== current);
  if (!siblings.length) return '';
  let html = '<div class="project-siblings"><span class="project-siblings-label">'
           + esc(me.group_name || 'worktrees') + '</span>';
  for (const p of siblings) {
    const label = p.branch || p.name;
    if (p.status !== 'ok') {
      html += '<span class="project-sibling bad" title="' + esc(p.message || p.status)
            + '">' + esc(label) + '</span>';
      continue;
    }
    // A real href, not an onclick: that is what makes the browser's own
    // "open in new tab" work, and it is the only affordance that opens a
    // second project without closing the first.
    html += '<a class="project-sibling" href="?project=' + encodeURIComponent(p.id)
          + '" title="' + esc(p.path) + ' — open (ctrl/cmd-click for a new tab)">'
          + esc(label) + '</a>';
  }
  return html + '</div>';
}

// The header copy. Deliberately rendered even with a single project: a second
// project can appear at any time (a `exptrack init` in another checkout, a
// worktree), and a control that is absent until then is a control nobody
// knows exists. With one project it simply names it, which is useful on its
// own — the dashboard otherwise never says which project is on screen.
// The dismiss/forget list is *not* duplicated here; it stays in the rail's
// manage panel, one destructive surface rather than two.
function renderHeaderProjectSwitcher(projects, current, note) {
  const el = document.getElementById('header-project-switcher');
  if (!el) return;
  let html = '<span class="header-project-label">Project</span>'
           + _projectSelectHtml(projects, current, 'header-project-select');
  if (note) {
    html += '<span class="header-project-problem" title="' + esc(note) + '">&#9888; '
          + esc(note) + '</span>';
  }
  el.innerHTML = html;
}

async function loadProjects() {
  const data = await api('/api/projects');
  if (!data) {
    // The call failed for some other reason (network, auth, …) — but a
    // stored project id that no longer resolves is exactly the kind of
    // problem a reload should get a clean shot at instead of repeating.
    // /api/projects is exempt from activation (server-side), so this is not
    // that same 400/409 failure mode — but clearing here costs nothing and
    // means a reload can never be stuck replaying a dead id.
    if (_activeProjectId) {
      _activeProjectId = '';
      _storageDel(_PROJECT_KEY);
      _setUrlProject('');
    }
    return {recovered: false, projects: null};
  }
  rememberProjects(data.projects);
  const el = document.getElementById('project-switcher');
  // /api/projects never serves an unrecognized id's data: an unknown, stale
  // or schema-skewed stored id comes back with `current` pointing at the
  // default project instead of the one we asked for. That mismatch is the
  // signal that the stored id is dead — adopt what the server reported so
  // the next request (and every one after) stops naming a project the
  // server refuses, rather than leaving the dashboard silently repeating the
  // same failed request forever.
  let recovered = false;
  if (_activeProjectId && data.current !== _activeProjectId) {
    _activeProjectId = data.current;
    _storageSet(_PROJECT_KEY, data.current);
    // The URL is this tab's binding, so a dead id left in it would come back
    // on every reload and re-run this recovery forever.
    _setUrlProject(data.current);
    recovered = true;
  }
  const current = _activeProjectId || data.current;
  // One sentence about the project on screen, shared by both switchers: a
  // recovery the reader has to be told about, or the reason the current
  // project cannot be read. Computed once so the header and the rail can
  // never disagree about what is wrong.
  let note = '';
  if (recovered) {
    // Say why the view moved — a silent switch under the user is worse than
    // the dead project it replaces, because it looks like nothing happened.
    const name = (data.projects.find(p => p.id === current) || {}).name || current;
    note = 'Saved project is no longer available — switched to ' + name + '.';
  } else {
    const problem = data.projects.find(p => p.id === current && p.status !== 'ok');
    if (problem) note = problem.message;
  }
  // The header switcher is rendered before the rail's, and outside the guard
  // below: the rail is collapsed by default and its container can be absent
  // entirely, and neither is a reason for the page to stop saying which
  // project it is showing.
  renderHeaderProjectSwitcher(data.projects, current, note);
  // Reported, not just applied: every other boot-time load carries the stored
  // project id, so a recovery here means they all failed and have to be re-run.
  if (!el) return {recovered: recovered, projects: data.projects};
  let html = '<div class="project-switcher-row">';
  html += _projectSelectHtml(data.projects, current, 'project-select');
  html += '<button class="project-manage-toggle" onclick="toggleProjectManage()" '
        + 'title="Manage registered projects">&#9881;</button>';
  html += '</div>';
  if (note) html += '<div class="project-problem">' + esc(note) + '</div>';
  html += _worktreeSiblingsHtml(data.projects, current);
  // The manage panel is where "dismiss" lives: a <select>'s <option>s can't
  // host their own buttons, so a row-per-project list is the only way to put
  // a forget control on a specific entry rather than on the switcher as a
  // whole. Collapsed by default and reached through an explicit toggle (never
  // inline with the picker) so dismissing a project is never one stray click
  // away from just switching to it.
  html += '<div id="project-manage-panel" class="project-manage-panel"'
        + (_projectManageOpen ? '' : ' style="display:none"') + '>';
  for (const p of data.projects) {
    html += '<div class="project-manage-row">'
          + '<span class="project-manage-name" title="' + esc(p.path) + '">' + esc(p.name) + '</span>'
          + '<button class="project-manage-forget" '
          + 'onclick="forgetProject(\'' + escJsAttr(p.id) + '\', \'' + escJsAttr(p.name) + '\')" '
          + 'title="Forget this project (does not delete anything on disk)">Forget</button>'
          + '</div>';
  }
  html += '</div>';
  el.innerHTML = html;
  return {recovered: recovered, projects: data.projects};
}

function toggleProjectManage() {
  _projectManageOpen = !_projectManageOpen;
  const panel = document.getElementById('project-manage-panel');
  if (panel) panel.style.display = _projectManageOpen ? '' : 'none';
}

function switchProject(id) {
  _activeProjectId = id;
  _storageSet(_PROJECT_KEY, id);           // the default for the next new tab
  _setUrlProject(id);                      // ...and the binding for THIS one
  location.reload();                       // every view is project-scoped
}

// Forgetting is destructive in the small sense that getting the project back
// means registering it again (`exptrack init` / `exptrack ui start` in it),
// so it asks first — the native confirm() dialog, which needs its own
// explicit click and can't be triggered by the same misclick that would hit
// the switcher or the manage toggle.
async function forgetProject(id, name) {
  if (!confirm('Forget "' + name + '"? This only removes it from the switcher '
             + '— its database and files are untouched. Register it again with '
             + '`exptrack init` or `exptrack ui start` in it.')) {
    return;
  }
  const res = await postApi('/api/project/forget', {id});
  if (!res) return;                        // postApi() can return null
  if (res.error) { owlSay(res.error); return; }
  if (!res.ok) {
    // `forget` only edits the registry, and returns false when there was no
    // entry to edit — which is exactly what a project discovered as a
    // worktree of this repository looks like. Without this branch the user
    // confirmed a destructive-sounding dialog and nothing visibly happened.
    owlSay('"' + name + '" was not in the project registry, so there was '
         + 'nothing to remove — it is still discovered as a worktree of this '
         + 'repository and stays in the list.');
    return;
  }
  if (_activeProjectId === id) {
    // Forgetting the project you're currently viewing would otherwise leave
    // the switcher pointing at an id the server no longer recognizes — the
    // same dead-selection state loadProjects()'s recovery path exists to
    // fix. Clear it up front and reload straight into the default project
    // rather than round-tripping through that recovery on the next request.
    _activeProjectId = '';
    _storageDel(_PROJECT_KEY);
    _setUrlProject('');
    location.reload();
    return;
  }
  _projectManageOpen = true;                // keep the panel open through the repaint
  const after = await loadProjects();
  // A registered project that is *also* a worktree of this repository is still
  // discovered after its registry entry goes, so the row the user just acted
  // on is still there. Documented in cli-reference.md; saying nothing here
  // left the UI looking like the forget had failed.
  const still = ((after && after.projects) || []).some(p => p.id === id);
  owlSay(still
    ? '"' + name + '" was removed from the project registry, but it is still '
      + 'discovered as a worktree of this repository, so it stays in the list.'
    : '"' + name + '" was removed from the project list — its database and '
      + 'files were not touched.');
}
