const { contextBridge, ipcRenderer } = require('electron');

// Safe bridge exposed to the Angular app. Lets the renderer ask the main
// process (which runs on the host) to open an IDE — something the Dockerised
// backend can't do. Presence of window.electronAPI also signals "we're in the
// desktop app", so the frontend can fall back to the HTTP endpoint in a browser.
contextBridge.exposeInMainWorld('electronAPI', {
  openIde: (opts) => ipcRenderer.invoke('open-ide', opts),
});
