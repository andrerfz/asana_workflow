// Loading state (busy, overlay) managed by CardUI — see cardUI.js

// ════════ WEBSOCKET ════════

function connectWS() {
  if (_ws && _ws.readyState <= 1) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  _ws = new WebSocket(`${proto}://${location.host}/ws/agent`);
  _ws.onopen = () => {
    console.log('[WS] connected');
    clearInterval(_wsPing);
    _wsPing = setInterval(() => {
      if (_ws && _ws.readyState === 1) _ws.send('ping');
    }, 25000);
    if (_wsWasDisconnected) {
      _wsWasDisconnected = false;
      fetchAllAgentStatuses().then(() => renderTasks());
    }
  };
  _ws.onmessage = (e) => {
    try {
      const { event, data } = JSON.parse(e.data);
      if (event === 'pong') return;
      handleAgentEvent(event, data);
    } catch {}
  };
  _ws.onclose = () => {
    console.log('[WS] disconnected, reconnecting in 3s');
    _wsWasDisconnected = true;
    clearInterval(_wsPing);
    setTimeout(connectWS, 3000);
  };
  _ws.onerror = () => { _ws.close(); };
}

function handleAgentEvent(event, data) {
  const gid = data.task_gid;
  if (!gid) return;

  if (event === 'agent:state' && data.state) {
    const prev = agentStatuses[gid];
    const prevPhase = prev?.phase;
    agentStatuses[gid] = data.state;
    const phase = data.state.phase;
    const taskName = data.state.task_name || gid;
    if (phase === 'done' && prevPhase !== 'done') {
      showToast(`Agent completed: ${taskName}`);
      sendNotification('Agent Done', `${taskName} — finished successfully`, `done-${gid}`);
    }
    if (phase === 'error' && prevPhase !== 'error') {
      showToast(`Agent error: ${data.state.error || 'unknown'}`, 'error');
      sendNotification('Agent Error', `${taskName} — ${data.state.error || 'failed'}`, `error-${gid}`);
    }
    if (phase === 'awaiting_approval' && prevPhase !== 'awaiting_approval') {
      showToast(`Agent needs approval: ${taskName}`);
      sendNotification('Approval Needed', `${taskName} — review the plan`, `approval-${gid}`);
    }
    if (phase === 'paused' && prevPhase !== 'paused') {
      showToast(`Agent has a question: ${taskName}`);
      sendNotification('Agent Question', `${taskName} — waiting for your answer`, `paused-${gid}`);
    }
    if (phase === 'qa_review' && prevPhase !== 'qa_review') {
      showToast(`QA review ready: ${taskName}`);
      sendNotification('QA Review', `${taskName} — review the QA findings`, `qa-${gid}`);
    }
    updateAgentUI(gid);
    return;
  }

  if (event === 'agent:log' && data.log) {
    const l = data.log;
    if (agentStatuses[gid]?.logs) {
      agentStatuses[gid].logs.push(data.log);
    }
    const logsEl = document.getElementById(`agent-logs-${gid}`);
    if (logsEl) {
      const line = document.createElement('div');
      line.className = `agent-log-line ${l.level || 'info'}`;
      line.innerHTML = `<span class="log-time">${(l.timestamp||'').split('T')[1]?.slice(0,8) || ''}</span> ${esc(l.message||'')}`;
      logsEl.appendChild(line);
      logsEl.scrollTop = logsEl.scrollHeight;
      const btn = logsEl.previousElementSibling;
      if (btn && btn.classList.contains('btn-agent-logs')) {
        btn.textContent = `Logs (${agentStatuses[gid]?.logs?.length || '?'})`;
      }
    }
    return;
  }
}

const _fetchDebounce = {};
async function fetchAgentStatus(gid) {
  if (_fetchDebounce[gid]) return _fetchDebounce[gid];
  const p = (async () => {
    try {
      const res = await fetch(`/api/agent/status/${gid}`);
      if (res.ok) {
        agentStatuses[gid] = await res.json();
        updateAgentUI(gid);
      }
    } catch {}
    finally { delete _fetchDebounce[gid]; }
  })();
  _fetchDebounce[gid] = p;
  return p;
}

async function fetchAllAgentStatuses() {
  try {
    const res = await fetch('/api/agent');
    if (res.ok) {
      const data = await res.json();
      (data.agents || []).forEach(a => { agentStatuses[a.task_gid] = a; });
    }
  } catch {}
}

// ════════ AGENT OPERATIONS ════════

function updateAgentUI(gid) {
  const card = document.getElementById(`task-card-${gid}`);
  if (!card) return;

  // Try to re-render only this card instead of the entire grid
  const task = allTasks.find(t => t.task_gid === gid);
  if (task && card.parentElement) {
    const tmp = document.createElement('div');
    tmp.innerHTML = taskCard(task);
    const newCard = tmp.firstElementChild;
    if (newCard) {
      card.replaceWith(newCard);
    } else {
      renderTasks();
    }
  } else {
    renderTasks();
  }

  const agent = agentStatuses[gid];
  if (agent && agent.repos) {
    agent.repos.forEach(r => {
      if (r.worktree_path) {
        setTimeout(() => loadDiff(gid, r.id), 100);
      }
    });
  }
}

async function startAgent(gid, btn) {
  if (_isBusy(gid)) return;
  CardUI.busy(gid, 'Preparing...');
  try {
    const [branchRes, suggestRes] = await Promise.all([
      fetch(`/api/ai/branch-name/${gid}`, { method: 'POST' }),
      fetch(`/api/agent/branch-suggestions/${gid}`),
    ]);

    let slug = '';
    if (branchRes.ok) {
      const branchData = await branchRes.json();
      slug = branchData.branch.split('/').pop();
    }

    let suggestions = [];
    if (suggestRes.ok) {
      const suggestData = await suggestRes.json();
      suggestions = suggestData.branches || [];
    }

    if (suggestions.length > 0) {
      _showBranchModal(gid, slug, suggestions);
    } else {
      await _doStartAgent(gid, slug, null);
    }
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
  finally { CardUI.idle(gid); }
}

function _showBranchModal(gid, slug, suggestions) {
  document.getElementById('branch-modal')?.remove();

  const suggestHtml = suggestions.map(s =>
    `<button class="btn-branch-suggest" onclick="_selectBranch('${gid}','${slug}','${s.branch}')" title="Continue from this branch">
      <code>${s.branch}</code>
      <span style="color:var(--text2);font-size:11px;margin-left:8px">— ${s.author}</span>
    </button>`
  ).join('');

  const modal = document.createElement('div');
  modal.id = 'branch-modal';
  modal.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:1000;display:flex;align-items:center;justify-content:center';
  modal.innerHTML = `
    <div style="background:var(--surface2);border-radius:12px;padding:24px;max-width:520px;width:90%">
      <h3 style="margin:0 0 8px">Start Agent</h3>
      <p style="color:var(--text2);margin:0 0 16px;font-size:13px">Branch(es) found in Asana comments. Continue from an existing branch or start fresh.</p>
      <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px">
        ${suggestHtml}
      </div>
      <div style="display:flex;gap:8px;justify-content:flex-end">
        <button class="btn" onclick="document.getElementById('branch-modal').remove()">Cancel</button>
        <button class="btn btn-primary" onclick="_selectBranch('${gid}','${slug}',null)">Fresh branch</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
}

async function _selectBranch(gid, slug, baseBranch) {
  document.getElementById('branch-modal')?.remove();
  await _doStartAgent(gid, slug, baseBranch);
}

async function _doStartAgent(gid, slug, baseBranch) {
  if (!_isBusy(gid)) CardUI.busy(gid, 'Starting agent...');
  try {
    const payload = { branch_slug: slug };
    if (baseBranch) payload.base_branch = baseBranch;

    const res = await fetch(`/api/agent/start/${gid}`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || 'Failed to start agent', 'error');
      return;
    }
    const run = await res.json();
    agentStatuses[gid] = run;
    renderTasks();
    showToast(baseBranch ? `Agent started (continuing from ${baseBranch})` : 'Agent started');
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
  finally { CardUI.idle(gid); }
}

async function updateTaskRepos(gid, selectedRepoIds) {
  try {
    const res = await fetch(`/api/agent/task/${gid}/repos`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_ids: selectedRepoIds })
    });
    if (!res.ok) {
      const err = await res.json();
      showToast(err.detail || 'Failed to update repos', 'error');
      return;
    }
    taskRepoOverrides[gid] = selectedRepoIds;
    renderTasks();
    showToast('Repos updated');
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

function handleRepoSelection(gid, selectEl) {
  const val = selectEl.value;
  if (!val) return;
  if (val === '__clear__') {
    taskRepoOverrides[gid] = [];
    updateTaskRepos(gid, []);
    selectEl.value = '';
    renderTasks();
    return;
  }
  const newRepos = [val];
  taskRepoOverrides[gid] = newRepos;
  updateTaskRepos(gid, newRepos);
  selectEl.value = '';
  renderTasks();
}

async function stopAgent(gid, btn) {
  return CardUI.wrap(gid, async () => {
    const res = await fetch(`/api/agent/stop/${gid}`, { method: 'POST' });
    if (res.ok) {
      await fetchAgentStatus(gid);
      showToast('Agent stopped');
    }
  }, 'Stopping...');
}

async function clearAgent(gid) {
  return CardUI.wrap(gid, async () => {
    await fetch(`/api/agent/clear/${gid}`, { method: 'DELETE' });
    delete agentStatuses[gid];
    renderTasks();
  });
}

async function approveAgentPlan(gid, btn) {
  return CardUI.wrap(gid, async () => {
    await answerAgent(gid, 'Approve');
    await fetchAgentStatus(gid);
  }, 'Approving...');
}

async function rejectAgentPlan(gid, btn) {
  return CardUI.wrap(gid, async () => {
    await answerAgent(gid, 'Reject');
    await fetchAgentStatus(gid);
  }, 'Rejecting...');
}

async function reviseAgentPlan(gid, btn) {
  const input = document.getElementById(`agent-revise-${gid}`);
  const feedback = input?.value?.trim();
  if (!feedback) { showToast('Type your feedback first', 'error'); return; }
  return CardUI.wrap(gid, async () => {
    await answerAgent(gid, `revise:${feedback}`);
    await fetchAgentStatus(gid);
  }, 'Revising...');
}

async function answerAgent(gid, answer) {
  try {
    const res = await fetch(`/api/agent/answer/${gid}`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ answer })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const detail = err.detail || 'Failed to send answer';
      // Agent already moved past this state — stale UI
      if (res.status === 400) {
        showToast('Agent already moved on — refreshing', 'error');
      } else {
        showToast(detail, 'error');
      }
      return;
    }
    showToast(`Sent: ${answer.length > 40 ? answer.slice(0, 40) + '...' : answer}`);
  } catch (e) { showToast(`Error: ${e.message}`, 'error'); }
}

function answerAgentCustom(gid) {
  const input = document.getElementById(`agent-answer-${gid}`);
  const val = input?.value?.trim();
  if (!val) { showToast('Type your answer first', 'error'); return; }
  CardUI.wrap(gid, async () => {
    await answerAgent(gid, val);
    await fetchAgentStatus(gid);
  }, 'Sending...');
}

// ── Guide (send feedback to running agent) ──

async function guideAgent(gid, btn) {
  const input = document.getElementById(`agent-guide-${gid}`);
  const feedback = input?.value?.trim();
  if (!feedback) { showToast('Type your guidance first', 'error'); return; }

  return CardUI.wrap(gid, async () => {
    const res = await fetch(`/api/agent/guide/${gid}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feedback }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || 'Failed to send guidance', 'error');
      return;
    }
    if (input) input.value = '';
    showToast('Guidance sent — agent will resume with your feedback');
  }, 'Sending...');
}

// ── QA Review ──

async function approveQAReview(gid, btn) {
  return CardUI.wrap(gid, async () => {
    await answerAgent(gid, 'Approve');
    await fetchAgentStatus(gid);
  }, 'Approving...');
}

async function rejectQAReview(gid, btn) {
  const input = document.getElementById(`qa-feedback-${gid}`);
  const feedback = input?.value?.trim();
  const answer = feedback ? `Reject: ${feedback}` : 'Reject';
  return CardUI.wrap(gid, async () => {
    await answerAgent(gid, answer);
    await fetchAgentStatus(gid);
  }, 'Rejecting...');
}

async function runManualQA(gid, btn) {
  return CardUI.wrap(gid, async () => {
    const res = await fetch(`/api/agent/qa/${gid}`, { method: 'POST' });
    if (res.ok) {
      showToast('QA review started');
      await fetchAgentStatus(gid);
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || 'Failed to start QA', 'error');
    }
  }, 'Running QA...');
}

async function runManualTest(gid, btn) {
  return CardUI.wrap(gid, async () => {
    const res = await fetch(`/api/agent/test/${gid}`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      showToast(data.all_passed ? 'All tests passed' : 'Tests failed', data.all_passed ? 'success' : 'error');
      await fetchAgentStatus(gid);
    } else {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || 'Failed to run tests', 'error');
    }
  }, 'Running tests...');
}

function toggleAgentLogs(gid) {
  const el = document.getElementById(`agent-logs-${gid}`);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

async function loadDiff(gid, repoId) {
  const container = document.getElementById(`diff-${gid}-${repoId}`);
  if (!container) return;
  try {
    const res = await fetch(`/api/agent/diff/${gid}/${repoId}`);
    if (!res.ok) return;
    const data = await res.json();
    if (!data.files || data.files.length === 0) {
      container.innerHTML = '<div style="font-size:11px;color:var(--text2);padding:4px 0">No changes detected</div>';
      return;
    }
    let html = `<div class="agent-diff">
      <div style="font-size:11px;font-weight:600;color:var(--text2);margin-bottom:4px">
        Changed files: ${data.files.length}
        (<span style="color:var(--green)">+${data.total_added}</span>
        <span style="color:var(--red)">-${data.total_removed}</span>)
      </div>`;
    data.files.forEach(f => {
      html += `<div class="agent-diff-file">
        <span style="font-family:monospace;font-size:11px">${esc(f.file)}</span>
        <span style="margin-left:auto;font-size:10px">
          <span style="color:var(--green)">+${f.added}</span>
          <span style="color:var(--red)">-${f.removed}</span>
        </span>
      </div>`;
    });
    html += `</div>`;
    container.innerHTML = html;
  } catch {}
}
