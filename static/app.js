let allTasks = [];
let allSections = [];

// Restore filters from localStorage
const _saved = JSON.parse(localStorage.getItem('dashFilters') || '{}');
let activeCluster = _saved.cluster || null;
let activeProject = _saved.project || null;
let activeSection = _saved.section !== undefined ? _saved.section : null;
let currentView = _saved.view || 'cards';
let scopeChart = null;
let clusterChart = null;
let velocityChart = null;
let sortField = _saved.sortField || 'priority';
let sortDir = _saved.sortDir ?? -1;
let activeType = _saved.type || null;

function _saveFilters() {
  localStorage.setItem('dashFilters', JSON.stringify({
    cluster: activeCluster,
    project: activeProject,
    section: activeSection,
    view: currentView,
    sortField, sortDir,
    type: activeType,
  }));
}

const CLUSTERS_META = {
  ebitda: { name: 'EBITDA Reports', color: '#e74c3c' },
  trazabilidad: { name: 'Trazabilidad', color: '#9b59b6' },
  turnos: { name: 'Planificacion Turnos', color: '#3498db' },
  pedidos: { name: 'Pedidos / Albaranes', color: '#f39c12' },
  almacen: { name: 'Almacen', color: '#1abc9c' },
  sentry: { name: 'Sentry', color: '#95a5a6' },
  integracion: { name: 'Integraciones', color: '#e67e22' },
  standalone: { name: 'Standalone', color: '#7f8c8d' },
};

async function fetchTasks(force = false) {
  setStatus('loading', force ? 'Refreshing from Asana...' : 'Loading...');
  document.getElementById('refreshBtn').disabled = true;
  try {
    const url = force ? '/api/tasks/refresh' : '/api/tasks';
    const opts = force ? { method: 'POST' } : {};
    const resp = await fetch(url, opts);
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    allTasks = data.tasks;
    allSections = data.sections || [];
    // activeSection stays null (All Sections) unless user explicitly picks one
    render();
    const ago = data.last_refresh ? timeAgo(data.last_refresh) : '';
    setStatus('ok', `${data.count} tasks${ago ? ' · updated ' + ago : ''}`);
  } catch (e) {
    setStatus('error', e.message);
    showToast('Error: ' + e.message, 'error');
  }
  document.getElementById('refreshBtn').disabled = false;
}

function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

let aiAvailable = false;

async function checkAiStatus() {
  try {
    const resp = await fetch('/api/ai/status');
    const data = await resp.json();
    aiAvailable = data.available;
    document.getElementById('aiBtn').style.display = aiAvailable ? '' : 'none';
  } catch (e) { aiAvailable = false; }
}

async function aiClassifyAll() {
  if (!confirm('Classify all tasks using Claude AI? This will call the Anthropic API.')) return;
  setStatus('loading', 'AI classifying...');
  document.getElementById('aiBtn').disabled = true;
  document.getElementById('aiBtn').textContent = 'Classifying...';
  try {
    const resp = await fetch('/api/ai/classify-all?force=true', { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    showToast(`AI classified ${data.classified}/${data.total} tasks`, 'success');
    await fetchTasks();
  } catch (e) {
    setStatus('error', e.message);
    showToast('AI error: ' + e.message, 'error');
  }
  document.getElementById('aiBtn').disabled = false;
  document.getElementById('aiBtn').textContent = 'AI Classify All';
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

async function syncToAsana() {
  if (!confirm('Push scope scores to Asana Story Point field?')) return;
  setStatus('loading', 'Syncing...');
  document.getElementById('syncBtn').disabled = true;
  try {
    const resp = await fetch('/api/sync', { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    showToast(`Synced ${data.synced} tasks. ${data.errors} errors.`, data.errors > 0 ? 'error' : 'success');
    await fetchTasks();
  } catch (e) {
    setStatus('error', e.message);
    showToast('Sync failed: ' + e.message, 'error');
  }
  document.getElementById('syncBtn').disabled = false;
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

// activeType initialized from localStorage above

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
  if (activeSection) tasks = tasks.filter(t => t.section_name === activeSection);
  if (activeCluster) tasks = tasks.filter(t => t.cluster.id === activeCluster);
  if (activeType === '_quickwin') tasks = tasks.filter(t => t.scope_score <= 2 && t.priority >= 7);
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
  // ── Section filter (top of sidebar) ──
  let html = '<h3>Sections</h3>';
  const totalTasks = allTasks.length;
  html += `<div class="cluster-card ${!activeSection ? 'active' : ''}" onclick="filterSection(null)">
    <div class="name"><span class="dot" style="background:var(--green)"></span>All Sections<span class="count">${totalTasks}</span></div>
  </div>`;
  allSections.filter(s => s.count > 0).forEach(s => {
    const safeName = esc(s.name).replace(/'/g, "\\'");
    html += `<div class="cluster-card ${activeSection === s.name ? 'active' : ''}" onclick="filterSection('${safeName}')">
      <div class="name"><span class="dot" style="background:var(--accent)"></span>${esc(s.name)}<span class="count">${s.count}</span></div>
    </div>`;
  });

  // ── Cluster filter ──
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

  // ── Project filter ──
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
  const quickWins = tasks.filter(t => t.scope_score <= 2 && t.priority >= 7).length;

  document.getElementById('summaryBar').innerHTML = `
    <div class="summary-item clickable ${!activeType ? 'active-filter' : ''}" onclick="filterType(null)"><div class="label">Tasks</div><div class="value">${tasks.length}</div></div>
    <div class="summary-item clickable ${activeType === 'Error' ? 'active-filter' : ''}" onclick="filterType('Error')"><div class="label">Errors</div><div class="value" style="color:var(--red)">${errors}</div></div>
    <div class="summary-item clickable ${activeType === 'Mejora' ? 'active-filter' : ''}" onclick="filterType('Mejora')"><div class="label">Mejoras</div><div class="value" style="color:var(--blue)">${mejoras}</div></div>
    <div class="summary-item"><div class="label">Avg Scope</div><div class="value">${avgScope}</div></div>
    <div class="summary-item"><div class="label">Avg Priority</div><div class="value">${avgPriority}</div></div>
    <div class="summary-item clickable ${activeType === '_quickwin' ? 'active-filter' : ''}" onclick="filterType('_quickwin')"><div class="label">Quick Wins</div><div class="value" style="color:var(--green)">${quickWins}</div></div>
  `;
}

function renderTasks() {
  const tasks = getFilteredTasks();
  const container = document.getElementById('taskContainer');
  if (!tasks.length) { container.innerHTML = '<div class="empty-state">No tasks found</div>'; return; }

  if (currentView === 'table') { renderTable(tasks, container); return; }
  if (currentView === 'cluster') { renderByCluster(tasks, container); return; }
  renderCards(tasks, container);
}

function renderCards(tasks, container) {
  container.innerHTML = '<div class="task-grid">' + tasks.map(t => taskCard(t)).join('') + '</div>';
}

function getClientTag(t) {
  const ct = t.tags.find(tag => tag.startsWith('Cliente:') || tag.startsWith('cliente:'));
  return ct ? ct.replace(/^[Cc]liente:\s*/, '') : '';
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
          ${[1,2,3,4,5].map(s => `<option value="${s}" ${s===t.scope_score?'selected':''}>S${s}</option>`).join('')}
        </select>
        <select class="inline-select" onchange="updateTask('${t.task_gid}','priority',this.value)">
          ${Array.from({length:10},(_,i)=>i+1).map(p => `<option value="${p}" ${p===t.priority?'selected':''}>P${p}</option>`).join('')}
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
      html += '<th>Resolved</th>';
      html += '<th>Task</th>';
      html += '<th>Client</th>';
      html += '<th>Cluster</th>';
      html += '<th>Scope</th>';
      html += '<th>Type</th>';
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

    // Render velocity chart
    setTimeout(() => renderVelocityChart(snapshots), 100);
    setStatus('ok', `${resolvedTasks.length} resolved tasks`);
  } catch (e) {
    setStatus('error', e.message);
    container.innerHTML = `<div class="empty-state">Error loading history: ${esc(e.message)}</div>`;
  }
}

function renderVelocityChart(snapshots) {
  const canvas = document.getElementById('velocityChartCanvas');
  if (!canvas) return;

  // Sort snapshots by date
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

function taskCard(t) {
  const aiSource = t.classification_source === 'ai';
  const client = getClientTag(t);
  const summary = t.ai_summary || t.ai_reasoning || '';
  return `<div class="task-card">
    <div class="task-header">
      <span class="badge badge-rank" title="Execution order">#${t.rank}</span>
      <a class="task-name" href="${t.permalink_url}" target="_blank">${esc(t.name)}</a>
      <div class="task-badges">
        ${aiSource ? '<span class="badge badge-ai" title="Classified by AI">AI</span>' : ''}
        ${client ? `<span class="badge badge-client">${esc(client)}</span>` : ''}
        <span class="badge badge-cluster" style="background:${t.cluster.color}">${esc(t.cluster.name)}</span>
        <span class="badge badge-tipo">${esc(t.tipo)}</span>
        <select class="inline-select" onchange="updateTask('${t.task_gid}','scope_score',this.value)" title="Scope Score">
          ${[1,2,3,4,5].map(s => `<option value="${s}" ${s===t.scope_score?'selected':''}>S${s}</option>`).join('')}
        </select>
        <select class="inline-select" onchange="updateTask('${t.task_gid}','priority',this.value)" title="Priority">
          ${Array.from({length:10},(_,i)=>i+1).map(p => `<option value="${p}" ${p===t.priority?'selected':''}>P${p}</option>`).join('')}
        </select>
        ${aiAvailable ? `<button class="btn-icon" onclick="aiClassifySingle('${t.task_gid}')" title="Re-classify with AI">&#x2728;</button>` : ''}
        <button class="btn-icon" onclick="copyBranch('${t.task_gid}')" title="Copy branch name">&#x1F33F;</button>
      </div>
    </div>
    ${summary ? `<div class="ai-summary"><span class="summary-text">${esc(summary)}</span><button class="btn-copy" onclick="copySummary(this)" title="Copy">&#128203;</button></div>` : ''}
    ${t.notes_preview ? `<div class="task-notes">${esc(t.notes_preview)}${t.notes ? `<button class="btn-copy" onclick="copyNotes('${t.task_gid}')" title="Copy full description">&#128203;</button>` : ''}</div>` : ''}
    <div class="task-tags">
      ${!activeSection && t.section_name ? `<span class="badge" style="background:#1e3a5f;color:#93c5fd;font-size:10px;padding:2px 6px;border-radius:3px">${esc(t.section_name)}</span>` : ''}
      ${(t.projects||[]).map(p => `<span class="badge badge-project">${esc(p)}</span>`).join('')}
      ${t.tags.filter(tag => !tag.startsWith('Cliente:') && !tag.startsWith('cliente:')).map(tag => `<span class="tag">${esc(tag)}</span>`).join('')}
      ${t.desarrollador && t.desarrollador !== 'N/A' ? `<span class="tag" style="border:1px solid var(--accent);color:var(--accent)">${esc(t.desarrollador)}</span>` : ''}
    </div>
  </div>`;
}

function renderCharts() {
  // Scope distribution
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

  // Cluster pie
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

function filterSection(name) {
  activeSection = name;
  activeCluster = null;
  activeProject = null;
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

  if (view === 'history') {
    sidebar.style.display = 'none';
    summaryBar.style.display = 'none';
    renderHistory(container);
  } else {
    sidebar.style.display = 'block';
    summaryBar.style.display = 'flex';
    renderTasks();
    renderCharts();
  }
}

function sortBy(field) {
  if (sortField === field) sortDir *= -1;
  else { sortField = field; sortDir = -1; }
  _saveFilters();
  renderTasks();
}

function setStatus(state, text) {
  const dot = document.getElementById('statusDot');
  dot.className = 'status-dot ' + state;
  document.getElementById('statusText').textContent = text;
}

function showToast(msg, type) {
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

function copySummary(btn) {
  const text = btn.parentElement.querySelector('.summary-text')?.textContent || btn.previousElementSibling?.textContent || '';
  copyToClipboard(text.trim()).then(() => {
    const orig = btn.innerHTML;
    btn.innerHTML = '&#10003;';
    btn.style.opacity = '1';
    setTimeout(() => { btn.innerHTML = orig; btn.style.opacity = ''; }, 1500);
  });
}

function copyNotes(gid) {
  const task = allTasks.find(t => t.task_gid === gid);
  if (!task || !task.notes) return;
  copyToClipboard(task.notes).then(() => {
    showToast('Description copied', 'success');
  });
}

async function copyBranch(gid) {
  showToast('Generating branch name...', 'success');
  try {
    const resp = await fetch(`/api/ai/branch-name/${gid}`, { method: 'POST' });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    await copyToClipboard(data.branch);
    showToast(`Copied: ${data.branch}`, 'success');
  } catch (e) {
    showToast('Branch name error: ' + e.message, 'error');
  }
}

function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback for HTTP contexts
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  return Promise.resolve();
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function filterType(type, el) {
  // Toggle off if clicking the same filter
  activeType = (activeType === type) ? null : type;
  // Sync type pills
  document.querySelectorAll('.type-pill').forEach(p => p.classList.remove('active'));
  if (!activeType) document.querySelector('.type-pill')?.classList.add('active');
  else if (el) el.classList.add('active');
  _saveFilters();
  render();
}

// Sidebar resize
(function() {
  const handle = document.getElementById('resizeHandle');
  const sidebar = document.getElementById('sidebar');
  let startX, startW;
  handle.addEventListener('mousedown', e => {
    startX = e.clientX; startW = sidebar.offsetWidth;
    handle.classList.add('active');
    const onMove = e2 => { sidebar.style.width = Math.max(180, Math.min(500, startW + e2.clientX - startX)) + 'px'; sidebar.style.minWidth = 'unset'; };
    const onUp = () => { handle.classList.remove('active'); document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
})();

// Init — restore saved view tab
checkAiStatus();
fetchTasks().then(() => {
  if (currentView !== 'cards') {
    const tabs = document.querySelectorAll('.view-tab');
    tabs.forEach(t => {
      t.classList.remove('active');
      if (t.textContent.toLowerCase().replace(/\s/g,'') === currentView) t.classList.add('active');
    });
    setView(currentView, document.querySelector('.view-tab.active'));
  }
});
