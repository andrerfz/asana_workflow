// ════════ DATA FETCHING ════════

let _fetchingTasks = false;
async function fetchTasks(force = false) {
  if (_fetchingTasks) return;
  _fetchingTasks = true;
  const btn = document.getElementById('refreshBtn');
  btn.disabled = true;
  btn.style.opacity = '0.5';
  setStatus('loading', force ? 'Refreshing from Asana...' : 'Loading...');
  try {
    const url = force ? '/api/tasks/refresh' : '/api/tasks';
    const opts = force ? { method: 'POST' } : {};
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    allTasks = data.tasks;
    allSections = data.sections || [];
    render();
    const ago = data.last_refresh ? timeAgo(data.last_refresh) : '';
    setStatus('ok', `${data.count} tasks${ago ? ' · updated ' + ago : ''}`);
  } catch (e) {
    setStatus('error', e.message);
    showToast('Error: ' + e.message, 'error');
  } finally {
    _fetchingTasks = false;
    btn.disabled = false;
    btn.style.opacity = '';
  }
}

async function checkAiStatus() {
  try {
    const resp = await fetch('/api/ai/status');
    const data = await resp.json();
    aiAvailable = data.available;
    document.getElementById('aiBtn').style.display = aiAvailable ? '' : 'none';
  } catch (e) { aiAvailable = false; }
}

async function fetchRepoList() {
  try {
    const resp = await fetch('/api/repos/list');
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    repoList = data.repos || [];
  } catch (e) {
    console.error('Failed to fetch repo list:', e);
    repoList = [];
  }
}

async function fetchAreaRepoMap() {
  try {
    const resp = await fetch('/api/repos/mapping/areas');
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    areaRepoMap = data.area_repo_map || {};
  } catch (e) {
    console.error('Failed to fetch area repo mapping:', e);
    areaRepoMap = {};
  }
}

async function fetchTaskRepoOverrides() {
  try {
    const resp = await fetch('/api/agent/task-repo-overrides');
    if (!resp.ok) throw new Error(await resp.text());
    taskRepoOverrides = await resp.json();
  } catch (e) {
    console.error('Failed to fetch task repo overrides:', e);
    taskRepoOverrides = {};
  }
}

let _classifying = false;
async function aiClassifyAll() {
  if (_classifying) return;
  if (!confirm('Classify all tasks using Claude AI? This will call the Anthropic API.')) return;
  _classifying = true;
  const btn = document.getElementById('aiBtn');
  btn.disabled = true;
  btn.style.opacity = '0.5';
  btn.textContent = 'Classifying...';
  setStatus('loading', 'AI classifying...');
  try {
    const resp = await fetch('/api/ai/classify-all?force=true', { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    showToast(`AI classified ${data.classified}/${data.total} tasks`, 'success');
    await fetchTasks();
  } catch (e) {
    setStatus('error', e.message);
    showToast('AI error: ' + e.message, 'error');
  } finally {
    _classifying = false;
    btn.disabled = false;
    btn.style.opacity = '';
    btn.textContent = 'AI Classify All';
  }
}

async function aiClassifySingle(gid) {
  setStatus('loading', 'AI classifying task...');
  try {
    const resp = await fetch(`/api/ai/classify/${gid}?force=true`, { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    showToast(`AI: ${data.classification.reasoning}`, 'success');
    await fetchTasks();
  } catch (e) {
    showToast('AI error: ' + e.message, 'error');
  }
}

let _syncing = false;
async function syncToAsana() {
  if (_syncing) return;
  if (!confirm('Push scope scores to Asana Story Point field?')) return;
  _syncing = true;
  const btn = document.getElementById('syncBtn');
  btn.disabled = true;
  btn.style.opacity = '0.5';
  setStatus('loading', 'Syncing...');
  try {
    const resp = await fetch('/api/sync', { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    showToast(`Synced ${data.synced} tasks. ${data.errors} errors.`, data.errors > 0 ? 'error' : 'success');
    await fetchTasks();
  } catch (e) {
    setStatus('error', e.message);
    showToast('Sync failed: ' + e.message, 'error');
  } finally {
    _syncing = false;
    btn.disabled = false;
    btn.style.opacity = '';
  }
}

async function updateTask(gid, field, value) {
  const body = {};
  body[field] = parseInt(value);
  try {
    await fetch(`/api/tasks/${gid}/classify`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    await fetchTasks();
  } catch (e) {
    showToast('Update failed', 'error');
  }
}

// ════════ SORTING & FILTERING ════════

function getSortValue(task, field) {
  if (field === 'cluster') return task.cluster?.name || '';
  if (field === 'client') {
    const ct = task.tags.find(t => t.startsWith('Cliente:'));
    return ct || '';
  }
  if (field === 'project') return (task.projects || [])[0] || '';
  if (field === 'ai_summary') return task.ai_summary || task.ai_reasoning || '';
  return task[field] ?? '';
}

function getFilteredTasks() {
  let tasks = [...allTasks];

  // Agent filter: show tasks with agent runs, regardless of section
  if (activeAgentFilter) {
    tasks = tasks.filter(t => {
      const agent = agentStatuses[t.task_gid];
      if (!agent) return false;
      if (activeAgentFilter === 'all') return true;
      return agent.phase === activeAgentFilter;
    });
  } else {
    if (activeSection) tasks = tasks.filter(t => t.section_name === activeSection);
  }

  if (activeCluster) tasks = tasks.filter(t => t.cluster.id === activeCluster);
  if (activeType === '_quickwin') tasks = tasks.filter(t => t.scope_score <= 2 && t.priority >= 4);
  else if (activeType) tasks = tasks.filter(t => t.tipo === activeType);
  if (activeProject) tasks = tasks.filter(t => (t.projects || []).includes(activeProject));
  tasks.sort((a, b) => {
    const av = getSortValue(a, sortField);
    const bv = getSortValue(b, sortField);
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sortDir;
    return String(av).localeCompare(String(bv)) * sortDir;
  });
  return tasks;
}

function getClientTag(t) {
  const ct = t.tags.find(tag => tag.startsWith('Cliente:') || tag.startsWith('cliente:'));
  return ct ? ct.replace(/^[Cc]liente:\s*/, '') : '';
}

// ════════ RENDERING ════════

function render() {
  if (currentView === 'history') {
    renderHistory(document.getElementById('taskContainer'));
  } else {
    renderSidebar();
    renderSummary();
    renderTasks();
    renderCharts();
  }
}

function renderSidebar() {
  let html = '<h3>Sections</h3>';
  const totalTasks = allTasks.length;
  html += `<div class="cluster-card ${!activeSection && !activeAgentFilter ? 'active' : ''}" onclick="filterSection(null)">
    <div class="name"><span class="dot" style="background:var(--green)"></span>All Sections<span class="count">${totalTasks}</span></div>
  </div>`;
  // Agent tasks filter (cross-section)
  const agentCount = allTasks.filter(t => agentStatuses[t.task_gid]).length;
  if (agentCount > 0) {
    html += `<div class="cluster-card ${activeAgentFilter === 'all' ? 'active' : ''}" onclick="filterAgent('all')">
      <div class="name"><span class="dot" style="background:var(--accent2)"></span>Agent Tasks<span class="count">${agentCount}</span></div>
    </div>`;
  }

  allSections.filter(s => s.count > 0).forEach(s => {
    const safeName = esc(s.name).replace(/'/g, "\\'");
    html += `<div class="cluster-card ${activeSection === s.name && !activeAgentFilter ? 'active' : ''}" onclick="filterSection('${safeName}')">
      <div class="name"><span class="dot" style="background:var(--accent)"></span>${esc(s.name)}<span class="count">${s.count}</span></div>
    </div>`;
  });

  html += '<h3 style="margin-top:16px">Clusters</h3>';
  const groups = {};
  const filtered = activeSection ? allTasks.filter(t => t.section_name === activeSection) : allTasks;
  filtered.forEach(t => {
    const cid = t.cluster.id;
    if (!groups[cid]) groups[cid] = { ...t.cluster, count: 0, totalScope: 0 };
    groups[cid].count++;
    groups[cid].totalScope += t.scope_score;
  });

  html += `<div class="cluster-card ${!activeCluster ? 'active' : ''}" onclick="filterCluster(null)">
    <div class="name"><span class="dot" style="background:var(--accent)"></span>All Clusters<span class="count">${filtered.length}</span></div>
  </div>`;

  Object.values(groups).sort((a,b) => b.count - a.count).forEach(c => {
    const avg = (c.totalScope / c.count).toFixed(1);
    html += `<div class="cluster-card ${activeCluster === c.id ? 'active' : ''}" onclick="filterCluster('${c.id}')">
      <div class="name"><span class="dot" style="background:${c.color}"></span>${esc(c.name)}<span class="count">${c.count}</span></div>
      <div class="stats">Avg scope: ${avg}</div>
    </div>`;
  });

  const projectCounts = {};
  filtered.forEach(t => (t.projects || []).forEach(p => { projectCounts[p] = (projectCounts[p] || 0) + 1; }));
  if (Object.keys(projectCounts).length >= 1) {
    html += '<h4 style="margin:16px 0 6px;font-size:11px;color:var(--text2);text-transform:uppercase">Projects</h4>';
    html += `<div class="cluster-card ${!activeProject ? 'active' : ''}" onclick="filterProject(null)">
      <div class="name"><span class="dot" style="background:var(--accent)"></span>All Projects<span class="count">${filtered.length}</span></div>
    </div>`;
    Object.entries(projectCounts).sort((a,b) => b[1] - a[1]).forEach(([p, cnt]) => {
      html += `<div class="cluster-card ${activeProject === p ? 'active' : ''}" onclick="filterProject('${esc(p).replace(/'/g, "\\'")}')">
        <div class="name"><span class="dot" style="background:#6366f1"></span>${esc(p)}<span class="count">${cnt}</span></div>
      </div>`;
    });
  }

  document.getElementById('clusterList').innerHTML = html;
}

function renderSummary() {
  const tasks = getFilteredTasks();
  const errors = tasks.filter(t => t.tipo === 'Error').length;
  const mejoras = tasks.filter(t => t.tipo === 'Mejora').length;
  const avgScope = tasks.length ? (tasks.reduce((s,t) => s + t.scope_score, 0) / tasks.length).toFixed(1) : 0;
  const avgPriority = tasks.length ? (tasks.reduce((s,t) => s + t.priority, 0) / tasks.length).toFixed(1) : 0;
  const quickWins = tasks.filter(t => t.scope_score <= 2 && t.priority >= 4).length;

  let html = `
    <div class="summary-item clickable ${!activeType ? 'active-filter' : ''}" onclick="filterType(null)"><div class="label">Tasks</div><div class="value">${tasks.length}</div></div>
    <div class="summary-item clickable ${activeType === 'Error' ? 'active-filter' : ''}" onclick="filterType('Error')"><div class="label">Errors</div><div class="value" style="color:var(--red)">${errors}</div></div>
    <div class="summary-item clickable ${activeType === 'Mejora' ? 'active-filter' : ''}" onclick="filterType('Mejora')"><div class="label">Mejoras</div><div class="value" style="color:var(--blue)">${mejoras}</div></div>
    <div class="summary-item"><div class="label">Avg Scope</div><div class="value">${avgScope}</div></div>
    <div class="summary-item"><div class="label">Avg Priority</div><div class="value">${avgPriority}</div></div>
    <div class="summary-item clickable ${activeType === '_quickwin' ? 'active-filter' : ''}" onclick="filterType('_quickwin')"><div class="label">Quick Wins</div><div class="value" style="color:var(--green)">${quickWins}</div></div>
  `;

  // Agent filter — count tasks that have any agent run
  const agentTaskCount = allTasks.filter(t => agentStatuses[t.task_gid]).length;
  const runningAgents = Object.values(agentStatuses).filter(a => a.is_active).length;
  const queuedAgents = Object.values(agentStatuses).filter(a => a.phase === 'queued').length;
  if (agentTaskCount > 0) {
    html += `<div class="summary-item clickable ${activeAgentFilter === 'all' ? 'active-filter' : ''}" onclick="filterAgent('all')"><div class="label">Agent Tasks</div><div class="value" style="color:var(--accent2)">${agentTaskCount}</div></div>`;
  }
  if (runningAgents > 0) {
    html += `<div class="summary-item clickable ${activeAgentFilter === 'coding' ? 'active-filter' : ''}" onclick="filterAgent('coding')"><div class="label">Running</div><div class="value" style="color:var(--blue)">${runningAgents}</div></div>`;
  }
  if (queuedAgents > 0) {
    html += `<div class="summary-item"><div class="label">Queued</div><div class="value" style="color:var(--orange)">${queuedAgents}</div></div>`;
  }

  document.getElementById('summaryBar').innerHTML = html;
}

function renderTasks() {
  const container = document.getElementById('taskContainer');
  if (currentView === 'agents') { renderAgentHistory(container); return; }
  const tasks = getFilteredTasks();
  if (!tasks.length) { container.innerHTML = '<div class="empty-state">No tasks found</div>'; return; }
  if (currentView === 'table') { renderTable(tasks, container); return; }
  if (currentView === 'cluster') { renderByCluster(tasks, container); return; }
  renderCards(tasks, container);
}

function renderCards(tasks, container) {
  container.innerHTML = '<div class="task-grid">' + tasks.map(t => taskCard(t)).join('') + '</div>';
}

function renderTable(tasks, container) {
  const cols = [
    { key: 'rank', label: '#' },
    { key: 'scope_score', label: 'Scope' },
    { key: 'name', label: 'Task' },
    { key: 'client', label: 'Client' },
    { key: 'cluster', label: 'Cluster' },
    { key: 'project', label: 'Project' },
    { key: 'tipo', label: 'Type' },
    { key: 'ai_summary', label: 'Summary' },
  ];
  let html = '<table class="task-table"><thead><tr>';
  cols.forEach(c => {
    const arrow = sortField === c.key ? (sortDir === -1 ? ' ▼' : ' ▲') : '';
    html += `<th onclick="sortBy('${c.key}')">${c.label}${arrow}</th>`;
  });
  html += '<th>Actions</th></tr></thead><tbody>';
  tasks.forEach(t => {
    const client = getClientTag(t);
    const summary = t.ai_summary || t.ai_reasoning || '';
    html += `<tr>
      <td><span class="badge badge-rank">${t.rank}</span></td>
      <td><span class="badge badge-scope s${t.scope_score}">S${t.scope_score}</span></td>
      <td><a class="task-name" href="${t.permalink_url}" target="_blank">${esc(t.name)}</a></td>
      <td>${client ? `<span class="badge badge-client">${esc(client)}</span>` : ''}</td>
      <td><span class="badge badge-cluster" style="background:${t.cluster.color}">${esc(t.cluster.name)}</span></td>
      <td>${(t.projects||[]).map(p => `<span class="badge badge-project">${esc(p)}</span>`).join(' ')}</td>
      <td><span class="badge badge-tipo">${esc(t.tipo)}</span></td>
      <td class="summary-cell">${summary ? `<span class="summary-text">${esc(summary)}</span><button class="btn-copy" onclick="copySummary(this)" title="Copy">&#128203;</button>` : '<span style="color:var(--text2);font-size:11px">Run AI Classify</span>'}</td>
      <td>
        <select class="inline-select" onchange="updateTask('${t.task_gid}','scope_score',this.value)">
          ${[{v:1,l:'Tiny'},{v:2,l:'Small'},{v:3,l:'Medium'},{v:4,l:'Large'},{v:5,l:'XLarge'}].map(s => `<option value="${s.v}" ${s.v===t.scope_score?'selected':''}>${s.v} \u2014 ${s.l}</option>`).join('')}
        </select>
        <select class="inline-select" onchange="updateTask('${t.task_gid}','priority',this.value)">
          ${[{v:1,l:'Lowest'},{v:2,l:'Low'},{v:3,l:'Normal'},{v:4,l:'High'},{v:5,l:'Critical'}].map(p => `<option value="${p.v}" ${p.v===t.priority?'selected':''}>${p.v} \u2014 ${p.l}</option>`).join('')}
        </select>
        ${aiAvailable ? `<button class="btn-icon" onclick="aiClassifySingle('${t.task_gid}')" title="AI Classify">&#x2728;</button>` : ''}
        ${t.notes ? `<button class="btn-icon" onclick="copyNotes('${t.task_gid}')" title="Copy description">&#128203;</button>` : ''}
        <button class="btn-icon" onclick="copyBranch('${t.task_gid}')" title="Copy branch name">&#x1F33F;</button>
      </td>
    </tr>`;
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

function renderByCluster(tasks, container) {
  const groups = {};
  tasks.forEach(t => {
    const cid = t.cluster.id;
    if (!groups[cid]) groups[cid] = { ...t.cluster, tasks: [] };
    groups[cid].tasks.push(t);
  });

  let html = '';
  Object.values(groups).sort((a,b) => b.tasks.length - a.tasks.length).forEach(g => {
    html += `<div style="margin-bottom:24px">
      <h3 style="font-size:15px;margin-bottom:10px;display:flex;align-items:center;gap:8px">
        <span class="dot" style="background:${g.color};width:10px;height:10px;border-radius:50%;display:inline-block"></span>
        ${esc(g.name)} <span style="color:var(--text2);font-size:13px">(${g.tasks.length})</span>
      </h3>
      <div class="task-grid">${g.tasks.map(t => taskCard(t)).join('')}</div>
    </div>`;
  });
  container.innerHTML = html;
}

async function renderHistory(container) {
  try {
    setStatus('loading', 'Loading history...');
    const [resolvedResp, snapshotsResp] = await Promise.all([
      fetch('/api/history/resolved'),
      fetch('/api/history')
    ]);

    if (!resolvedResp.ok || !snapshotsResp.ok) {
      throw new Error('Failed to fetch history data');
    }

    const resolvedData = await resolvedResp.json();
    const snapshotsData = await snapshotsResp.json();

    const resolvedTasks = resolvedData.tasks || [];
    const snapshots = snapshotsData.snapshots || [];

    let html = '<div class="history-section">';
    html += '<h3>Velocity Chart</h3>';
    html += '<div class="history-chart"><canvas id="velocityChartCanvas"></canvas></div>';
    html += '</div>';

    html += '<div class="history-section">';
    html += `<h3>Resolved Tasks <span style="color:var(--text2);font-size:13px;font-weight:normal">(${resolvedTasks.length})</span></h3>`;
    if (!resolvedTasks.length) {
      html += '<p style="color:var(--text2);font-size:13px">No resolved tasks yet. Tasks will appear here after they disappear from your active list between syncs (reassigned, moved to QA, etc.).</p>';
    } else {
      html += '<table class="task-table"><thead><tr>';
      html += '<th>Resolved</th><th>Task</th><th>Client</th><th>Cluster</th><th>Scope</th><th>Type</th>';
      html += '</tr></thead><tbody>';

      resolvedTasks.forEach(t => {
        const client = (t.tags || []).find(tag => tag.startsWith('Cliente:'));
        const resolvedDate = t.resolved_at ? new Date(t.resolved_at).toLocaleDateString() : '';
        html += `<tr>
          <td class="completed-date">${resolvedDate}</td>
          <td><a class="task-name" href="${t.permalink_url}" target="_blank">${esc(t.name)}</a></td>
          <td>${client ? `<span class="badge badge-client">${esc(client)}</span>` : ''}</td>
          <td><span class="badge badge-cluster" style="background:${t.cluster_color || '#888'}">${esc(t.cluster_name || 'N/A')}</span></td>
          <td><span class="badge badge-scope s${t.scope_score}">S${t.scope_score}</span></td>
          <td><span class="badge badge-tipo">${esc(t.tipo || 'N/A')}</span></td>
        </tr>`;
      });
      html += '</tbody></table>';
    }
    html += '</div>';
    container.innerHTML = html;

    setTimeout(() => renderVelocityChart(snapshots), 100);
    setStatus('ok', `${resolvedTasks.length} resolved tasks`);
  } catch (e) {
    setStatus('error', e.message);
    container.innerHTML = `<div class="empty-state">Error loading history: ${esc(e.message)}</div>`;
  }
}

async function renderAgentHistory(container) {
  container.innerHTML = '<div class="spinner"></div>';
  try {
    const res = await fetch('/api/agent/history');
    if (!res.ok) throw new Error('Failed to load agent history');
    const data = await res.json();
    const { runs, stats } = data;

    let html = '<div class="history-section">';
    html += `<div class="summary-bar" style="margin-bottom:16px">
      <div class="summary-item"><div class="label">Total Runs</div><div class="value">${stats.total_runs}</div></div>
      <div class="summary-item"><div class="label">Completed</div><div class="value" style="color:var(--green)">${stats.completed}</div></div>
      <div class="summary-item"><div class="label">Failed</div><div class="value" style="color:var(--red)">${stats.failed}</div></div>
      <div class="summary-item"><div class="label">Success Rate</div><div class="value">${stats.success_rate}%</div></div>
      <div class="summary-item"><div class="label">Total Cost</div><div class="value">$${stats.total_cost_usd.toFixed(2)}</div></div>
      <div class="summary-item"><div class="label">Avg Duration</div><div class="value">${Math.round(stats.avg_duration_seconds / 60)}m</div></div>
    </div>`;

    if (runs.length === 0) {
      html += '<p style="color:var(--text2)">No agent runs yet.</p>';
    } else {
      html += `<table class="task-table"><thead><tr>
        <th>Task</th><th>Status</th><th>Repos</th><th>Commits</th>
        <th>Tokens</th><th>Cost</th><th>Duration</th><th>Retries</th><th>Date</th>
      </tr></thead><tbody>`;

      runs.forEach(r => {
        const phaseColor = PHASE_COLORS[r.phase] || '#6b7280';
        const duration = r.duration_seconds ? `${Math.round(r.duration_seconds / 60)}m` : '-';
        const tokens = (r.tokens?.input || 0) + (r.tokens?.output || 0);
        const tokensStr = tokens > 0 ? `${(tokens / 1000).toFixed(1)}k` : '-';
        const costStr = r.cost_usd > 0 ? `$${r.cost_usd.toFixed(3)}` : '-';
        const date = r.created_at ? new Date(r.created_at).toLocaleDateString() : '-';
        const commits = r.repos.reduce((s, repo) => s + (repo.commits || 0), 0);
        const repoNames = r.repos.map(repo => repo.id).join(', ');

        html += `<tr>
          <td style="max-width:300px"><span style="font-size:13px">${esc(r.task_name || r.task_gid)}</span></td>
          <td><span class="badge agent-phase-badge" style="background:${phaseColor}">${r.phase}</span></td>
          <td style="font-size:11px;color:var(--text2)">${esc(repoNames)}</td>
          <td>${commits}</td>
          <td style="font-size:11px">${tokensStr}</td>
          <td style="font-size:11px">${costStr}</td>
          <td style="font-size:11px">${duration}</td>
          <td>${r.retries || 0}</td>
          <td style="font-size:11px;color:var(--text2)">${date}</td>
        </tr>`;

        if (r.error) {
          html += `<tr><td colspan="9" style="padding:4px 10px"><span style="font-size:11px;color:var(--red)">${esc(r.error)}</span></td></tr>`;
        }

        if (r.quality_checks && r.quality_checks.length > 0) {
          html += `<tr><td colspan="9" style="padding:8px 10px;background:var(--surface2)">`;
          html += `<div style="font-size:11px"><strong>Quality Checks:</strong> `;
          r.quality_checks.forEach(c => {
            const icon = c.passed ? '✓' : '✗';
            const color = c.passed ? 'var(--green)' : 'var(--orange)';
            html += `<span style="margin-right:12px;color:${color}">${icon} ${esc(c.check)}</span>`;
          });
          html += `</div></td></tr>`;
        }
      });

      html += '</tbody></table>';
    }

    html += '</div>';
    container.innerHTML = html;
    setStatus('ok', `${stats.total_runs} agent runs`);
  } catch (e) {
    container.innerHTML = `<div class="empty-state">Error: ${esc(e.message)}</div>`;
    setStatus('error', e.message);
  }
}

// ════════ CHARTS ════════

function renderVelocityChart(snapshots) {
  const canvas = document.getElementById('velocityChartCanvas');
  if (!canvas) return;

  const sorted = snapshots.sort((a, b) => new Date(a.date) - new Date(b.date));
  const labels = sorted.map(s => new Date(s.date).toLocaleDateString());
  const data = sorted.map(s => s.open_count);

  if (velocityChart) velocityChart.destroy();

  velocityChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Open Tasks',
        data: data,
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99, 102, 241, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.4,
      }]
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: '#8b90a5', font: { size: 10 } } },
        title: { display: true, text: 'Open Task Velocity Over Time', color: '#8b90a5', font: { size: 12 } }
      },
      scales: {
        x: { ticks: { color: '#8b90a5', font: { size: 10 } }, grid: { color: '#2d3148' } },
        y: { ticks: { color: '#8b90a5' }, grid: { color: '#2d3148' } }
      }
    }
  });
}

function renderCharts() {
  const scopeCounts = [0,0,0,0,0];
  allTasks.forEach(t => scopeCounts[t.scope_score - 1]++);

  if (scopeChart) scopeChart.destroy();
  scopeChart = new Chart(document.getElementById('scopeChart'), {
    type: 'bar',
    data: {
      labels: ['S1 Tiny','S2 Small','S3 Med','S4 Large','S5 XL'],
      datasets: [{ data: scopeCounts, backgroundColor: ['#22c55e','#3b82f6','#f59e0b','#f97316','#ef4444'], borderRadius: 4 }]
    },
    options: {
      plugins: { legend: { display: false }, title: { display: true, text: 'Scope Distribution', color: '#8b90a5', font: { size: 11 } } },
      scales: { x: { ticks: { color: '#8b90a5', font: { size: 10 } }, grid: { display: false } }, y: { ticks: { color: '#8b90a5', stepSize: 1 }, grid: { color: '#2d3148' } } }
    }
  });

  const clusterData = {};
  allTasks.forEach(t => {
    const cid = t.cluster.id;
    if (!clusterData[cid]) clusterData[cid] = { label: t.cluster.name, color: t.cluster.color, count: 0 };
    clusterData[cid].count++;
  });
  const cds = Object.values(clusterData);

  if (clusterChart) clusterChart.destroy();
  clusterChart = new Chart(document.getElementById('clusterChart'), {
    type: 'doughnut',
    data: {
      labels: cds.map(c => c.label),
      datasets: [{ data: cds.map(c => c.count), backgroundColor: cds.map(c => c.color) }]
    },
    options: {
      plugins: {
        legend: { position: 'bottom', labels: { color: '#8b90a5', font: { size: 10 }, boxWidth: 10 } },
        title: { display: true, text: 'Clusters', color: '#8b90a5', font: { size: 11 } }
      }
    }
  });
}

// ════════ UI CONTROLS ════════

function filterSection(name) {
  activeSection = name;
  activeCluster = null;
  activeProject = null;
  activeAgentFilter = null;
  _saveFilters();
  render();
}

function filterCluster(id) {
  activeCluster = id;
  _saveFilters();
  render();
}

function filterProject(name) {
  activeProject = name;
  _saveFilters();
  render();
}

function setView(view, el) {
  currentView = view;
  _saveFilters();
  document.querySelectorAll('.view-tab').forEach(t => t.classList.remove('active'));
  if (el) el.classList.add('active');

  const container = document.getElementById('taskContainer');
  const sidebar = document.getElementById('sidebar');
  const summaryBar = document.getElementById('summaryBar');

  if (view === 'history' || view === 'agents') {
    sidebar.style.display = 'none';
    summaryBar.style.display = 'none';
  } else {
    sidebar.style.display = 'block';
    summaryBar.style.display = 'flex';
  }
  render();
}

function sortBy(field) {
  if (sortField === field) sortDir *= -1;
  else { sortField = field; sortDir = -1; }
  _saveFilters();
  renderTasks();
}

function filterType(type, el) {
  activeType = (activeType === type) ? null : type;
  document.querySelectorAll('.type-pill').forEach(p => p.classList.remove('active'));
  if (!activeType) document.querySelector('.type-pill')?.classList.add('active');
  else if (el) el.classList.add('active');
  _saveFilters();
  render();
}

function filterAgent(phase) {
  // Toggle: click same filter again to clear
  activeAgentFilter = (activeAgentFilter === phase) ? null : phase;
  // Clear section filter when agent filter is active (cross-section view)
  if (activeAgentFilter) activeSection = null;
  _saveFilters();
  render();
}
