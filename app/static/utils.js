// ════════ UTILITIES ════════

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
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

function copyToClipboard(text) {
  // Try modern API first, fall back to execCommand
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).catch(() => _fallbackCopy(text));
  }
  return _fallbackCopy(text);
}

function _fallbackCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;left:-9999px;opacity:0';
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  try { document.execCommand('copy'); } catch {}
  document.body.removeChild(ta);
  return Promise.resolve();
}

function copySummary(btn) {
  const parent = btn.parentElement;
  const text = parent.querySelector('.summary-text')?.textContent
    || btn.previousElementSibling?.textContent
    || parent.childNodes[0]?.textContent  // fallback: first text node
    || '';
  if (!text.trim()) { showToast('Nothing to copy', 'error'); return; }
  copyToClipboard(text.trim()).then(() => {
    const orig = btn.innerHTML;
    btn.innerHTML = '&#10003;';
    btn.style.opacity = '1';
    setTimeout(() => { btn.innerHTML = orig; btn.style.opacity = ''; }, 1500);
    showToast('Copied', 'success');
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

// IDE helpers
function getIDEPreference() {
  return JSON.parse(localStorage.getItem('idePreference') || '{}');
}
function saveIDEPreference(ide) {
  localStorage.setItem('idePreference', JSON.stringify(ide));
}
function openInIDE(path) {
  const pref = getIDEPreference();
  if (!pref.protocol && !pref.app) { openSettings(); switchSettingsTab('ide'); return; }
  if (pref.app) {
    // JetBrains IDEs: use backend to open via `open -a` (protocol URLs don't handle directories well)
    fetch('/api/ide/open', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: pref.app, path }),
    }).then(r => { if (!r.ok) r.json().then(e => showToast(e.detail || 'Failed to open IDE', 'error')); })
      .catch(e => showToast(`Error: ${e.message}`, 'error'));
    return;
  }
  const url = pref.protocol.replace('{path}', encodeURIComponent(path));
  window.open(url, '_blank');
}

// Notifications
function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}
function sendNotification(title, body, tag) {
  if ('Notification' in window && Notification.permission === 'granted') {
    const n = new Notification(title, { body, icon: '/static/icon.png', tag: tag || 'agent', renotify: true });
    n.onclick = () => { window.focus(); n.close(); };
  }
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = 880;
    gain.gain.value = 0.15;
    osc.start();
    osc.stop(ctx.currentTime + 0.15);
  } catch {}
}
