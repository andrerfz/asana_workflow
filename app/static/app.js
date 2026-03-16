// ════════ APP ENTRY POINT ════════
// All logic split into: state.js, utils.js, agent.js, taskCard.js, views.js, settings.js

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

// Init
checkAiStatus();
connectWS();
requestNotificationPermission();
Promise.all([fetchRepoList(), fetchAreaRepoMap(), fetchTaskRepoOverrides()]).then(() => {
  return fetchAllAgentStatuses().then(() => fetchTasks());
}).then(() => {
  if (currentView !== 'cards') {
    const tabs = document.querySelectorAll('.view-tab');
    tabs.forEach(t => {
      t.classList.remove('active');
      if (t.textContent.toLowerCase().replace(/\s/g,'') === currentView) t.classList.add('active');
    });
    setView(currentView, document.querySelector('.view-tab.active'));
  }
});
