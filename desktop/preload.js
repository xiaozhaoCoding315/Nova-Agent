const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('novaDesktop', {
  connect: (url) => ipcRenderer.invoke('nova:connect', url),
})
