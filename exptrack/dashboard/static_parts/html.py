"""
exptrack/dashboard/static_parts/html.py — HTML template structure

Split from static.py for maintainability.
"""

# Document head (everything before <style>)
HTML_HEAD = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>exptrack</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
"""

# Everything between </style></head> and <script>
HTML_BODY = r"""</style>
</head>
<body>

<div class="header">
  <h1 onclick="showWelcome()" title="Back to dashboard home"><span class="owl-container" id="header-owl"><span class="owl-speech" id="owl-speech" onclick="event.stopPropagation();dismissOwl()"></span><span class="owl-mascot owl-blink" onclick="event.stopPropagation();owlSpeak('click')"><svg width="28" height="28" viewBox="0 0 16 16" style="vertical-align:middle;margin-right:6px;image-rendering:pixelated"><!-- Pixel owl: ear tufts --><rect x="4" y="1" width="1" height="1" fill="#7c3aed"/><rect x="11" y="1" width="1" height="1" fill="#7c3aed"/><rect x="4" y="2" width="1" height="1" fill="#7c3aed"/><rect x="11" y="2" width="1" height="1" fill="#7c3aed"/><!-- Head --><rect x="5" y="2" width="6" height="1" fill="#2c5aa0"/><rect x="4" y="3" width="8" height="1" fill="#2c5aa0"/><rect x="4" y="4" width="8" height="1" fill="#2c5aa0"/><!-- Eyes (white circles with dark pupils) --><rect class="owl-eye-white" x="5" y="4" width="2" height="1" fill="#fff"/><rect class="owl-eye-white" x="9" y="4" width="2" height="1" fill="#fff"/><rect x="6" y="4" width="1" height="1" fill="#1a1a1a"/><rect x="10" y="4" width="1" height="1" fill="#1a1a1a"/><!-- Beak --><rect x="7" y="5" width="2" height="1" fill="#ffc107"/><!-- Body --><rect x="4" y="5" width="3" height="1" fill="#2c5aa0"/><rect x="9" y="5" width="3" height="1" fill="#2c5aa0"/><rect x="4" y="6" width="8" height="1" fill="#2c5aa0"/><rect x="5" y="7" width="6" height="1" fill="#2c5aa0"/><!-- Belly --><rect x="6" y="7" width="4" height="1" fill="#5c9ce6"/><rect x="5" y="8" width="6" height="1" fill="#2c5aa0"/><rect x="6" y="8" width="4" height="1" fill="#5c9ce6"/><!-- Wings --><rect x="3" y="6" width="1" height="2" fill="#7c3aed"/><rect x="12" y="6" width="1" height="2" fill="#7c3aed"/><!-- Feet --><rect x="6" y="9" width="1" height="1" fill="#ffc107"/><rect x="9" y="9" width="1" height="1" fill="#ffc107"/></svg></span></span>exptrack</h1>
  <div class="header-actions">
    <button class="toolbox-btn" data-tab="todos" onclick="openToolbox('todos')" title="Todo list">&#9745; Todo</button>
    <button class="toolbox-btn" data-tab="commands" onclick="openToolbox('commands')" title="Saved commands">&gt;_ Cmds</button>
    <button class="theme-btn" id="theme-toggle" onclick="toggleTheme()" title="Toggle dark mode">&#9790;</button>
    <button class="help-btn" onclick="toggleHelp()">? Docs</button>
    <div class="settings-wrap">
      <button class="settings-btn" onclick="toggleSettingsPanel()" title="Settings">&#9881;</button>
      <div class="settings-panel" id="settings-panel">
        <div class="settings-section">
          <div class="settings-section-title">Display</div>
          <div class="settings-row">
            <label>Timezone</label>
            <select id="tz-select" onchange="setTimezone(this.value)">
              <option value="">Browser local</option>
              <option value="UTC">UTC</option>
              <option value="America/New_York">US Eastern</option>
              <option value="America/Chicago">US Central</option>
              <option value="America/Denver">US Mountain</option>
              <option value="America/Los_Angeles">US Pacific</option>
              <option value="Europe/London">London</option>
              <option value="Europe/Berlin">Berlin</option>
              <option value="Europe/Paris">Paris</option>
              <option value="Asia/Tokyo">Tokyo</option>
              <option value="Asia/Shanghai">Shanghai</option>
              <option value="Asia/Kolkata">India</option>
              <option value="Australia/Sydney">Sydney</option>
            </select>
          </div>
        </div>
        <div class="settings-section">
          <div class="settings-section-title">Metrics</div>
          <div class="settings-row">
            <label title="Only store every Nth metric point during training (1 = keep all)">Save every Nth step</label>
            <input type="number" id="settings-keep-every" min="1" value="1" style="width:70px;font-family:inherit;font-size:12px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--code-bg);color:var(--fg)" onchange="saveMetricSettings()">
          </div>
          <div class="settings-row">
            <label title="Max points to show on charts (server-side downsampling)">Chart max points</label>
            <input type="number" id="settings-max-points" min="10" max="50000" value="500" style="width:70px;font-family:inherit;font-size:12px;padding:4px 8px;border:1px solid var(--border);border-radius:4px;background:var(--code-bg);color:var(--fg)" onchange="saveMetricSettings()">
          </div>
        </div>
        <div class="settings-section">
          <div class="settings-section-title">Database</div>
          <div class="settings-storage" id="settings-storage"></div>
          <div class="settings-actions">
            <button onclick="settingsCleanDb()" title="Remove orphaned rows not linked to any experiment">&#x2702; Clean orphans</button>
            <button onclick="settingsVacuumDb()" title="Checkpoint WAL and compact the database file">&#x1F5DC; Vacuum</button>
            <button class="danger" onclick="settingsResetDb()" title="Delete ALL experiments and data">&#x26A0; Reset DB</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="help-panel" id="help-panel">
  <button class="help-close" onclick="toggleHelp()">&times;</button>
  <h3>Quick Start</h3>
  <div class="help-grid">
    <div class="help-item">
      <strong>Track a script</strong>
      <span><code>exptrack run train.py --lr 0.01</code> &mdash; params captured automatically.</span>
    </div>
    <div class="help-item">
      <strong>Track a notebook</strong>
      <span><code>%load_ext exptrack</code> in first cell &mdash; cells, variables, plots tracked.</span>
    </div>
    <div class="help-item">
      <strong>Shell / SLURM</strong>
      <span><code>eval $(exptrack run-start --lr 0.01)</code> then <code>exptrack run-finish $EXP_ID</code></span>
    </div>
    <div class="help-item">
      <strong>Log metrics</strong>
      <span><code>exp.log_metric("loss", 0.5, step=i)</code> or <code>exptrack log-metric $ID loss 0.5</code></span>
    </div>
  </div>

  <h3>Dashboard Guide</h3>
  <p style="margin-bottom:6px"><strong>Click</strong> an experiment to open it. <strong>Double-click</strong> any name, tag, or note to edit inline. <strong>Checkbox-select</strong> in the sidebar for bulk actions.</p>
  <div class="help-grid">
    <div class="help-item">
      <strong>Overview</strong>
      <span>Params, metrics with chart preview, artifacts, code changes, reproduce command.</span>
    </div>
    <div class="help-item">
      <strong>Charts</strong>
      <span>Interactive metric charts with linear/log scale, zoom, and downsampling.</span>
    </div>
    <div class="help-item">
      <strong>Images</strong>
      <span>Gallery grid with lightbox. Compare: side-by-side, overlay, or swipe.</span>
    </div>
    <div class="help-item">
      <strong>Data Files</strong>
      <span>CSV, JSON, JSONL rendered as sortable interactive tables.</span>
    </div>
    <div class="help-item">
      <strong>Compare</strong>
      <span><em>Pair:</em> side-by-side with overlay charts. <em>Multi:</em> bar charts across 3+ runs.</span>
    </div>
    <div class="help-item">
      <strong>Reproduce</strong>
      <span>One-click copy of the run command. Save to Commands notepad for reuse.</span>
    </div>
  </div>

  <h3>Key Concepts</h3>
  <p style="margin-bottom:2px">
    <strong>Params</strong> &mdash; captured hyperparameters.
    <strong>Metrics</strong> &mdash; logged values tracked per step.
    <strong>Artifacts</strong> &mdash; output files (<code>plt.savefig()</code> auto-captured).
  </p>
  <p style="margin-bottom:2px">
    <strong>Tags</strong> &mdash; labels (<code>baseline</code>, <code>v2</code>).
    <strong>Studies</strong> &mdash; groups of related runs.
    <strong>Stages</strong> &mdash; numbered steps within a study.
  </p>
  <p>
    <strong>Timeline</strong> &mdash; ordered log of cell executions and variable changes (notebooks).
  </p>

  <h3>Toolbar</h3>
  <p>
    <strong>&#9790;</strong> dark mode &nbsp;|&nbsp;
    <strong>&#9881;</strong> columns &amp; settings &nbsp;|&nbsp;
    <strong>&#9745; Todo</strong> &amp; <strong>&gt;_ Cmds</strong> task list and saved commands &nbsp;|&nbsp;
    <strong>&#10133; New</strong> manual experiment &nbsp;|&nbsp;
    <strong>&#9881; Manage</strong> tags &amp; studies
  </p>

  <h3>FAQ</h3>
  <div class="faq-list">
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Does it capture stdout?</div>
      <div class="faq-a">No. Only explicitly logged metrics. Redirect output to a file and register it: <code>exptrack log-artifact &lt;id&gt; train.log</code></div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Can I edit runs after they finish?</div>
      <div class="faq-a">Yes &mdash; name, tags, notes, artifacts, and metrics. Double-click in the dashboard or use the CLI. Params and git state are immutable.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Studies vs. tags?</div>
      <div class="faq-a"><strong>Studies</strong> group related runs (pipeline steps, sweeps). <strong>Tags</strong> are labels (<code>baseline</code>, <code>production</code>). An experiment can have both.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Works without argparse?</div>
      <div class="faq-a">Yes. Falls back to <code>sys.argv</code> parsing. Click, Fire, Typer all work.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Needs internet?</div>
      <div class="faq-a">No. Everything is local. Chart.js loads from CDN but the dashboard works without it.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Performance overhead?</div>
      <div class="faq-a">Negligible. Microseconds for patching, milliseconds for git capture, single SQLite insert per metric.</div>
    </div>
  </div>
</div>

<div id="app-layout">
  <!-- Left: Collapsible experiment list -->
  <div id="exp-sidebar">
    <div class="sidebar-content">
      <div class="sidebar-header">
        <input type="text" id="search-input" placeholder="Search..." oninput="searchQuery=this.value;renderExpList()">
        <button class="collapse-btn" onclick="toggleSidebar()" title="Collapse sidebar">&#8249;</button>
      </div>
      <div class="status-chips" id="status-chips"></div>
      <div id="exp-list"></div>
      <div id="sidebar-actions-bar"></div>
    </div>
    <div class="collapse-strip" onclick="toggleSidebar()">
      <span style="font-size:18px;color:var(--muted)">&#8250;</span>
      <span id="sidebar-count" style="font-size:11px;color:var(--muted);margin-top:8px;writing-mode:vertical-rl"></span>
    </div>
  </div>

  <!-- Center: Main content -->
  <div id="main-content">
    <!-- Welcome state: shown when no experiment selected -->
    <div id="welcome-state">
      <div class="stats" id="stats"></div>
      <div class="table-toolbar">
        <input type="text" id="main-search" class="main-search-input" placeholder="Search experiments..." oninput="searchQuery=this.value;renderExperiments();renderExpList()">
        <div class="toolbar-btn-group">
          <button class="toolbar-btn compare-main-btn" onclick="showCompareView()" title="Compare two experiments">&#x2194; Compare</button>
          <button class="toolbar-btn" onclick="toggleManageDrawer()" title="Manage tags &amp; studies">&#x2699; Manage</button>
          <button class="toolbar-btn" onclick="openNewExpModal()" title="Add manual experiment">&#x2795; New</button>
        </div>
        <div class="tag-filter-bar" id="filter-bar"></div>
      </div>
      <div class="group-bar" id="group-bar">
        <span>Group by:</span>
        <button data-group="git_commit" onclick="setGroup('git_commit')" class="active">Git Commit</button>
        <button data-group="git_branch" onclick="setGroup('git_branch')">Branch</button>
        <button data-group="status" onclick="setGroup('status')">Status</button>
        <button data-group="" onclick="setGroup('')">None</button>
        <span style="margin-left:12px;border-left:1px solid var(--border);padding-left:12px" class="highlight-toggle">
          <label><input type="checkbox" id="highlight-toggle" onchange="toggleHighlightMode(this.checked)"> Highlight by study</label>
        </span>
        <span class="highlight-legend" id="highlight-legend"></span>
      </div>
      <div id="table-actions-bar" class="table-actions-bar" style="display:none"></div>
      <div class="col-settings-bar"><button class="col-settings-btn" onclick="toggleColumnSettings()" title="Show/hide columns">&#x2699; Columns</button><div class="col-settings-panel" id="col-settings-panel"></div></div>
      <div class="table-scroll-wrap"><table id="exp-table"><thead id="exp-thead"></thead><tbody id="exp-body"></tbody></table></div>
    </div>

    <!-- Detail state: shown when an experiment is selected -->
    <div id="detail-view" style="display:none">
      <div id="detail-panel"></div>
    </div>

    <!-- Compare state -->
    <div id="compare-view" style="display:none">
      <div class="compare-header">
        <button class="back-link" onclick="showWelcome()">&larr; Back to experiments</button>
        <h3 style="margin:8px 0 4px">Compare Experiments</h3>
      </div>
      <div class="tabs" style="margin-bottom:12px">
        <button class="tab active" id="compare-pair-tab" onclick="switchCompareTab('pair')">Pair Compare</button>
        <button class="tab" id="compare-multi-tab" onclick="switchCompareTab('multi')">Multi Compare</button>
      </div>
      <div id="compare-pair-content">
        <div class="compare-input">
          <div class="compare-selector">
            <label class="compare-label">base</label>
            <select id="cmp-id1"><option value="">-- Select base experiment --</option></select>
          </div>
          <span class="vs-label">&larr;&rarr;</span>
          <div class="compare-selector">
            <label class="compare-label">compare</label>
            <select id="cmp-id2"><option value="">-- Select compare experiment --</option></select>
          </div>
          <button class="primary" onclick="doCompare()">Compare</button>
        </div>
        <div id="compare-result"></div>
      </div>
      <div id="compare-multi-content" style="display:none">
        <div class="compare-input" style="flex-wrap:wrap;gap:8px">
          <div class="compare-selector" style="flex:1;min-width:300px">
            <label class="compare-label">experiments</label>
            <select id="cmp-multi-select" multiple size="6" style="width:100%;font-size:12px"></select>
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;justify-content:flex-end">
            <button class="primary" onclick="doMultiCompareFromSelector()">Compare Selected</button>
            <button onclick="selectAllMultiCompare()" style="font-size:12px">Select All</button>
          </div>
        </div>
        <p style="color:var(--muted);font-size:12px;margin:4px 0 12px">Hold Ctrl/Cmd to select multiple experiments. Need at least 2.</p>
        <div id="multi-compare-result"></div>
      </div>
    </div>
  </div>
</div>

<div class="toolbox-overlay" id="toolbox-overlay" onclick="closeToolbox()"></div>
<div class="toolbox-drawer" id="toolbox-drawer">
  <div class="toolbox-header">
    <h3 id="toolbox-title">Toolbox</h3>
    <button class="toolbox-close" onclick="closeToolbox()">&times;</button>
  </div>
  <div class="toolbox-tabs">
    <button class="toolbox-tab active" data-tab="todos" onclick="switchToolboxTab('todos')">&#9745; Todos</button>
    <button class="toolbox-tab" data-tab="commands" onclick="switchToolboxTab('commands')">&gt;_ Commands</button>
  </div>
  <div class="toolbox-body">
    <div class="toolbox-panel active" id="toolbox-todos">
      <div class="todo-add-form">
        <div class="todo-add-row">
          <input type="text" id="todo-text-input" placeholder="What needs to be done?" onkeydown="todoAddKeydown(event)">
          <button class="todo-add-btn" onclick="addTodo()">Add</button>
        </div>
        <div class="todo-add-row" style="gap:6px;align-items:center">
          <label for="todo-due-input" style="font-size:13px;color:var(--muted);white-space:nowrap">Due</label>
          <input type="date" id="todo-due-input">
        </div>
        <div class="toolbox-meta-row" id="todo-meta-row"></div>
      </div>
      <div class="todo-filters">
        <span id="todo-status-filters">
          <button class="todo-filter-btn active" data-filter="all" onclick="setTodoFilter('all')">All</button>
          <button class="todo-filter-btn" data-filter="active" onclick="setTodoFilter('active')">Active</button>
          <button class="todo-filter-btn" data-filter="done" onclick="setTodoFilter('done')">Done</button>
        </span>
        <span id="todo-tag-filters"></span>
        <span id="todo-study-filters"></span>
        <span class="todo-count" id="todo-count"></span>
      </div>
      <div class="todo-list" id="todo-list"></div>
    </div>
    <div class="toolbox-panel" id="toolbox-commands">
      <div class="cmd-add-form">
        <input type="text" id="cmd-label-input" placeholder="Label (e.g. Train baseline)" onkeydown="cmdAddKeydown(event)">
        <textarea id="cmd-command-input" rows="2" placeholder="Command (e.g. exptrack run train.py --lr 0.01)" onkeydown="cmdAddKeydown(event)"></textarea>
        <div class="toolbox-meta-row" id="cmd-meta-row"></div>
        <div class="cmd-add-row">
          <button class="cmd-add-btn" onclick="addCmd()">Add Command</button>
        </div>
      </div>
      <div class="cmd-filters">
        <span id="cmd-tag-filters"></span>
        <span id="cmd-study-filters"></span>
      </div>
      <div class="cmd-list" id="cmd-list"></div>
    </div>
  </div>
</div>

<div class="manage-drawer-overlay" id="manage-overlay" onclick="closeManageDrawer()"></div>
<div class="manage-drawer" id="manage-drawer">
  <div class="manage-drawer-header">
    <h3>Manage Tags &amp; Studies</h3>
    <button class="manage-drawer-close" onclick="closeManageDrawer()">&times;</button>
  </div>
  <div class="manage-drawer-body" id="manage-drawer-body"></div>
</div>

<script>
"""

# Document footer (after </script>)
HTML_FOOTER = r"""</script>
</body>
</html>
"""
