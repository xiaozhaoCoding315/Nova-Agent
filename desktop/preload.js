const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('novaDesktop', {
  connect: (url) => ipcRenderer.invoke('nova:connect', url),
  startLocal: () => ipcRenderer.invoke('nova:start-local'),
  onLaunchStatus: (callback) => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('nova:launch-status', listener)
    return () => ipcRenderer.removeListener('nova:launch-status', listener)
  },
})
