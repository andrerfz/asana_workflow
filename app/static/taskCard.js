// ════════ TASK CARD — 3-ROW LAYOUT ════════

function taskCard(t) {
  const aiSource = t.classification_source === 'ai';
  const client = getClientTag(t);
  const summary = t.ai_summary || t.ai_reasoning || '';
  const agent = agentStatuses[t.task_gid];
  const agentHasWorktree = agent && agent.repos && agent.repos.some(r => r.worktree_path);
  const hasAgent = agent && (!['cancelled'].includes(agent.phase) || agentHasWorktree);

  const taskRepos = taskRepoOverrides[t.task_gid] || (t.area ? areaRepoMap[t.area] || [] : []);
  const hasRepos = taskRepos && taskRepos.length > 0;
  const repoIdsArray = Array.isArray(taskRepos) ? taskRepos : [];

  // ── Row 1: Header ──
  let agentControls = '';
  const phase = hasAgent ? agent.phase : null;
  const isActive = hasAgent && agent.is_active;
  const busy = _isBusy(t.task_gid);
  const dis = busy ? 'disabled style="opacity:0.5;pointer-events:none"' : '';

  if (!hasAgent) {
    // No agent — show start button
    const startDis = busy || !hasRepos;
    agentControls = `<button class="btn-icon btn-agent-start" onclick="startAgent('${t.task_gid}',this)" ${startDis?'disabled':''} title="${!hasRepos?'Assign a repo first':'Start AI Agent'}" style="${startDis?'opacity:0.4;pointer-events:none':''}">&#x1F916;</button>`;
  } else if (isActive) {
    // Agent running — show stop button
    agentControls = `<button class="btn-icon" onclick="stopAgent('${t.task_gid}',this)" ${dis} title="Stop Agent" style="color:var(--red)${busy?';opacity:0.5;pointer-events:none':''}">&#x23F9;</button>`;
  } else if (phase === 'done') {
    // Done — show clear + test + QA
    agentControls = `<button class="btn-icon" onclick="clearAgent('${t.task_gid}')" ${dis} title="Dismiss" style="color:var(--text2)">&#x2715;</button>`;
    if (agentHasWorktree) agentControls += `<button class="btn" onclick="runManualTest('${t.task_gid}',this)" ${dis} style="font-size:10px;padding:2px 8px;background:#3b82f6;color:#fff;border:none;border-radius:4px;margin-left:4px" title="Run tests on worktree">Test</button>`;
    agentControls += `<button class="btn" onclick="runManualQA('${t.task_gid}',this)" ${dis} style="font-size:10px;padding:2px 8px;background:#a855f7;color:#fff;border:none;border-radius:4px;margin-left:4px">QA</button>`;
  } else if (phase === 'error') {
    // Error — show clear + restart + test + QA
    agentControls = `<button class="btn-icon" onclick="clearAgent('${t.task_gid}')" ${dis} title="Dismiss" style="color:var(--text2)">&#x2715;</button>`;
    agentControls += `<button class="btn-icon btn-agent-start" onclick="startAgent('${t.task_gid}',this)" ${dis} title="Retry Agent">&#x1F504;</button>`;
    if (agentHasWorktree) agentControls += `<button class="btn" onclick="runManualTest('${t.task_gid}',this)" ${dis} style="font-size:10px;padding:2px 8px;background:#3b82f6;color:#fff;border:none;border-radius:4px;margin-left:4px" title="Run tests on worktree">Test</button>`;
    agentControls += `<button class="btn" onclick="runManualQA('${t.task_gid}',this)" ${dis} style="font-size:10px;padding:2px 8px;background:#a855f7;color:#fff;border:none;border-radius:4px;margin-left:4px">QA</button>`;
  } else {
    // Other inactive phases (cancelled, etc) — show clear + restart + test + QA if worktree exists
    agentControls = `<button class="btn-icon" onclick="clearAgent('${t.task_gid}')" ${dis} title="Dismiss" style="color:var(--text2)">&#x2715;</button>`;
    agentControls += `<button class="btn-icon btn-agent-start" onclick="startAgent('${t.task_gid}',this)" ${dis} title="Retry Agent">&#x1F504;</button>`;
    if (agentHasWorktree) {
      agentControls += `<button class="btn" onclick="runManualTest('${t.task_gid}',this)" ${dis} style="font-size:10px;padding:2px 8px;background:#3b82f6;color:#fff;border:none;border-radius:4px;margin-left:4px" title="Run tests on worktree">Test</button>`;
      agentControls += `<button class="btn" onclick="runManualQA('${t.task_gid}',this)" ${dis} style="font-size:10px;padding:2px 8px;background:#a855f7;color:#fff;border:none;border-radius:4px;margin-left:4px">QA</button>`;
    }
  }

  const row1 = `<div class="tc-header">
    <span class="badge badge-rank" title="Execution order">#${t.rank}</span>
    <a class="task-name" href="${t.permalink_url}" target="_blank">${esc(t.name)}</a>
    <div class="tc-actions">
      ${hasAgent ? agentBadgeHTML(agent) : ''}
      ${agentControls}
      ${aiAvailable && !isActive ? `<button class="btn-icon" onclick="aiClassifySingle('${t.task_gid}')" ${dis} title="Re-classify with AI">&#x2728;</button>` : ''}
      <button class="btn-icon" onclick="copyBranch('${t.task_gid}')" title="Copy branch name">&#x1F33F;</button>
    </div>
  </div>`;

  // ── Row 2: Classification (only if AI classified or area assigned) ──
  let row2 = '';
  if (aiSource || t.area) {
    row2 = `<div class="tc-classification">
      ${t.area ? `<span class="tc-label">Area</span><span class="badge badge-area">${esc(t.area)}</span>` : ''}
      <span class="badge badge-cluster" style="background:${t.cluster.color}">${esc(t.cluster.name)}</span>
      ${client ? `<span class="badge badge-client">${esc(client)}</span>` : ''}
      ${aiSource ? '<span class="badge badge-ai" title="Classified by AI">AI</span>' : ''}
      <div class="tc-repo-wrap">
        <select class="inline-select repo-selector" onchange="handleRepoSelection('${t.task_gid}',this)" title="${hasRepos ? 'Repos: '+repoIdsArray.join(', ') : 'Assign repo for agent'}">
          ${!hasRepos ? '<option value="" disabled selected>— repo —</option>' : ''}
          ${repoList.map(r => {
            const isAssigned = repoIdsArray.includes(r.id);
            const isFirst = isAssigned && r.id === repoIdsArray[0];
            return `<option value="${r.id}" ${isFirst?'selected':''}>${isAssigned?'✓ ':''}${r.id}</option>`;
          }).join('')}
          ${hasRepos ? '<option value="__clear__">✕ Clear repos</option>' : ''}
        </select>
      </div>
    </div>`;
  }

  // ── Row 3: Meta ──
  const metaParts = [];
  metaParts.push(`<span class="tc-meta-item tc-scope s${t.scope_score}" onclick="toggleScopeEdit(this,'${t.task_gid}')" title="Scope: how big/complex (1=quick win, 5=large feature) — click to edit">Scope ${t.scope_score}</span>`);
  metaParts.push(`<span class="tc-meta-item tc-priority" onclick="togglePriorityEdit(this,'${t.task_gid}')" title="Priority: how urgent (1=lowest, 5=critical) — click to edit">Pri ${t.priority}</span>`);
  metaParts.push(`<span class="tc-meta-item tc-tipo">${esc(t.tipo)}</span>`);
  if (!activeSection && t.section_name) {
    metaParts.push(`<span class="tc-meta-item tc-section">${esc(t.section_name)}</span>`);
  }
  (t.projects || []).forEach(p => {
    metaParts.push(`<span class="badge badge-project">${esc(p)}</span>`);
  });
  t.tags.filter(tag => !tag.startsWith('Cliente:') && !tag.startsWith('cliente:')).forEach(tag => {
    metaParts.push(`<span class="tag">${esc(tag)}</span>`);
  });
  if (t.desarrollador && t.desarrollador !== 'N/A') {
    metaParts.push(`<span class="tc-meta-item tc-dev">@${esc(t.desarrollador)}</span>`);
  }

  const row3 = `<div class="tc-meta">${metaParts.join('<span class="tc-sep">·</span>')}</div>`;

  // ── Expandable sections ──
  let expandable = '';
  if (summary) {
    expandable += `<div class="tc-summary"><span class="summary-text">${esc(summary)}</span><button class="btn-copy" onclick="copySummary(this)" title="Copy">&#128203;</button></div>`;
  }
  if (hasAgent) {
    expandable += agentPanelHTML(t.task_gid, agent);
  }
  if (t.notes_preview) {
    expandable += `<div class="task-notes">${esc(t.notes_preview)}${t.notes ? `<button class="btn-copy" onclick="copyNotes('${t.task_gid}')" title="Copy full description">&#128203;</button>` : ''}</div>`;
  }

  return `<div class="task-card" id="task-card-${t.task_gid}" data-has-repos="${hasRepos}">
    ${row1}${row2}${row3}${expandable}
  </div>`;
}

// ── Click-to-edit for scope/priority ──

function toggleScopeEdit(el, gid) {
  if (el.querySelector('select')) return;
  const task = allTasks.find(t => t.task_gid === gid);
  if (!task) return;
  const current = task.scope_score;
  const scopeLabels = {1:'Tiny',2:'Small',3:'Medium',4:'Large',5:'XLarge'};
  const sel = document.createElement('select');
  sel.className = 'inline-select';
  sel.setAttribute('autofocus','');
  sel.onchange = function(){ updateTask(gid,'scope_score',this.value); };
  sel.onblur = function(){ renderTasks(); };
  [1,2,3,4,5].forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.selected = s === current;
    opt.textContent = s + ' \u2014 ' + scopeLabels[s];
    sel.appendChild(opt);
  });
  el.textContent = '';
  el.appendChild(sel);
  el.querySelector('select').focus();
}

function togglePriorityEdit(el, gid) {
  if (el.querySelector('select')) return;
  const task = allTasks.find(t => t.task_gid === gid);
  if (!task) return;
  const current = task.priority;
  const priLabels = {1:'Lowest',2:'Low',3:'Normal',4:'High',5:'Critical'};
  const selP = document.createElement('select');
  selP.className = 'inline-select';
  selP.setAttribute('autofocus','');
  selP.onchange = function(){ updateTask(gid,'priority',this.value); };
  selP.onblur = function(){ renderTasks(); };
  [1,2,3,4,5].forEach(p => {
    const opt = document.createElement('option');
    opt.value = p;
    opt.selected = p === current;
    opt.textContent = p + ' \u2014 ' + priLabels[p];
    selP.appendChild(opt);
  });
  el.textContent = '';
  el.appendChild(selP);
  el.querySelector('select').focus();
}

// ── Agent UI sub-components ──

function agentBadgeHTML(agent) {
  const color = PHASE_COLORS[agent.phase] || '#6b7280';
  const label = PHASE_LABELS[agent.phase] || agent.phase;
  const pulse = agent.is_active ? 'animation:pulse 1.5s infinite;' : '';
  return `<span id="agent-badge-${agent.task_gid}" class="badge agent-phase-badge phase-${agent.phase}"
    style="background:${color};color:#fff;font-size:10px;${pulse}" title="Agent: ${label}">${label}</span>`;
}

function agentPanelHTML(gid, agent) {
  const busy = _isBusy(gid);
  const dis = busy ? 'disabled style="opacity:0.5;pointer-events:none"' : '';
  let html = `<div class="agent-panel" id="agent-panel-${gid}">`;

  // Current activity indicator — always visible for active agents
  if (agent.is_active) {
    const phaseLabel = PHASE_LABELS[agent.phase] || agent.phase;
    const phaseColor = PHASE_COLORS[agent.phase] || '#6b7280';
    const lastLog = agent.logs && agent.logs.length > 0 ? agent.logs[agent.logs.length - 1].message : '';
    html += `<div style="display:flex;align-items:center;gap:8px;padding:8px 12px;background:${phaseColor}15;border-left:3px solid ${phaseColor};border-radius:4px;margin-bottom:8px;font-size:12px">
      <span style="width:8px;height:8px;border-radius:50%;background:${phaseColor};animation:pulse 1.5s infinite;flex-shrink:0"></span>
      <span style="font-weight:600;color:${phaseColor}">${phaseLabel}</span>
      ${lastLog ? `<span style="color:var(--text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(lastLog)}</span>` : ''}
    </div>`;
  }

  // Guide input — only when actively coding
  if (agent.is_active && agent.phase === 'coding') {
    html += `<div class="agent-guide" style="margin-bottom:8px;padding:10px 12px;background:rgba(59,130,246,0.07);border-left:3px solid #3b82f6;border-radius:4px">
      <div style="font-size:11px;font-weight:600;color:#3b82f6;margin-bottom:6px">Guide Agent</div>
      <div style="display:flex;gap:6px;align-items:flex-end">
        <textarea class="form-input" id="agent-guide-${gid}" placeholder="Send feedback or redirect the agent..." rows="2" style="flex:1;font-size:12px;resize:vertical;min-height:44px" ${busy?'disabled':''}></textarea>
        <button class="btn btn-primary" onclick="guideAgent('${gid}',this)" ${dis} style="align-self:flex-end;font-size:11px;padding:4px 12px">Send</button>
      </div>
    </div>`;
  }

  // Plan approval (show during awaiting_approval and planning/revise)
  if (['awaiting_approval', 'planning'].includes(agent.phase) && agent.plan) {
    html += `<div class="agent-plan">
      <div class="agent-plan-title">Implementation Plan</div>
      <pre class="agent-plan-text">${esc(agent.plan)}</pre>
      <div class="agent-plan-actions">
        <button class="btn btn-agent-approve" onclick="approveAgentPlan('${gid}',this)" ${dis}>Approve</button>
        <button class="btn btn-agent-reject" onclick="rejectAgentPlan('${gid}',this)" ${dis}>Reject</button>
      </div>
      <div style="margin-top:8px;display:flex;gap:6px;align-items:flex-end">
        <textarea class="form-input" id="agent-revise-${gid}" placeholder="Feedback to revise the plan..." rows="3" style="flex:1;font-size:12px;resize:vertical;min-height:60px" ${busy?'disabled':''}></textarea>
        <button class="btn btn-agent-revise" onclick="reviseAgentPlan('${gid}',this)" ${dis} style="align-self:flex-end">Revise</button>
      </div>
    </div>`;
  }

  // QA Review — show when in qa_review phase OR when done/error with a report
  if (agent.qa_report && ['qa_review', 'done', 'error'].includes(agent.phase)) {
    const qaAnswered = agent.question && agent.question.answer;
    const isActive = agent.phase === 'qa_review' && !qaAnswered;
    html += `<div class="agent-qa" style="border-left:3px solid #a855f7;background:rgba(168,85,247,0.05);padding:12px;border-radius:6px;margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <span style="font-weight:600;color:#a855f7;font-size:13px">🔍 QA Review</span>
        ${agent.phase === 'done' ? '<span style="font-size:10px;padding:2px 8px;background:#10b981;color:#fff;border-radius:10px">Approved</span>' : agent.phase === 'error' ? '<span style="font-size:10px;padding:2px 8px;background:#ef4444;color:#fff;border-radius:10px">Issues Found</span>' : ''}
      </div>
      <pre class="agent-plan-text" style="max-height:300px;overflow-y:auto">${esc(agent.qa_report)}</pre>`;
    if (isActive) {
      html += `<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
        <button onclick="approveQAReview('${gid}',this)" ${dis} style="padding:8px 20px;background:#10b981;color:#fff;border:none;border-radius:6px;font-weight:600;font-size:13px;cursor:pointer">✓ Approve &amp; Deliver</button>
        <button onclick="rejectQAReview('${gid}',this)" ${dis} style="padding:8px 20px;background:#ef4444;color:#fff;border:none;border-radius:6px;font-weight:600;font-size:13px;cursor:pointer">✕ Reject &amp; Fix</button>
      </div>
      <div style="margin-top:8px">
        <textarea class="form-input" id="qa-feedback-${gid}" placeholder="Optional: tell the agent what to fix..." rows="2" style="width:100%;font-size:12px;resize:vertical;min-height:40px;border:1px solid rgba(168,85,247,0.3);border-radius:4px"></textarea>
      </div>`;
    }
    html += `</div>`;
  }

  // Question from agent
  if (agent.phase === 'paused' && agent.question && !agent.question.answer) {
    const q = agent.question;
    html += `<div class="agent-question">
      <div class="agent-question-title">Agent needs your input</div>
      <p>${esc(q.text)}</p>
      ${q.options ? q.options.map(o => `<button class="btn" onclick="answerAgent('${gid}','${o}')" ${dis} style="margin:4px 4px 4px 0">${o}</button>`).join('') : ''}
      <div style="margin-top:8px;display:flex;gap:6px">
        <input class="form-input" id="agent-answer-${gid}" placeholder="Or type a custom answer..." style="flex:1" ${busy?'disabled':''}>
        <button class="btn btn-primary" onclick="answerAgentCustom('${gid}')" ${dis}>Send</button>
      </div>
    </div>`;
  }

  // Repo statuses — hide during early phases, show meaningful status
  if (agent.repos && agent.repos.length > 0 && !['queued', 'init', 'planning'].includes(agent.phase)) {
    const visibleRepos = agent.repos.filter(r => r.status && r.status !== 'pending');
    if (visibleRepos.length > 0) {
      html += `<div class="agent-repos">`;
      visibleRepos.forEach(r => {
        const statusColor = r.status === 'done' ? 'var(--green)' : r.status === 'error' ? 'var(--red)' : r.status === 'coding' ? 'var(--blue)' : 'var(--text2)';
        const displayStatus = r.status === 'ready' ? 'waiting' : r.status;
        html += `<div class="agent-repo-row">
          <span style="font-weight:600;font-size:12px">${esc(r.id)}</span>
          ${r.branch ? `<span style="color:var(--accent2);font-size:11px;font-family:monospace" title="Branch">${esc(r.branch)}</span>` : ''}
          <span style="color:${statusColor};font-size:11px">${displayStatus}</span>
          ${r.commits ? `<span style="color:var(--text2);font-size:11px">${r.commits} commits</span>` : ''}
          ${r.worktree_path ? `<button class="btn-icon" onclick="openInIDE('${r.worktree_path}')" title="Open in IDE">&#128194;</button>` : ''}
        </div>`;
      });
      html += `</div>`;
    }
  }

  // Diff preview — only show when repos have actual work done
  if (['done', 'testing', 'coding', 'qa_review', 'error'].includes(agent.phase) && agent.repos && agent.repos.length > 0) {
    agent.repos.filter(r => r.status === 'done' || r.status === 'coding' || r.status === 'error').forEach(r => {
      if (r.worktree_path) {
        html += `<div id="diff-${gid}-${r.id}" class="agent-diff-container"></div>`;
      }
    });
  }

  // Cost tracking
  if ((agent.tokens && (agent.tokens.input > 0 || agent.tokens.output > 0)) || agent.cost_usd > 0 || agent.num_api_calls > 0) {
    html += `<div class="agent-costs" style="background:var(--surface2);border-radius:6px;padding:12px;font-size:11px;margin-top:12px">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        ${agent.tokens?.input ? `<div><span style="color:var(--text2)">Input tokens:</span> <span style="font-weight:600">${agent.tokens.input.toLocaleString()}</span></div>` : ''}
        ${agent.tokens?.output ? `<div><span style="color:var(--text2)">Output tokens:</span> <span style="font-weight:600">${agent.tokens.output.toLocaleString()}</span></div>` : ''}
        ${agent.cost_usd ? `<div><span style="color:var(--text2)">Cost:</span> <span style="font-weight:600;color:var(--accent2)">$${agent.cost_usd.toFixed(4)}</span></div>` : ''}
        ${agent.num_api_calls ? `<div><span style="color:var(--text2)">API calls:</span> <span style="font-weight:600">${agent.num_api_calls}</span></div>` : ''}
      </div>
    </div>`;
  }

  // Quality checks
  if (agent.phase === 'done' && agent.quality_checks && agent.quality_checks.length > 0) {
    html += `<div style="margin-top:6px;font-size:11px">`;
    html += `<div style="font-weight:600;color:var(--text2);margin-bottom:4px">Quality Checks</div>`;
    agent.quality_checks.forEach(c => {
      const icon = c.passed ? '✓' : '✗';
      const color = c.passed ? 'var(--green)' : 'var(--orange)';
      html += `<div style="padding:2px 0;color:${color}">${icon} [${esc(c.repo)}] ${esc(c.check)}: ${esc(c.detail)}</div>`;
    });
    html += `</div>`;
  }

  // Error display
  if (agent.phase === 'error' && agent.error) {
    html += `<div class="agent-error">
      <span style="color:var(--red);font-size:12px">${esc(agent.error)}</span>
      <button class="btn-icon" onclick="startAgent('${gid}')" title="Retry" style="margin-left:8px">&#x1F504;</button>
    </div>`;
  }

  // Log toggle
  if (agent.logs && agent.logs.length > 0) {
    const logsOpen = agent.is_active || ['planning','coding','testing','qa_review'].includes(agent.phase);
    html += `<button class="btn btn-agent-logs" onclick="toggleAgentLogs('${gid}')">
      Logs (${agent.logs.length})
    </button>
    <div class="agent-logs" id="agent-logs-${gid}" style="display:${logsOpen ? 'block' : 'none'}; max-height:200px; overflow-y:auto">
      ${agent.logs.slice(-30).map(l => `<div class="agent-log-line ${l.level}"><span class="log-time">${l.timestamp.split('T')[1]?.slice(0,8) || ''}</span> ${esc(l.message)}</div>`).join('')}
    </div>`;
  }

  html += `</div>`;
  return html;
}
