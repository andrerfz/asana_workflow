const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

const FASTAPI_PORT = 8765;
const FASTAPI_URL = `http://localhost:${FASTAPI_PORT}`;

let mainWindow;
let fastapiProcess;

function startFastApi() {
  const projectRoot = path.join(__dirname, '..');
  fastapiProcess = spawn('uvicorn', ['app:app', '--host', '0.0.0.0', '--port', String(FASTAPI_PORT)], {
    cwd: projectRoot,
    env: { ...process.env },
    stdio: 'pipe',
  });
  fastapiProcess.stdout.on('data', d => console.log('[fastapi]', d.toString().trim()));
  fastapiProcess.stderr.on('data', d => console.error('[fastapi]', d.toString().trim()));
}

function waitForServer(url, attempts = 30) {
  return new Promise((resolve, reject) => {
    const http = require('http');
    let tries = 0;
    const check = () => {
      tries++;
      http.get(url, res => {
        if (res.statusCode < 500) resolve();
        else retry();
      }).on('error', () => {
        if (tries >= attempts) reject(new Error('FastAPI did not start'));
        else setTimeout(check, 1000);
      });
    };
    const retry = () => setTimeout(check, 1000);
    check();
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 900,
    minWidth: 800,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.loadURL(FASTAPI_URL);

  // Open external links in default browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  startFastApi();
  try {
    await waitForServer(FASTAPI_URL + '/');
  } catch (e) {
    console.error('FastAPI failed to start:', e.message);
  }
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (fastapiProcess) fastapiProcess.kill();
  if (process.platform !== 'darwin') app.quit();
});
