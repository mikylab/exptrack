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
    <button class="toolbox-btn" onclick="toggleSessionsTab()" title="Session Trees">&#9783; Sessions</button>
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
          <div class="settings-row">
            <label title="Keep the Todos / Commands panel pinned to the side instead of opening as a popout">Pin Todos / Commands panel</label>
            <input type="checkbox" id="settings-toolbox-pin" onchange="setToolboxPinned(this.checked)">
          </div>
          <div class="settings-row">
            <label title="Write exports to <project>/exports/ instead of downloading via the browser. Existing files are never overwritten — a numeric suffix is added on conflict.">Save exports to project folder</label>
            <input type="checkbox" id="settings-export-to-folder" onchange="setExportToFolder(this.checked)">
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

<div class="help-overlay" id="help-overlay" onclick="toggleHelp()"></div>
<div class="help-drawer" id="help-panel">
  <div class="help-drawer-header">
    <h3>Docs</h3>
    <button class="help-drawer-close" onclick="toggleHelp()">&times;</button>
  </div>
  <div class="help-drawer-body">

  <div class="help-section">
    <h3>Getting Started</h3>
    <p class="help-intro">expTrack captures parameters, git state, and artifacts from your training scripts. Here's how to start tracking experiments.</p>
    <div class="help-steps">
      <div class="help-step">
        <div class="help-step-num">1</div>
        <div class="help-step-body">
          <strong>Track a script</strong>
          <p>Prefix your training command. Parameters from argparse (or CLI flags) are captured automatically.</p>
          <div class="help-cmd">exptrack run train.py --lr 0.01 --epochs 20</div>
        </div>
      </div>
      <div class="help-step">
        <div class="help-step-num">2</div>
        <div class="help-step-body">
          <strong>Log metrics from your script</strong>
          <p>expTrack captures parameters and artifacts, but you need to log metrics explicitly. Inside a script run with <code>exptrack run</code>:</p>
          <div class="help-cmd">exp = globals().get("__exptrack__")
if exp:
    exp.log_metric("loss", 0.42, step=epoch)
    exp.log_metrics({"loss": 0.42, "acc": 0.91}, step=epoch)</div>
        </div>
      </div>
      <div class="help-step">
        <div class="help-step-num">3</div>
        <div class="help-step-body">
          <strong>Track a Jupyter notebook</strong>
          <p>Add this to your first cell. Cells, variables, and plots are tracked across the session.</p>
          <div class="help-cmd">%load_ext exptrack</div>
          <p>Or use the explicit API:</p>
          <div class="help-cmd">import exptrack.notebook as exp
exp.start(lr=0.001)
exp.metric("val/loss", 0.23, step=5)
exp.done()</div>
        </div>
      </div>
      <div class="help-step">
        <div class="help-step-num">4</div>
        <div class="help-step-body">
          <strong>Shell / SLURM pipelines</strong>
          <p>For multi-step workflows or non-Python scripts. Environment variables are set for your pipeline to use.</p>
          <div class="help-cmd">eval $(exptrack run-start --script train.py --lr 0.01)
python train.py --lr 0.01
exptrack log-metric $EXP_ID val_loss 0.234 --step 10
exptrack run-finish $EXP_ID --metrics results.json</div>
        </div>
      </div>
    </div>
  </div>

  <div class="help-section">
    <h3>Using This Dashboard</h3>

    <div class="help-howto">
      <div class="help-howto-item">
        <strong>View an experiment</strong>
        <p>Click any experiment in the sidebar or table to open its detail view. You'll see parameters, metrics, code changes, artifacts, and a reproducible command.</p>
      </div>
      <div class="help-howto-item">
        <strong>Edit names, tags, or notes</strong>
        <p>Double-click any name, tag, or note field to edit it inline. Press Enter to save, Escape to cancel. Tags support autocomplete from previously used values.</p>
      </div>
      <div class="help-howto-item">
        <strong>Compare experiments</strong>
        <p>Click the <strong>&#x2194; Compare</strong> button in the toolbar. <em>Pair Compare</em> shows side-by-side parameters and overlay charts between two runs. <em>Multi Compare</em> shows bar charts across three or more runs.</p>
      </div>
      <div class="help-howto-item">
        <strong>Bulk actions</strong>
        <p>Use the checkboxes in the sidebar to select multiple experiments. A toolbar appears to tag, delete, or add them to a study.</p>
      </div>
      <div class="help-howto-item">
        <strong>Reproduce a run</strong>
        <p>In the detail view, scroll to the Reproduce section. Click the copy button to get the full command. Click <strong>&gt;_ Save</strong> to save it to the Commands notepad.</p>
      </div>
    </div>

    <h4>Tabs in the detail view</h4>
    <table class="help-ref-table">
      <tr><td class="help-ref-key">Overview</td><td>Parameters, metrics with chart preview, artifacts, code changes, and the reproduce command.</td></tr>
      <tr><td class="help-ref-key">Charts</td><td>Full-size metric charts. Use the toolbar to switch between linear and log scale, or adjust downsampling.</td></tr>
      <tr><td class="help-ref-key">Images</td><td>Image artifacts in a gallery grid. Click to enlarge. In Pair Compare, you can overlay or swipe between images.</td></tr>
      <tr><td class="help-ref-key">Data Files</td><td>CSV, TSV, JSON, and JSONL artifacts rendered as interactive tables with sortable columns.</td></tr>
      <tr><td class="help-ref-key">Timeline</td><td>Chronological log of cell executions, variable changes, and artifact saves. Notebook experiments only.</td></tr>
    </table>

    <h4>Header buttons</h4>
    <table class="help-ref-table">
      <tr><td class="help-ref-key">&#9790;</td><td>Toggle dark mode.</td></tr>
      <tr><td class="help-ref-key">&#9745; Todo</td><td>A simple task list saved to your project.</td></tr>
      <tr><td class="help-ref-key">&gt;_ Cmds</td><td>Saved commands. Use &gt;_ Save from any experiment's Reproduce section to add entries here.</td></tr>
      <tr><td class="help-ref-key">&#9881;</td><td>Settings: timezone, metric thinning, database maintenance.</td></tr>
      <tr><td class="help-ref-key">&#x2699; Columns</td><td>Show, hide, or resize table columns.</td></tr>
      <tr><td class="help-ref-key">&#x2699; Manage</td><td>Rename or delete tags and studies across all experiments.</td></tr>
      <tr><td class="help-ref-key">&#x2795; New</td><td>Create an experiment manually (without running a script).</td></tr>
    </table>
  </div>

  <div class="help-section">
    <h3>Key Concepts</h3>
    <table class="help-ref-table">
      <tr><td class="help-ref-key">Params</td><td>Hyperparameters captured from your script's arguments or notebook variables. Immutable after the run starts.</td></tr>
      <tr><td class="help-ref-key">Metrics</td><td>Numeric values you log explicitly (loss, accuracy, etc.). Tracked per step so they can be plotted over time.</td></tr>
      <tr><td class="help-ref-key">Artifacts</td><td>Output files: plots, models, CSVs. <code>plt.savefig()</code> calls are captured automatically.</td></tr>
      <tr><td class="help-ref-key">Tags</td><td>Labels you attach to experiments: <code>baseline</code>, <code>v2</code>, <code>production</code>. Useful for filtering.</td></tr>
      <tr><td class="help-ref-key">Studies</td><td>Groups of related experiments (e.g., pipeline steps or an ablation sweep). Different from tags.</td></tr>
      <tr><td class="help-ref-key">Stages</td><td>Numbered steps within a study, like <em>1: train</em>, <em>2: eval</em>, <em>3: analyze</em>.</td></tr>
    </table>
  </div>

  <div class="help-section">
    <h3>Common Issues</h3>
    <div class="faq-list">
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">My parameters aren't showing up</div>
        <div class="faq-a">
          Make sure you ran the script with <code>exptrack run train.py</code>, not <code>python train.py</code>. expTrack patches argparse before your script runs. If your script doesn't use argparse, CLI flags like <code>--lr 0.01</code> are still captured from <code>sys.argv</code>.
          <div class="help-cmd">exptrack show &lt;id&gt;    # check if params were captured</div>
        </div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">My metrics aren't appearing / charts are empty</div>
        <div class="faq-a">
          expTrack does not capture metrics automatically. You need to log them from your script:
          <div class="help-cmd">exp = globals().get("__exptrack__")
if exp:
    exp.log_metric("loss", loss_value, step=epoch)</div>
          For charts to render, include the <code>step</code> parameter. Without it, only the final value is stored. From the CLI:
          <div class="help-cmd">exptrack log-metric &lt;id&gt; loss 0.42 --step 10</div>
        </div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">How do I log metrics from a shell pipeline?</div>
        <div class="faq-a">
          Use the CLI commands. After starting an experiment with <code>run-start</code>:
          <div class="help-cmd"># Single metric
exptrack log-metric $EXP_ID val_loss 0.234 --step 10

# From a JSON file
exptrack log-metric $EXP_ID --file results.json --step 10

# Or attach metrics when finishing
exptrack run-finish $EXP_ID --metrics results.json</div>
        </div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Experiments aren't showing up at all</div>
        <div class="faq-a">
          expTrack stores data relative to the project root (where you ran <code>exptrack init</code>). If you run scripts from a different directory, it may create a separate <code>.exptrack/</code> folder elsewhere. Run <code>exptrack ls</code> from your project directory to verify.
        </div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Can I edit or delete an experiment after it's done?</div>
        <div class="faq-a">
          <strong>Editable:</strong> name, tags, notes, artifacts, and metrics. Double-click in the dashboard or use the CLI (<code>exptrack tag</code>, <code>exptrack note</code>, <code>exptrack log-metric</code>).<br>
          <strong>Immutable:</strong> parameters and git state, since those represent what was actually run.<br>
          <strong>Delete:</strong> <code>exptrack rm &lt;id&gt;</code> or select experiments in the sidebar and use bulk delete.
        </div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">What's the difference between studies and tags?</div>
        <div class="faq-a">
          <strong>Studies</strong> group experiments that are part of the same workflow: pipeline steps (train &rarr; eval &rarr; analyze), ablation sweeps, or related runs. Use <code>--study</code> on <code>run-start</code> or assign later with <code>exptrack study &lt;id&gt; &lt;name&gt;</code>.<br>
          <strong>Tags</strong> are labels for categorization: <code>baseline</code>, <code>production</code>, <code>needs-review</code>. An experiment can have both.
        </div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">How do I group pipeline steps together?</div>
        <div class="faq-a">
          Use <code>--study</code> and <code>--stage</code> with <code>run-start</code>. Each step is a separate experiment, but they're linked by the study name:
          <div class="help-cmd">eval $(exptrack run-start --script train --study my-run --stage 1 --stage-name train --lr 0.01)
TRAIN_ID=$EXP_ID; python train.py; exptrack run-finish $TRAIN_ID

eval $(exptrack run-start --script eval --study my-run --stage 2 --stage-name eval)
EVAL_ID=$EXP_ID; python eval.py; exptrack run-finish $EVAL_ID</div>
          Filter by study in the sidebar or with <code>exptrack ls --study my-run</code>.
        </div>
      </div>
    </div>
  </div>

  </div>
</div>

<div id="app-layout">
  <!-- Left: Collapsible experiment list -->
  <div id="exp-sidebar">
    <div class="sidebar-content">
      <div class="sidebar-header">
        <input type="text" id="search-input" placeholder="Search..." oninput="searchQuery=this.value;renderExpList()">
        <button class="collapse-btn" id="sidebar-group-study-btn" onclick="toggleSidebarStudyGroup()" title="Group by study">&#9783;</button>
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
        <button data-group="study" onclick="setGroup('study')">Study</button>
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

    <!-- Sessions tab -->
    <div id="sessions-tab">
      <div id="sessions-list">
        <div class="sessions-list-header">
          <h3>Sessions <span id="sessions-updated-stamp" class="sessions-updated-stamp"></span></h3>
          <div class="sessions-list-actions">
            <button class="sessions-refresh-btn" title="Reload sessions" onclick="loadSessionsList()">&#x21bb;</button>
            <button class="sessions-close-btn" title="Close sessions tab" onclick="closeSessionsTab()">&times;</button>
          </div>
        </div>
        <div id="sessions-list-items"></div>
      </div>
      <div id="session-tree-view">
        <div class="session-tree-empty">
          <p><b>Session Trees</b> are an opt-in layer for exploratory notebook work — they record the shape of your thinking as a navigable tree.</p>
          <p>To start one, run in a notebook:</p>
          <pre style="margin:8px 0;font-family:'IBM Plex Mono',monospace;font-size:12px">%load_ext exptrack
%exptrack session start "exploring threshold sensitivity"
%exptrack checkpoint "after preprocessing clean"
%exptrack branch "try threshold 0.7"</pre>
          <p>Use <code>%%scratch</code> to mark cells you want excluded from logging.</p>
        </div>
      </div>
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
  <div class="toolbox-resize-handle" id="toolbox-resize-handle" onmousedown="startToolboxResize(event)" title="Drag to resize"></div>
  <div class="toolbox-header">
    <h3 id="toolbox-title">Toolbox</h3>
    <div class="toolbox-header-actions">
      <button class="toolbox-pin-btn" id="toolbox-pin-btn" onclick="toggleToolboxPin()" title="Pin as persistent side panel">&#128204;</button>
      <button class="toolbox-close" onclick="closeToolbox()">&times;</button>
    </div>
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
      <div class="toolbox-export-row">
        <button class="toolbox-export-btn" onclick="exportTodos('md')" title="Download as Markdown">&#x2913; .md</button>
        <button class="toolbox-export-btn" onclick="exportTodos('txt')" title="Download as plain text">&#x2913; .txt</button>
        <button class="toolbox-export-btn" onclick="exportTodos('json')" title="Download as JSON">&#x2913; .json</button>
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
      <div class="toolbox-export-row">
        <button class="toolbox-export-btn" onclick="exportCommands('sh')" title="Download as shell script">&#x2913; .sh</button>
        <button class="toolbox-export-btn" onclick="exportCommands('md')" title="Download as Markdown">&#x2913; .md</button>
        <button class="toolbox-export-btn" onclick="exportCommands('json')" title="Download as JSON">&#x2913; .json</button>
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
