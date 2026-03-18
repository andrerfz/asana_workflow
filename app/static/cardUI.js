// ════════ CARD UI — REACTIVE STATE MANAGER ════════
// Centralized control for card loading overlays and button states.
// All transitions are CSS-class driven for instant, paint-optimized feedback.

const _busy = new Set();
function _isBusy(gid) { return _busy.has(gid); }

const CardUI = (() => {
  const _epoch = {};  // gid → wrap generation, prevents stale idle() from clearing a newer wrap

  /** Show loading backdrop on a card and disable all interactive elements. */
  function busy(gid, label) {
    _busy.add(gid);
    const card = document.getElementById(`task-card-${gid}`);
    if (!card) return;
    card.classList.add('card-busy');
    // Insert overlay if not already present
    if (!card.querySelector('.card-overlay')) {
      const overlay = document.createElement('div');
      overlay.className = 'card-overlay';
      const inner = document.createElement('div');
      inner.className = 'card-overlay-inner';
      const spinner = document.createElement('span');
      spinner.className = 'spinner';
      inner.appendChild(spinner);
      if (label) {
        const labelEl = document.createElement('span');
        labelEl.className = 'card-overlay-label';
        labelEl.textContent = label;
        inner.appendChild(labelEl);
      }
      overlay.appendChild(inner);
      card.appendChild(overlay);
    }
  }

  /** Remove loading backdrop and restore card to idle state. */
  function idle(gid) {
    _busy.delete(gid);
    const card = document.getElementById(`task-card-${gid}`);
    if (!card) return;
    card.classList.remove('card-busy');
    card.querySelector('.card-overlay')?.remove();
  }

  /** Wrap an async action with busy/idle lifecycle + loading overlay.
   *  Prevents double-fire: returns immediately if already busy.
   *  Safety timeout: unblocks card after 30s even if backend hangs. */
  async function wrap(gid, fn, label) {
    if (_busy.has(gid)) return;
    const gen = (_epoch[gid] || 0) + 1;
    _epoch[gid] = gen;
    busy(gid, label);
    // Safety: force-unblock after 30s if the backend never responds
    const safety = setTimeout(() => {
      if (_epoch[gid] === gen) {
        idle(gid);
        showToast('Action timed out — please retry', 'error');
      }
    }, 30000);
    try {
      await fn();
    } finally {
      clearTimeout(safety);
      if (_epoch[gid] === gen) idle(gid);
    }
  }

  /** Hide elements matching a CSS selector within a card. */
  function hide(gid, selector) {
    const card = document.getElementById(`task-card-${gid}`);
    card?.querySelectorAll(selector).forEach(el => el.classList.add('ui-hidden'));
  }

  /** Show elements matching a CSS selector within a card. */
  function show(gid, selector) {
    const card = document.getElementById(`task-card-${gid}`);
    card?.querySelectorAll(selector).forEach(el => el.classList.remove('ui-hidden'));
  }

  /** Disable specific elements within a card. */
  function disable(gid, selector) {
    const card = document.getElementById(`task-card-${gid}`);
    card?.querySelectorAll(selector).forEach(el => el.classList.add('ui-disabled'));
  }

  /** Enable specific elements within a card. */
  function enable(gid, selector) {
    const card = document.getElementById(`task-card-${gid}`);
    card?.querySelectorAll(selector).forEach(el => el.classList.remove('ui-disabled'));
  }

  return { busy, idle, wrap, hide, show, disable, enable };
})();
