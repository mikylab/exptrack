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
    <span class="tz-setting" title="Set timezone for displaying timestamps">
      <select id="tz-select" onchange="setTimezone(this.value)">
        <option value="">TZ: Browser local</option>
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
    </span>
    <button class="theme-btn" id="theme-toggle" onclick="toggleTheme()" title="Toggle dark mode">&#9790;</button>
    <button class="help-btn" onclick="toggleHelp()">? Docs</button>
  </div>
</div>

<div class="help-panel" id="help-panel">
  <button class="help-close" onclick="toggleHelp()">&times;</button>
  <h3>What is exptrack?</h3>
  <p>A zero-friction experiment tracker for ML workflows. It captures parameters, metrics, variables, code changes, and artifacts automatically — no code changes needed.</p>

  <h3>Key Concepts</h3>
  <div class="help-grid">
    <div class="help-item">
      <strong>Params</strong>
      <span>Hyperparameters captured from argparse, CLI flags, or notebook variables (lr, batch_size, etc). These define WHAT you ran.</span>
    </div>
    <div class="help-item">
      <strong>Metrics</strong>
      <span>Numeric values logged during training (loss, accuracy, etc). Tracked per step with min/max/last, visualized as line charts.</span>
    </div>
    <div class="help-item">
      <strong>Variables</strong>
      <span>Notebook variable values captured automatically — scalars, arrays, DataFrames, tensors. Grouped by type (Scalars, Arrays &amp; Tensors, Other).</span>
    </div>
    <div class="help-item">
      <strong>Artifacts</strong>
      <span>Output files (plots, models, CSVs) auto-captured via plt.savefig() or manually. Viewable in-dashboard with image galleries and data file previews.</span>
    </div>
    <div class="help-item">
      <strong>Timeline</strong>
      <span>Ordered log of every cell execution, variable change, and artifact save. Filter by event type. Includes cell lineage viewer and source diffs.</span>
    </div>
    <div class="help-item">
      <strong>Tags &amp; Notes</strong>
      <span>Labels and annotations to organize experiments. Tags have autocomplete; notes support multi-line text. Both are inline-editable.</span>
    </div>
    <div class="help-item">
      <strong>Studies</strong>
      <span>Group related experiments into named studies. Create from selected experiments, add/remove members, rename or delete globally. Highlight by study for visual grouping.</span>
    </div>
    <div class="help-item">
      <strong>Stages</strong>
      <span>Assign a stage number and optional label to experiments (e.g. "1 (preprocessing)", "2 (training)"). Double-click to edit in table or detail view.</span>
    </div>
  </div>

  <h3>Dashboard Views</h3>
  <p><strong>Experiment table:</strong> Main view with sortable columns, status chips, search bar, and tag/study filters. Group by git commit, branch, status, or none. Pin experiments (&#9734;) to keep them at the top. Configure visible columns via the &#9881; Columns button.</p>
  <p><strong>Sidebar:</strong> Collapsible experiment list on the left. Use checkboxes to select experiments for bulk actions (compare, export, add to study, compact, delete). Opens automatically when viewing experiment details.</p>
  <p><strong>Detail view:</strong> Click an experiment to see its full details. Four tabs:</p>
  <p style="margin-left:16px"><strong>Overview</strong> — metadata, params, metrics with interactive charts, variables, artifacts, code changes, and reproduce command.<br>
  <strong>Timeline</strong> — execution events filtered by type (code, variables, artifacts, observational), cell source viewer.<br>
  <strong>Images</strong> — image gallery with side-by-side, overlay (opacity slider), and swipe comparison modes.<br>
  <strong>Data Files</strong> — preview CSV, TSV, JSON, and JSONL artifacts as rendered tables.</p>
  <p><strong>Compare:</strong> Two modes — <em>Pair Compare</em> (side-by-side params, metrics with deltas, overlaid charts, image comparison) and <em>Multi Compare</em> (3+ experiments with bar charts per metric). Use "Show only differences" to hide matching values.</p>

  <h3>Bulk Operations</h3>
  <p>Select experiments via checkboxes, then use the action bar: <strong>Compare</strong> (2+), <strong>Add to Study</strong>, <strong>Export</strong> (JSON, CSV, TSV, Markdown, Plain Text), <strong>Copy</strong> to clipboard, <strong>Compact</strong> (strip diffs to free storage), or <strong>Delete</strong>.</p>

  <h3>Inline Editing</h3>
  <p>Double-click to edit: experiment name, tags (with autocomplete), studies (with autocomplete), notes (Ctrl+Enter to save), stage, script path, and reproduce command. Press <strong>Enter</strong> to save, <strong>Escape</strong> to cancel.</p>

  <h3>Settings</h3>
  <p><strong>Dark mode:</strong> Toggle via the &#9790; button. Preference is saved locally.<br>
  <strong>Timezone:</strong> Select from the TZ dropdown. Applied to all timestamps and saved to project config.<br>
  <strong>Columns:</strong> Show/hide and resize table columns via &#9881; Columns. Preferences saved locally.<br>
  <strong>Highlight mode:</strong> Toggle "Highlight by study" to color-code experiments by study membership.</p>

  <h3>Other Features</h3>
  <p><strong>Manual experiments:</strong> Click &#10133; New to create an experiment by hand — set name, status, date, params, metrics, tags, and notes.<br>
  <strong>Manage drawer:</strong> Click &#9881; Manage for global tag and study management (rename, delete across all experiments).<br>
  <strong>Artifact management:</strong> Add, edit labels/paths, or delete artifacts from the detail view.<br>
  <strong>Metric logging:</strong> Log new metric values directly from the detail view.<br>
  <strong>Hidden experiments:</strong> Hide selected experiments from the table; unhide from the hidden panel.<br>
  <strong>Owl mascot:</strong> Click the owl for tips. Click the speech bubble to dismiss it.</p>

  <h3>Frequently Asked Questions</h3>
  <div class="faq-list">
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">If I run a script and it prints results, will that be logged?</div>
      <div class="faq-a">No. expTrack does not capture stdout/stderr output. Only explicitly logged metrics are recorded. To capture a value, use the <code>__exptrack__</code> global: <code>exp = globals().get("__exptrack__"); exp.log_metric("accuracy", 0.95)</code></div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">What format does my script need for auto-logging?</div>
      <div class="faq-a">Any Python script works &mdash; no format requirements. If your script uses argparse, all arguments are captured automatically. Otherwise, expTrack parses raw sys.argv flags (--key value). The only thing that needs explicit logging is metrics (loss, accuracy, etc.).</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Can I edit runs after they finish?</div>
      <div class="faq-a">Yes. You can edit name, tags, notes, and add artifacts or metrics after a run completes &mdash; via the CLI or by double-clicking in the dashboard. Params and git state are immutable for reproducibility.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Does expTrack work with scripts that don't use argparse?</div>
      <div class="faq-a">Yes. If argparse isn't detected, expTrack parses sys.argv directly. It recognizes --key value and --key=value patterns. Click, Fire, Typer, and manual parsing all work.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Does expTrack capture plots automatically?</div>
      <div class="faq-a">Yes, if you use matplotlib. plt.savefig() is monkey-patched so saved figures are auto-registered as artifacts. Figures saved before the experiment starts are buffered and linked when it begins.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Does expTrack need an internet connection?</div>
      <div class="faq-a">No. Everything is local &mdash; SQLite database, stdlib HTTP server. The only network request is Chart.js from CDN in the dashboard, and the UI still works without it.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">What happens if I rerun the same script?</div>
      <div class="faq-a">A new experiment is created each time. If artifact paths conflict, old artifacts are archived automatically (when protect_on_rerun is enabled). Params and metrics are stored independently per run.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Can I delete experiments?</div>
      <div class="faq-a">Yes. Use <code>exptrack rm &lt;id&gt;</code> for single runs or <code>exptrack clean</code> to bulk-delete failed runs. In the dashboard, select experiments and use the Delete bulk action.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Does expTrack affect my script's performance?</div>
      <div class="faq-a">The overhead is negligible. Argparse patching adds microseconds. Git capture runs once at startup. Metric logging is a single SQLite insert. Large git diffs are capped at 256 KB by default.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Can I use expTrack in Jupyter notebooks?</div>
      <div class="faq-a">Yes. Add <code>%load_ext exptrack</code> in your first cell. Cell executions, variable changes, code diffs, and artifacts are tracked automatically.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">How do I compare experiments?</div>
      <div class="faq-a">CLI: <code>exptrack compare &lt;id1&gt; &lt;id2&gt;</code>. Dashboard: use the Compare button for Pair Compare (2 experiments) or Multi Compare (3+) with bar charts and overlaid line charts.</div>
    </div>
    <div class="faq-item">
      <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">Can I track experiments across multiple machines?</div>
      <div class="faq-a">expTrack is local-first. Each machine has its own database. To aggregate, use <code>exptrack export</code> for JSON, enable the GitHub Sync plugin, or query the SQLite database directly.</div>
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
