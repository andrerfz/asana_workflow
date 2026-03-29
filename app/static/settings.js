// ════════ SETTINGS MODAL ════════

function openSettings() {
  document.getElementById('settingsModal').style.display = 'flex';
  switchSettingsTab('repos');
}
function closeSettings() {
  document.getElementById('settingsModal').style.display = 'none';
}

function switchSettingsTab(tab, btn) {
  _settingsTab = tab;
  document.querySelectorAll('.modal-tab').forEach(t => t.classList.remove('active'));
  if (btn) btn.classList.add('active');
  else document.querySelectorAll('.modal-tab').forEach(t => { if (t.textContent.toLowerCase().includes(tab)) t.classList.add('active'); });

  if (tab === 'repos') renderReposTab();
  else if (tab === 'ide') renderIDETab();
  else if (tab === 'mapping') renderMappingTab();
  else if (tab === 'agent') renderAgentTab();
  else if (tab === 'guides') renderGuidesTab();
  else if (tab === 'workflow') renderWorkflowTab();
}

async function renderReposTab() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="spinner"></div>';
  try {
    const [res, cfgRes] = await Promise.all([fetch('/api/repos'), fetch('/api/repos/config')]);
    const data = await res.json();
    const cfg = await cfgRes.json();
    _projectsDir = cfg.projects_dir || '';

    let html = '';

    html += `<div class="settings-section"><h3>Projects Directory</h3>`;
    if (_projectsDir) {
      html += `<div class="repo-card" style="border-color:var(--green)">
        <span class="health-dot clean"></span>
        <div class="repo-info">
          <div class="repo-id" style="font-family:monospace">${esc(_projectsDir)}</div>
          <div class="repo-meta"><span>All repos must be under this directory</span></div>
        </div>
        <button class="btn" onclick="scanAndShowRepos()" style="font-size:12px">Scan for Repos</button>
      </div>`;
    } else {
      html += `<div class="repo-card" style="border-color:var(--red)">
        <span class="health-dot error"></span>
        <div class="repo-info">
          <div class="repo-id" style="color:var(--red)">PROJECTS_DIR not configured</div>
          <div class="repo-meta"><span>Add PROJECTS_DIR=/path/to/your/projects to .env and restart</span></div>
        </div>
      </div>`;
    }
    html += `</div>`;

    html += `<div class="settings-section"><h3>Configured Repositories</h3>`;
    if (data.repos.length === 0) {
      html += `<p style="color:var(--text2);font-size:13px">No repositories configured yet. ${_projectsDir ? 'Click "Scan for Repos" above or add one manually.' : 'Configure PROJECTS_DIR first.'}</p>`;
    }
    data.repos.forEach(r => {
      const hc = r.health?.status || 'unknown';
      html += `<div class="repo-card">
        <span class="health-dot ${hc}" title="${r.health?.details || ''}"></span>
        <div class="repo-info">
          <div class="repo-id">${r.id}</div>
          <div class="repo-path">${r.path}</div>
          <div class="repo-meta">
            <span>Branch: ${r.default_branch}</span>
            <span>Lang: ${r.language}</span>
            ${r.test_worktree_cmd ? `<span>Test (Worktree): ${r.test_worktree_cmd}</span>` : r.test_docker_cmd ? `<span>Test (Docker): ${r.test_docker_cmd}</span>` : r.test_cmd ? `<span>Test: ${r.test_cmd}</span>` : ''}
            ${r.test_description ? `<span style="color:var(--text2);font-style:italic">AI: ${r.test_description.slice(0,80)}${r.test_description.length>80?'...':''}</span>` : ''}
          </div>
        </div>
        <div class="repo-actions">
          <button class="btn-icon" onclick="editRepo('${r.id}')" title="Edit">&#9998;</button>
          <button class="btn-icon" onclick="deleteRepo('${r.id}')" title="Delete" style="color:var(--red)">&#10005;</button>
        </div>
      </div>`;
    });
    html += `</div>`;
    html += `<button class="btn btn-primary" onclick="showRepoForm()">+ Add Repository</button>`;
    html += `<div id="repoFormContainer"></div>`;
    html += `<div id="scanResults"></div>`;
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">Error loading repos: ${e.message}</p>`;
  }
}

async function scanAndShowRepos() {
  const container = document.getElementById('scanResults');
  container.innerHTML = '<div class="spinner" style="margin:12px 0"></div>';
  try {
    const [scanRes, reposRes] = await Promise.all([fetch('/api/repos/scan'), fetch('/api/repos')]);
    const scan = await scanRes.json();
    const existing = await reposRes.json();
    const existingPaths = new Set(existing.repos.map(r => r.path));

    const available = scan.repos.filter(r => !existingPaths.has(r.path));
    if (available.length === 0) {
      container.innerHTML = `<p style="color:var(--text2);font-size:13px;margin-top:12px">All git repos under ${esc(_projectsDir)} are already configured.</p>`;
      return;
    }

    let html = `<div class="settings-section" style="margin-top:16px"><h3>Found ${available.length} unconfigured repos</h3>`;
    available.forEach(r => {
      const suggestedId = r.name.toLowerCase().replace(/[^a-z0-9_-]/g, '-');
      html += `<div class="repo-card">
        <span class="health-dot clean"></span>
        <div class="repo-info">
          <div class="repo-id">${esc(r.name)}</div>
          <div class="repo-path">${esc(r.path)}</div>
          <div class="repo-meta"><span>Lang: ${r.language}</span></div>
        </div>
        <button class="btn btn-primary" onclick="quickAddRepo('${suggestedId}','${r.path}')" style="font-size:12px">+ Add</button>
      </div>`;
    });
    html += `</div>`;
    container.innerHTML = html;
  } catch (e) {
    container.innerHTML = `<p style="color:var(--red)">Scan error: ${e.message}</p>`;
  }
}

async function quickAddRepo(id, path) {
  try {
    const res = await fetch(`/api/repos/${id}`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ path, default_branch: 'master', language: 'auto' })
    });
    if (!res.ok) throw new Error(await res.text());
    showToast(`Repo "${id}" added`);
    renderReposTab();
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

function showRepoForm(existing = null) {
  const c = document.getElementById('repoFormContainer');
  const v = existing || { id: '', path: '', default_branch: 'master', test_cmd: '', test_docker_cmd: '', test_worktree_cmd: '', test_worktree_cmd_fast: '', test_description: '', build_cmd: '', lint_cmd: '', language: 'auto', context_files: [] };
  c.innerHTML = `
    <div class="settings-section" style="margin-top:16px;padding:16px;background:var(--surface2);border-radius:8px">
      <h3>${existing ? 'Edit' : 'Add'} Repository</h3>
      <div class="form-row">
        <div class="form-group"><label>ID (unique key)</label>
          <input class="form-input" id="repoId" value="${v.id}" ${existing ? 'disabled' : ''} placeholder="back-clientes">
        </div>
        <div class="form-group"><label>Path</label>
          <input class="form-input" id="repoPath" value="${v.path}" placeholder="${_projectsDir ? _projectsDir + '/my-repo' : '/path/to/repo'}">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Default Branch</label>
          <input class="form-input" id="repoBranch" value="${v.default_branch}" placeholder="master">
        </div>
        <div class="form-group"><label>Language</label>
          <input class="form-input" id="repoLang" value="${v.language}" placeholder="auto">
        </div>
      </div>
      <div class="form-row">
        <div class="form-group"><label>Test Command (local)</label>
          <textarea class="form-input" id="repoTest" rows="2" placeholder="make test">${v.test_cmd || ''}</textarea>
        </div>
        <div class="form-group"><label>Build Command</label>
          <textarea class="form-input" id="repoBuild" rows="2" placeholder="make build">${v.build_cmd || ''}</textarea>
        </div>
      </div>
      <div class="form-group"><label>Test Command (Docker) — runs from project root via docker compose exec</label>
        <textarea class="form-input" id="repoTestDocker" rows="3" placeholder="docker compose exec laravel.test vendor/bin/paratest --processes=4 --stop-on-failure">${v.test_docker_cmd || ''}</textarea>
      </div>
      <div class="form-group"><label>Test Command (Worktree) — runs from worktree dir, preferred over others when set</label>
        <textarea class="form-input" id="repoTestWorktree" rows="3" placeholder="make agent-test">${v.test_worktree_cmd || ''}</textarea>
      </div>
      <div class="form-group"><label>Test Command (Worktree Fast) — used when no migration files detected, skips DB migrations</label>
        <textarea class="form-input" id="repoTestWorktreeFast" rows="2" placeholder="make agent-test-no-migration">${v.test_worktree_cmd_fast || ''}</textarea>
      </div>
      <div class="form-group"><label>Test Description — instructions for the AI agent about how/when to run tests</label>
        <textarea class="form-input" id="repoTestDesc" rows="3" placeholder="e.g. Use 'make agent-test' for full tests (runs migrations). Use 'make agent-test-no-migration' when your changes don't involve database migrations (faster).">${v.test_description || ''}</textarea>
      </div>
      <div class="form-group"><label>Lint Command</label>
        <textarea class="form-input" id="repoLint" rows="2" placeholder="make lint">${v.lint_cmd || ''}</textarea>
      </div>
      <div class="form-group"><label>Context Files (comma-separated paths relative to repo root)</label>
        <input class="form-input" id="repoContext" value="${(v.context_files || []).join(', ')}" placeholder="docs/schema.sql, src/types.ts">
      </div>
      <div class="form-actions">
        <button class="btn" onclick="document.getElementById('repoFormContainer').innerHTML=''">Cancel</button>
        <button class="btn btn-primary" onclick="saveRepo()">Save</button>
      </div>
    </div>`;
}

async function saveRepo() {
  const id = document.getElementById('repoId').value.trim();
  const payload = {
    path: document.getElementById('repoPath').value.trim(),
    default_branch: document.getElementById('repoBranch').value.trim() || 'master',
    language: document.getElementById('repoLang').value.trim() || 'auto',
    test_cmd: document.getElementById('repoTest').value.trim() || null,
    test_docker_cmd: document.getElementById('repoTestDocker').value.trim() || null,
    test_worktree_cmd: document.getElementById('repoTestWorktree').value.trim() || null,
    test_worktree_cmd_fast: document.getElementById('repoTestWorktreeFast').value.trim() || null,
    test_description: document.getElementById('repoTestDesc').value.trim() || null,
    build_cmd: document.getElementById('repoBuild').value.trim() || null,
    lint_cmd: document.getElementById('repoLint').value.trim() || null,
    context_files: document.getElementById('repoContext').value.split(',').map(s => s.trim()).filter(Boolean),
  };
  if (!id || !payload.path) { showToast('ID and Path are required', 'error'); return; }
  try {
    const res = await fetch(`/api/repos/${id}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    if (!res.ok) throw new Error(await res.text());
    showToast(`Repo "${id}" saved`);
    renderReposTab();
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function saveAgentSettings() {
  const timeoutEl = document.getElementById('agentTimeout');
  const timeout = timeoutEl ? Math.max(10, Math.min(180, parseInt(timeoutEl.value) || 45)) : 45;
  const payload = {
    section_on_start: document.getElementById('agentSectionStart').value.trim() || null,
    section_on_done: document.getElementById('agentSectionDone').value.trim() || null,
    section_on_error: document.getElementById('agentSectionError').value.trim() || null,
    agent_timeout_minutes: timeout,
  };
  try {
    const res = await fetch('/api/agent/settings', { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload) });
    if (!res.ok) throw new Error(await res.text());
    const status = document.getElementById('agentSettingsStatus');
    status.style.display = 'inline';
    setTimeout(() => { status.style.display = 'none'; }, 2000);
    showToast('Agent settings saved');
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function editRepo(id) {
  try {
    const res = await fetch(`/api/repos/${id}`);
    const repo = await res.json();
    showRepoForm(repo);
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function deleteRepo(id) {
  if (!confirm(`Delete repo "${id}"?`)) return;
  try {
    const res = await fetch(`/api/repos/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(await res.text());
    showToast(`Repo "${id}" deleted`);
    renderReposTab();
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

function renderIDETab() {
  const body = document.getElementById('settingsBody');
  const current = getIDEPreference();
  let html = `<div class="settings-section"><h3>Preferred IDE</h3>
    <p style="color:var(--text2);font-size:13px;margin-bottom:12px">Select the IDE used to open worktrees when reviewing agent changes.</p>`;
  IDE_OPTIONS.forEach(ide => {
    const sel = current.id === ide.id ? 'selected' : '';
    html += `<div class="ide-option ${sel}" onclick="selectIDE('${ide.id}')">
      <div><div class="ide-name">${ide.name}</div><div class="ide-protocol">${ide.protocol}</div></div>
    </div>`;
  });
  html += `</div>`;
  html += `<div class="settings-section"><h3>Custom Protocol</h3>
    <div class="form-group"><label>URI Template (use {path} as placeholder)</label>
      <input class="form-input" id="customProtocol" value="${current.id === 'custom' ? current.protocol : ''}" placeholder="myide://open?file={path}">
    </div>
    <button class="btn" onclick="selectCustomIDE()">Use Custom</button>
  </div>`;
  body.innerHTML = html;
}

function selectIDE(id) {
  const ide = IDE_OPTIONS.find(i => i.id === id);
  if (ide) { saveIDEPreference(ide); renderIDETab(); showToast(`IDE set to ${ide.name}`); }
}
function selectCustomIDE() {
  const proto = document.getElementById('customProtocol').value.trim();
  if (!proto || !proto.includes('{path}')) { showToast('Protocol must contain {path}', 'error'); return; }
  saveIDEPreference({ id: 'custom', name: 'Custom', protocol: proto });
  renderIDETab();
  showToast('Custom IDE saved');
}

async function renderMappingTab() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="spinner"></div>';
  try {
    const [mapRes, reposRes] = await Promise.all([fetch('/api/repos/mapping/areas'), fetch('/api/repos')]);
    const mapData = await mapRes.json();
    const reposData = await reposRes.json();
    const mapping = mapData.area_repo_map || {};
    const availableRepos = reposData.repos || [];

    let html = `<div class="settings-section"><h3>Area &rarr; Repository Mapping</h3>
      <p style="color:var(--text2);font-size:13px;margin-bottom:12px">
        Map task areas (from classifier) to repositories. The agent auto-assigns repos to tasks based on this.
        ${availableRepos.length === 0 ? '<br><strong style="color:var(--orange)">Add repositories first in the Repositories tab.</strong>' : ''}
      </p>`;

    for (const [area, repos] of Object.entries(mapping)) {
      html += `<div class="repo-card" style="flex-wrap:wrap">
        <div class="repo-info" style="min-width:140px">
          <div class="repo-id">${area}</div>
        </div>
        <div style="flex:1;display:flex;gap:6px;flex-wrap:wrap;align-items:center">`;

      availableRepos.forEach(r => {
        const checked = repos.includes(r.id) ? 'checked' : '';
        html += `<label style="display:flex;align-items:center;gap:4px;font-size:12px;cursor:pointer;padding:4px 8px;border-radius:4px;background:var(--bg);border:1px solid var(--border)">
          <input type="checkbox" data-area="${area}" data-repo="${r.id}" ${checked}
            onchange="updateAreaMapping('${area}')" style="accent-color:var(--accent)">
          ${r.id}
        </label>`;
      });

      if (availableRepos.length === 0) {
        html += `<span style="font-size:12px;color:var(--text2);font-style:italic">No repos available</span>`;
      }

      html += `</div></div>`;
    }
    html += `</div>`;
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

async function updateAreaMapping(area) {
  const checkboxes = document.querySelectorAll(`input[data-area="${area}"]`);
  const selectedRepos = [];
  checkboxes.forEach(cb => { if (cb.checked) selectedRepos.push(cb.dataset.repo); });
  try {
    const res = await fetch(`/api/repos/mapping/areas/${area}`, {
      method: 'PUT', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ repo_ids: selectedRepos })
    });
    if (!res.ok) throw new Error(await res.text());
    showToast(`${area} → ${selectedRepos.join(', ') || 'none'}`);
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

async function renderAgentTab() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="spinner"></div>';
  try {
    const res = await fetch('/api/agent/cli-status');
    const cli = await res.json();

    let html = '';

    html += `<div class="settings-section"><h3>Claude Code CLI</h3>`;
    if (cli.available) {
      const authColor = cli.authenticated ? 'var(--green)' : 'var(--orange)';
      const authDot = cli.authenticated ? 'clean' : 'dirty';
      html += `<div class="repo-card" style="border-color:${authColor}">
        <span class="health-dot ${authDot}"></span>
        <div class="repo-info">
          <div class="repo-id">Claude Code ${esc(cli.version || '')}</div>
          <div class="repo-meta"><span>Path: ${esc(cli.path || '')}</span></div>
          <div class="repo-meta" style="margin-top:4px">
            <span style="color:${authColor}">${cli.authenticated ? 'Authenticated — uses your claude.ai subscription' : 'Not authenticated'}</span>
          </div>
        </div>
      </div>`;

      if (!cli.authenticated) {
        html += `<div style="margin-top:12px;padding:12px;background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);border-radius:8px;font-size:13px;color:var(--text2)">
          <p style="margin-bottom:8px"><strong style="color:var(--orange)">Login required</strong></p>
          <p>Run this on your <strong style="color:var(--text)">Mac terminal</strong> (not inside Docker):</p>
          <code style="display:block;background:var(--bg);padding:6px 10px;border-radius:4px;margin:8px 0;font-size:12px">claude login</code>
          <p>This opens a browser to authenticate with your claude.ai account. After login, restart the container:</p>
          <code style="display:block;background:var(--bg);padding:6px 10px;border-radius:4px;margin:8px 0;font-size:12px">make recreate</code>
          <p style="margin-top:8px;font-size:11px;color:var(--text2)">Your credentials at <code>~/.claude/</code> are mounted read-only into the container.</p>
        </div>`;
      }
    } else {
      html += `<div class="repo-card" style="border-color:var(--red)">
        <span class="health-dot error"></span>
        <div class="repo-info">
          <div class="repo-id" style="color:var(--red)">Claude Code CLI not installed</div>
          <div class="repo-meta"><span>${esc(cli.error || 'Unknown error')}</span></div>
        </div>
      </div>`;
      html += `<div style="margin-top:12px;padding:12px;background:var(--surface2);border-radius:8px;font-size:13px;color:var(--text2)">
        <p style="margin-bottom:8px"><strong style="color:var(--text)">Setup instructions:</strong></p>
        <p>1. Install Claude Code on your Mac:</p>
        <code style="display:block;background:var(--bg);padding:6px 10px;border-radius:4px;margin:4px 0 8px;font-size:12px">npm install -g @anthropic-ai/claude-code</code>
        <p>2. Login to your claude.ai account:</p>
        <code style="display:block;background:var(--bg);padding:6px 10px;border-radius:4px;margin:4px 0 8px;font-size:12px">claude login</code>
        <p>3. Rebuild the container:</p>
        <code style="display:block;background:var(--bg);padding:6px 10px;border-radius:4px;margin:4px 0;font-size:12px">make recreate</code>
      </div>`;
    }
    html += `</div>`;

    html += `<div class="settings-section"><h3>How billing works</h3>
      <div style="font-size:13px;color:var(--text2);line-height:1.6">
        <p><strong style="color:var(--accent2)">AI Agent (coding)</strong> → Claude Code CLI → your <strong style="color:var(--text)">claude.ai subscription</strong> (Pro/Max)</p>
        <p style="margin-top:4px"><strong style="color:var(--accent2)">Dashboard AI (classify, summaries)</strong> → Anthropic API → <strong style="color:var(--text)">ANTHROPIC_API_KEY</strong> (pay-per-token)</p>
      </div>
    </div>`;

    let agentSettings = {};
    try {
      const settingsRes = await fetch('/api/agent/settings');
      agentSettings = await settingsRes.json();
    } catch (e) {}

    const sectionNames = allSections.map(s => s.name);

    html += `<div class="settings-section"><h3>Asana Section Mapping</h3>
      <div style="font-size:13px;color:var(--text2);margin-bottom:12px">
        Configure which Asana sections the agent moves tasks to during its workflow.
      </div>
      <div style="display:flex;flex-direction:column;gap:10px">
        <div>
          <label style="font-size:12px;color:var(--text2);display:block;margin-bottom:4px">On Start (agent begins working)</label>
          <input id="agentSectionStart" type="text" value="${esc(agentSettings.section_on_start || '')}"
            placeholder="e.g. In Progress" list="sectionSuggestions"
            style="width:100%;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text2);display:block;margin-bottom:4px">On Done (agent finished)</label>
          <input id="agentSectionDone" type="text" value="${esc(agentSettings.section_on_done || '')}"
            placeholder="e.g. Code Review" list="sectionSuggestions"
            style="width:100%;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px">
        </div>
        <div>
          <label style="font-size:12px;color:var(--text2);display:block;margin-bottom:4px">On Error (optional)</label>
          <input id="agentSectionError" type="text" value="${esc(agentSettings.section_on_error || '')}"
            placeholder="Leave empty to skip" list="sectionSuggestions"
            style="width:100%;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px">
        </div>
      </div>
      <datalist id="sectionSuggestions">
        ${sectionNames.map(n => `<option value="${esc(n)}">`).join('')}
      </datalist>
      <button onclick="saveAgentSettings()" style="margin-top:12px;padding:6px 16px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px">Save Section Mapping</button>
      <span id="agentSettingsStatus" style="margin-left:8px;font-size:12px;color:var(--green);display:none">Saved!</span>
    </div>`;

    html += `<div class="settings-section"><h3>Agent Timeout</h3>
      <div style="font-size:13px;color:var(--text2);margin-bottom:12px">
        Maximum active work time (excludes time waiting for your approval/answers).
      </div>
      <div style="display:flex;align-items:center;gap:8px">
        <input id="agentTimeout" type="number" min="10" max="180" step="5"
          value="${agentSettings.agent_timeout_minutes || 45}"
          style="width:80px;padding:6px 10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px">
        <span style="font-size:13px;color:var(--text2)">minutes</span>
      </div>
    </div>`;

    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">Error: ${e.message}</p>`;
  }
}

// ════════ CLAUDE.md GUIDES ════════

async function renderGuidesTab() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="spinner"></div>';
  try {
    const resp = await fetch('/api/guides');
    const guides = await resp.json();
    let html = '<div class="settings-section"><h3>CLAUDE.md Guides</h3>'
      + '<p style="font-size:12px;color:var(--text2);margin-bottom:12px">'
      + 'These guides are loaded during the Investigation phase to help the agent understand your projects. '
      + 'The Global guide describes cross-project relationships. Per-repo guides are read from each repository\'s CLAUDE.md file.</p>';

    for (const g of guides) {
      const badge = g.type === 'global'
        ? '<span style="background:#0ea5e9;color:#fff;padding:2px 6px;border-radius:4px;font-size:10px;margin-left:6px">GLOBAL</span>'
        : '<span style="background:var(--surface2);color:var(--text2);padding:2px 6px;border-radius:4px;font-size:10px;margin-left:6px">' + esc(g.id) + '</span>';
      const exists = g.content !== null;
      html += '<div class="form-group" style="margin-bottom:16px">'
        + '<label style="font-weight:600;font-size:13px">' + esc(g.label) + badge + '</label>'
        + '<textarea class="form-input" id="guide-' + esc(g.id) + '" rows="12"'
        + ' style="font-family:monospace;font-size:12px;white-space:pre;resize:vertical"'
        + ' placeholder="' + (exists ? '' : 'No CLAUDE.md file found. Create one by typing content here and saving.') + '"'
        + '>' + (exists ? esc(g.content) : '') + '</textarea>'
        + '<div class="form-actions" style="margin-top:6px">'
        + '<button class="btn btn-sm" onclick="saveGuide(\'' + esc(g.id) + '\')">Save</button>'
        + '</div></div>';
    }

    html += '</div>';
    body.innerHTML = html;
  } catch (e) {
    body.textContent = 'Error loading guides: ' + e.message;
  }
}

async function saveGuide(guideId) {
  const textarea = document.getElementById('guide-' + guideId);
  if (!textarea) return;
  try {
    const resp = await fetch('/api/guides/' + guideId, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: textarea.value }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    showToast('Guide saved');
  } catch (e) {
    showToast('Error saving guide: ' + e.message, 'error');
  }
}

// ════════ WORKFLOW VISUALIZATION ════════

async function renderWorkflowTab() {
  const body = document.getElementById('settingsBody');
  body.innerHTML = '<div class="spinner"></div>';

  try {
    const res = await fetch('/api/agent/workflow');
    if (!res.ok) throw new Error(await res.text());
    const graph = await res.json();
    _renderWorkflowGraph(body, graph);
  } catch (e) {
    body.innerHTML = `<p style="color:var(--red)">Failed to load workflow: ${esc(e.message)}</p>`;
  }
}

function _renderWorkflowGraph(container, graph) {
  const nodes = graph.nodes || [];
  const edges = graph.edges || [];

  const NW = 140, NH = 58, PAD_X = 50, PAD_Y = 40, GAP_X = 40, GAP_Y = 50;
  const maxCol = Math.max(...nodes.map(n => n.col ?? 0));
  const maxRow = Math.max(...nodes.map(n => n.row ?? 0));
  const SVG_W = PAD_X * 2 + (maxCol + 1) * (NW + GAP_X) - GAP_X;
  const SVG_H = PAD_Y * 2 + (maxRow + 1) * (NH + GAP_Y) - GAP_Y;

  const laid = nodes.map(n => ({
    ...n,
    x: PAD_X + (n.col ?? 0) * (NW + GAP_X),
    y: PAD_Y + (n.row ?? 0) * (NH + GAP_Y),
  }));
  const nodeMap = {};
  laid.forEach(n => nodeMap[n.id] = n);

  let svg = `<svg viewBox="0 0 ${SVG_W} ${SVG_H}" xmlns="http://www.w3.org/2000/svg"
    style="width:100%;height:auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">`;

  svg += `<defs>
    <marker id="wf-arr" viewBox="0 0 10 6" refX="10" refY="3" markerWidth="8" markerHeight="6" orient="auto-start-reverse">
      <path d="M0,0 L10,3 L0,6 z" fill="#8b90a5"/>
    </marker>
    <marker id="wf-arr-err" viewBox="0 0 10 6" refX="10" refY="3" markerWidth="6" markerHeight="4" orient="auto-start-reverse">
      <path d="M0,0 L10,3 L0,6 z" fill="#ef4444" opacity="0.5"/>
    </marker>
    <marker id="wf-arr-warn" viewBox="0 0 10 6" refX="10" refY="3" markerWidth="6" markerHeight="4" orient="auto-start-reverse">
      <path d="M0,0 L10,3 L0,6 z" fill="#eab308" opacity="0.5"/>
    </marker>
    <filter id="wf-glow"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>`;

  svg += `<rect width="${SVG_W}" height="${SVG_H}" rx="12" fill="#0f1117"/>`;
  for (let gx = 20; gx < SVG_W; gx += 30)
    for (let gy = 20; gy < SVG_H; gy += 30)
      svg += `<circle cx="${gx}" cy="${gy}" r="0.5" fill="#2d3148"/>`;

  edges.forEach(e => {
    const from = nodeMap[e.from], to = nodeMap[e.to];
    if (!from || !to) return;

    const isErr = e.type === 'error';
    const isPause = e.type === 'pause';
    const isLoop = e.type === 'loop';
    const isDashed = isErr || isPause || isLoop;
    const stroke = isErr ? '#ef4444' : isPause ? '#eab308' : 'rgba(139,144,165,0.5)';
    const marker = isErr ? 'url(#wf-arr-err)' : isPause ? 'url(#wf-arr-warn)' : 'url(#wf-arr)';
    const opacity = isDashed && (isErr || isPause) ? '0.35' : isDashed ? '0.5' : '0.7';

    const fc = { x: from.x + NW / 2, y: from.y + NH / 2 };
    const tc = { x: to.x + NW / 2, y: to.y + NH / 2 };
    const dx = tc.x - fc.x, dy = tc.y - fc.y;

    let path;
    if (Math.abs(dy) < 20) {
      if (dx > 0) {
        path = `M${from.x + NW} ${fc.y} L${to.x} ${tc.y}`;
      } else {
        const midY = Math.min(fc.y, tc.y) - 30;
        path = `M${fc.x} ${from.y} Q${fc.x} ${midY} ${(fc.x+tc.x)/2} ${midY} Q${tc.x} ${midY} ${tc.x} ${to.y}`;
      }
    } else if (Math.abs(dx) < 20) {
      path = `M${fc.x} ${from.y + NH} L${tc.x} ${to.y}`;
    } else {
      if (dy > 0) {
        path = `M${fc.x} ${from.y + NH} L${fc.x} ${tc.y} L${to.x} ${tc.y}`;
      } else {
        const midY = from.y - 20;
        path = `M${fc.x} ${from.y} L${fc.x} ${midY} L${tc.x} ${midY} L${tc.x} ${to.y + NH}`;
      }
    }

    svg += `<path d="${path}" fill="none" stroke="${stroke}" stroke-width="${isDashed ? 1.5 : 2}"
      ${isDashed ? 'stroke-dasharray="6,4"' : ''} opacity="${opacity}" marker-end="${marker}"/>`;

    if (e.label) {
      const mx = (fc.x + tc.x) / 2, my = (fc.y + tc.y) / 2 - 6;
      svg += `<text x="${mx}" y="${my}" text-anchor="middle" fill="${stroke}" font-size="9" opacity="0.8">${e.label}</text>`;
    }
  });

  laid.forEach(n => {
    svg += `<g class="wf-node" data-id="${n.id}" style="cursor:pointer">`;
    svg += `<rect x="${n.x+2}" y="${n.y+2}" width="${NW}" height="${NH}" rx="10" fill="rgba(0,0,0,0.3)"/>`;
    svg += `<rect class="wf-node-bg" x="${n.x}" y="${n.y}" width="${NW}" height="${NH}" rx="10" fill="#1a1d27" stroke="${n.color}" stroke-width="2"/>`;
    svg += `<text x="${n.x+NW/2}" y="${n.y+23}" text-anchor="middle" fill="${n.color}" font-size="14">${n.icon}</text>`;
    svg += `<text x="${n.x+NW/2}" y="${n.y+42}" text-anchor="middle" fill="#e1e4ed" font-size="11" font-weight="600">${n.label}</text>`;
    svg += `</g>`;
  });

  svg += `</svg>`;

  const legend = `<div class="wf-legend">
    <span class="wf-legend-item"><span class="wf-legend-line solid"></span> Main flow</span>
    <span class="wf-legend-item"><span class="wf-legend-line dashed"></span> Loop / retry</span>
    <span class="wf-legend-item"><span class="wf-legend-line dashed error"></span> Error path</span>
    <span class="wf-legend-item"><span class="wf-legend-line dashed pause"></span> Pause / resume</span>
  </div>`;

  container.innerHTML = `<div class="wf-container">
    <div class="wf-diagram">${svg}</div>
    ${legend}
    <div class="wf-detail" id="wfDetail">
      <div class="wf-detail-placeholder">Click a node to see details</div>
    </div>
  </div>`;

  container.querySelectorAll('.wf-node').forEach(el => {
    el.addEventListener('click', () => {
      const node = laid.find(n => n.id === el.dataset.id);
      if (!node) return;
      container.querySelectorAll('.wf-node-bg').forEach(r => { r.setAttribute('stroke-width', '2'); r.removeAttribute('filter'); });
      el.querySelector('.wf-node-bg').setAttribute('stroke-width', '3');
      el.querySelector('.wf-node-bg').setAttribute('filter', 'url(#wf-glow)');

      document.getElementById('wfDetail').innerHTML = `
        <div class="wf-detail-header" style="border-left:3px solid ${node.color};padding-left:10px">
          <span style="font-size:20px">${node.icon}</span>
          <span style="font-weight:600;font-size:15px">${node.label}</span>
        </div>
        <div class="wf-detail-body">
          ${(node.desc||'').split('\n').map(l => `<div class="wf-detail-line">${esc(l)}</div>`).join('')}
        </div>`;
    });
  });
}
