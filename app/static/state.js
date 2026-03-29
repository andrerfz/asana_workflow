// ════════ STATE ════════

let allTasks = [];
let allSections = [];
let agentStatuses = {}; // task_gid → agent run data
let repoList = []; // all available repos
let areaRepoMap = {}; // area → repo ids
let taskRepoOverrides = {}; // task_gid → repo ids (manually assigned)

// WebSocket
let _ws = null;
let _wsPing = null;
let _wsWasDisconnected = false;

// Restore filters from localStorage
const _saved = JSON.parse(localStorage.getItem('dashFilters') || '{}');
let activeCluster = _saved.cluster || null;
let activeProject = _saved.project || null;
let activeSection = _saved.section !== undefined ? _saved.section : null;
let currentView = _saved.view || 'cards';
let sortField = _saved.sortField || 'priority';
let sortDir = _saved.sortDir ?? -1;
let activeType = _saved.type || null;
let activeAgentFilter = _saved.agentFilter || null; // null, 'all', or a specific phase

// Charts
let scopeChart = null;
let clusterChart = null;
let velocityChart = null;

// AI
let aiAvailable = false;

// Settings
let _settingsTab = 'repos';
let _projectsDir = '';

function _saveFilters() {
  localStorage.setItem('dashFilters', JSON.stringify({
    cluster: activeCluster,
    project: activeProject,
    section: activeSection,
    view: currentView,
    sortField, sortDir,
    type: activeType,
    agentFilter: activeAgentFilter,
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

const PHASE_COLORS = {
  queued:'#6b7280', init:'#8b5cf6', investigating:'#0ea5e9', planning:'#d97706',
  awaiting_approval:'#eab308', coding:'#3b82f6', testing:'#22c55e', qa_review:'#a855f7',
  done:'#8b5cf6', error:'#ef4444', paused:'#eab308', cancelled:'#4b5563',
};
const PHASE_LABELS = {
  queued:'Queued', init:'Init', investigating:'Investigating', planning:'Planning',
  awaiting_approval:'Awaiting Approval', coding:'Coding', testing:'Testing',
  qa_review:'QA Review', done:'Done', error:'Error', paused:'Paused', cancelled:'Cancelled',
};

const IDE_OPTIONS = [
  { id: 'phpstorm', name: 'PhpStorm', cli: '/Applications/PhpStorm.app/Contents/MacOS/phpstorm', cliArgs: [] },
  { id: 'vscode', name: 'VS Code', cli: 'code', cliArgs: ['-r'] },
  { id: 'cursor', name: 'Cursor', cli: 'cursor', cliArgs: ['-r'] },
  { id: 'webstorm', name: 'WebStorm', cli: '/Applications/WebStorm.app/Contents/MacOS/webstorm', cliArgs: [] },
  { id: 'idea', name: 'IntelliJ IDEA', cli: '/Applications/IntelliJ IDEA.app/Contents/MacOS/idea', cliArgs: [] },
  { id: 'sublime', name: 'Sublime Text', protocol: 'subl://open?file={path}' },
];
