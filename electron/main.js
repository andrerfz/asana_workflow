const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

const FASTAPI_PORT = 8765;
const FASTAPI_URL = `http://localhost:${FASTAPI_PORT}`;

// Where the git repo + docker-compose.yml + .env live. When running from source
// (`make electron-start`) it's the parent dir. When packaged into a .app,
// __dirname points inside the bundle, so fall back to the configured repo path
// (override with the ASANA_WF_REPO env var, e.g. for a teammate's checkout).
const PROJECT_ROOT = process.env.ASANA_WF_REPO
  || (app.isPackaged ? '/Users/andrerfz/Proyectos/asana_workflow' : path.join(__dirname, '..'));
const COMPOSE_BASE = ['compose', '-f', 'docker/docker-compose.yml', '--env-file', '.env'];

let mainWindow;
let splashWindow;

// When launched from Finder (packaged .app) the inherited PATH is minimal and
// won't include docker/git. Augment it so spawned tools resolve either way.
function buildEnv() {
  const extra = [
    '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin',
    path.join(process.env.HOME || '', '.orbstack/bin'),
  ];
  const current = (process.env.PATH || '').split(':');
  const PATH = [...new Set([...extra, ...current])].filter(Boolean).join(':');
  return { ...process.env, PATH };
}

// Run a command to completion, capturing output. Never rejects on non-zero
// exit — returns { code, out, err } so callers decide what a failure means.
function run(cmd, args, opts = {}) {
  return new Promise(resolve => {
    const child = spawn(cmd, args, {
      cwd: opts.cwd || PROJECT_ROOT,
      env: buildEnv(),
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let out = '', err = '';
    child.stdout.on('data', d => { out += d.toString(); });
    child.stderr.on('data', d => { err += d.toString(); });
    child.on('error', e => resolve({ code: -1, out, err: e.message }));
    child.on('close', code => resolve({ code, out: out.trim(), err: err.trim() }));
  });
}

function isServerUp(url) {
  return new Promise(resolve => {
    require('http').get(url, res => resolve(res.statusCode < 500)).on('error', () => resolve(false));
  });
}

function waitForServer(url, attempts = 90) {
  return new Promise((resolve, reject) => {
    const http = require('http');
    let tries = 0;
    const check = () => {
      tries++;
      http.get(url, res => {
        if (res.statusCode < 500) resolve();
        else retry();
      }).on('error', () => {
        if (tries >= attempts) reject(new Error('El backend no respondió a tiempo'));
        else setTimeout(check, 1000);
      });
    };
    const retry = () => { if (tries >= attempts) reject(new Error('El backend no respondió a tiempo')); else setTimeout(check, 1000); };
    check();
  });
}

const sleep = ms => new Promise(r => setTimeout(r, ms));
function setStatus(msg) {
  console.log('[launcher]', msg);
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.executeJavaScript(`window.setStatus(${JSON.stringify(msg)})`).catch(() => {});
  }
}
function showError(msg) {
  console.error('[launcher] error:', msg);
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.executeJavaScript(`window.showError(${JSON.stringify(msg)})`).catch(() => {});
  }
}

// Make sure the Docker daemon is running; start OrbStack/Docker Desktop if not.
async function ensureDockerDaemon() {
  if ((await run('docker', ['info'])).code === 0) return;

  setStatus('Arrancando Docker (OrbStack)…');
  // open -a returns immediately; the daemon takes a few seconds to be ready.
  let opened = await run('open', ['-a', 'OrbStack']);
  if (opened.code !== 0) opened = await run('open', ['-a', 'Docker']);
  if (opened.code !== 0) {
    throw new Error('No encuentro OrbStack ni Docker Desktop. Instala uno y vuelve a abrir la app.');
  }

  for (let i = 0; i < 40; i++) {           // up to ~80s
    await sleep(2000);
    if ((await run('docker', ['info'])).code === 0) return;
    setStatus(`Esperando a que Docker arranque… (${i + 1})`);
  }
  throw new Error('Docker no terminó de arrancar.');
}

// Pull the latest code on the current branch when we can fast-forward safely.
// Returns true if anything was updated. Stashes local changes rather than
// clobbering them, and refuses to auto-merge a diverged history.
async function autoUpdate() {
  if ((await run('git', ['rev-parse', '--is-inside-work-tree'])).code !== 0) return { updated: false };

  setStatus('Buscando actualizaciones…');
  if ((await run('git', ['fetch', '--quiet'])).code !== 0) {
    setStatus('Sin conexión para actualizar — continuando.');
    return { updated: false };
  }

  const local = (await run('git', ['rev-parse', '@'])).out;
  const upstream = await run('git', ['rev-parse', '@{u}']);
  if (upstream.code !== 0) return { updated: false };   // no upstream configured
  const remote = upstream.out;
  if (local === remote) return { updated: false };      // already up to date

  const base = (await run('git', ['merge-base', '@', '@{u}'])).out;
  if (local !== base) {
    // Diverged or ahead of remote — don't touch it automatically.
    setStatus('Hay cambios locales divergentes — me salto la actualización.');
    return { updated: false };
  }

  // Behind remote and fast-forwardable. Protect uncommitted work first.
  const dirty = (await run('git', ['status', '--porcelain'])).out;
  if (dirty) {
    setStatus('Guardando tus cambios locales (git stash)…');
    await run('git', ['stash', 'push', '-u', '-m', 'auto-stash by electron launcher']);
  }

  setStatus('Descargando actualización…');
  const pull = await run('git', ['pull', '--ff-only']);
  if (pull.code !== 0) {
    setStatus('No se pudo actualizar — continuando con la versión actual.');
    return { updated: false };
  }
  if (dirty) setStatus('Cambios locales guardados en "git stash" (recupéralos con: git stash pop).');
  // Did the update touch the frontend? Its built bundle is gitignored and the
  // compose bind-mount shadows the image's build, so we must rebuild it on the
  // host for the new UI to actually be served.
  const changed = (await run('git', ['diff', '--name-only', local, '@'])).out;
  return { updated: true, frontendChanged: /(^|\n)frontend\//.test(changed) };
}

// Rebuild the Angular bundle on the host. Needed after a UI update: the built
// bundle is gitignored (so `git pull` doesn't bring it) and the compose
// bind-mount shadows the image's build with the host's app/static.
async function rebuildFrontend() {
  setStatus('Recompilando interfaz…');
  const fe = path.join(PROJECT_ROOT, 'frontend');
  if (!require('fs').existsSync(path.join(fe, 'node_modules'))) {
    await run('npm', ['ci', '--prefer-offline'], { cwd: fe });
  }
  const r = await run('npm', ['run', 'build'], { cwd: fe });
  if (r.code !== 0) console.error('[frontend] build failed:', r.err || r.out);
}

// Start (or recreate) the backend container. Rebuilds the image when code was
// updated so dependency/Dockerfile changes are picked up.
async function startBackend(rebuild) {
  setStatus(rebuild ? 'Reconstruyendo backend…' : 'Arrancando backend…');
  const args = [...COMPOSE_BASE, 'up', '-d', ...(rebuild ? ['--build'] : [])];
  const res = await run('docker', args);
  if (res.code !== 0) {
    throw new Error('docker compose up falló:\n' + (res.err || res.out));
  }
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 420, height: 320, resizable: false, frame: false,
    backgroundColor: '#0f1115', center: true, show: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    show: false,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(FASTAPI_URL);

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (splashWindow && !splashWindow.isDestroyed()) splashWindow.close();
    splashWindow = null;
  });

  // Open external links in default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

// --- Claude Code subscription usage bridge -------------------------------
// The real session/weekly quota (what `/status` shows) comes from
// /api/oauth/usage, which needs the `user:profile` OAuth scope. Only the
// interactive login token (stored in the macOS Keychain) has it — and only the
// host can read the Keychain. So Electron (host) fetches it and writes it to
// data/ for the Dockerised backend to serve.
function httpsGetJson(url, headers) {
  return new Promise((resolve, reject) => {
    require('https').get(url, { headers }, res => {
      let body = '';
      res.on('data', c => { body += c; });
      res.on('end', () => {
        if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}: ${body.slice(0, 200)}`));
        try { resolve(JSON.parse(body)); } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}

async function pollOAuthUsage() {
  if (process.platform !== 'darwin') return;  // Keychain read is macOS-only
  try {
    const cred = await run('security', ['find-generic-password', '-s', 'Claude Code-credentials', '-w']);
    if (cred.code !== 0 || !cred.out) return;
    const oauth = (JSON.parse(cred.out).claudeAiOauth) || JSON.parse(cred.out);
    const token = oauth.accessToken;
    if (!token) return;
    const usage = await httpsGetJson('https://api.anthropic.com/api/oauth/usage', {
      Authorization: `Bearer ${token}`,
      'anthropic-beta': 'oauth-2025-04-20',
      'anthropic-version': '2023-06-01',
    });
    const fs = require('fs');
    const out = path.join(PROJECT_ROOT, 'data', 'oauth_usage.json');
    fs.writeFileSync(out, JSON.stringify({ fetched_at: new Date().toISOString(), usage }));
  } catch (e) {
    console.error('[oauth-usage] fetch failed:', e.message);
  }
}

async function boot() {
  createSplash();
  try {
    // If the backend is already serving, only check for updates that would
    // require a restart; otherwise bring the whole stack up from scratch.
    const alreadyUp = await isServerUp(FASTAPI_URL + '/');

    await ensureDockerDaemon();
    const { updated, frontendChanged } = await autoUpdate();

    if (frontendChanged) {
      await rebuildFrontend();
    }
    if (!alreadyUp || updated) {
      await startBackend(updated);
    }

    setStatus('Esperando al servidor…');
    await waitForServer(FASTAPI_URL + '/');
    createWindow();
  } catch (e) {
    showError(e.message || String(e));
  }
}

app.whenReady().then(() => {
  boot();
  pollOAuthUsage();
  setInterval(pollOAuthUsage, 120_000);  // keep the quota snapshot fresh
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) boot();
  });
});

app.on('window-all-closed', () => {
  // The backend lives in Docker (restart: unless-stopped) and is intentionally
  // left running so it survives closing the window.
  if (process.platform !== 'darwin') app.quit();
});
