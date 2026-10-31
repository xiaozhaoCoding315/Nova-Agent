// Nova Agent 桌面壳：一个指向自托管服务器的精简客户端。
// 首次启动让用户填服务器地址（校验 /api/v1/status/health），之后记住并直连。
const { app, BrowserWindow, Menu, dialog, ipcMain, net, session, shell } = require('electron')
const fs = require('node:fs')
const path = require('node:path')

const isMac = process.platform === 'darwin'
let mainWindow = null
let setupWindow = null

/* ---------- 配置持久化 ---------- */

function configFile() {
  return path.join(app.getPath('userData'), 'nova-config.json')
}

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(configFile(), 'utf8'))
  } catch {
    return {}
  }
}

function saveConfig(patch) {
  const next = { ...loadConfig(), ...patch }
  fs.mkdirSync(path.dirname(configFile()), { recursive: true })
  fs.writeFileSync(configFile(), JSON.stringify(next, null, 2))
  return next
}

function normalizeUrl(raw) {
  let url = String(raw || '').trim().replace(/\/+$/, '')
  if (url && !/^https?:\/\//i.test(url)) url = `http://${url}`
  return url
}

async function checkServer(url) {
  try {
    const res = await net.fetch(`${url}/api/v1/status/health`, {
      signal: AbortSignal.timeout(6000),
    })
    return res.ok
  } catch {
    return false
  }
}

/* ---------- 窗口 ---------- */

function createMainWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 880,
    minWidth: 960,
    minHeight: 600,
    backgroundColor: '#101014',
    autoHideMenuBar: true,
    title: 'Nova Agent',
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  })

  // 仓库导出 ZIP、桌面安装包等下载落到用户选择的本地路径
  mainWindow.webContents.session.on('will-download', (event, item) => {
    const target = dialog.showSaveDialogSync(mainWindow, {
      defaultPath: item.getFilename(),
    })
    if (!target) {
      event.preventDefault()
      return
    }
    item.setSavePath(target)
  })

  // 站外链接交给系统浏览器；站内跳转放行
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (target.startsWith(`${url}/`) || target === url) return { action: 'allow' }
    setImmediate(() => shell.openExternal(target))
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, target) => {
    if (target.startsWith(`${url}/`) || target === url) return
    event.preventDefault()
    shell.openExternal(target)
  })

  mainWindow.loadURL(url)
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function createSetupWindow(savedUrl, warning) {
  setupWindow = new BrowserWindow({
    width: 520,
    height: 380,
    resizable: false,
    backgroundColor: '#101014',
    autoHideMenuBar: true,
    title: '连接 Nova 服务器',
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  const query = encodeURIComponent(JSON.stringify({ savedUrl, warning: warning || '' }))
  setupWindow.loadFile('first-run.html', { search: `?config=${query}` })
  setupWindow.on('closed', () => {
    setupWindow = null
  })
}

/* ---------- IPC：首启连接 ---------- */

ipcMain.handle('nova:connect', async (_event, rawUrl) => {
  const url = normalizeUrl(rawUrl)
  if (!/^https?:\/\/.+/.test(url)) {
    return { ok: false, error: '请输入有效的服务器地址，例如 http://192.168.1.10:8000' }
  }
  const ok = await checkServer(url)
  if (!ok) {
    return { ok: false, error: '连不上这个地址：请确认服务器已启动、地址与端口正确（ health 接口不可达）' }
  }
  saveConfig({ serverUrl: url })
  createMainWindow(url)
  if (setupWindow) setupWindow.close()
  setupAutoUpdate()
  return { ok: true }
})

/* ---------- 自动更新（可选） ---------- */

function setupAutoUpdate() {
  const updateUrl = String(
    process.env.NOVA_UPDATE_URL || loadConfig().updateUrl || '',
  ).trim().replace(/\/+$/, '')
  if (!app.isPackaged || !/^https?:\/\//i.test(updateUrl)) return

  let autoUpdater
  try {
    ;({ autoUpdater } = require('electron-updater'))
  } catch (err) {
    console.warn('auto-update unavailable:', err?.message || err)
    return
  }

  try {
    autoUpdater.setFeedURL({ provider: 'generic', url: updateUrl })
    autoUpdater.autoDownload = true
    autoUpdater.autoInstallOnAppQuit = true
    autoUpdater.on('error', (err) => console.warn('auto-update:', err?.message || err))
    autoUpdater.on('update-downloaded', async () => {
      const { response } = await dialog.showMessageBox(mainWindow ?? undefined, {
        type: 'info',
        title: 'Nova Agent 更新已就绪',
        message: '新版本已下载完成，是否现在重启安装？',
        buttons: ['重启安装', '稍后'],
        defaultId: 0,
        cancelId: 1,
      })
      if (response === 0) autoUpdater.quitAndInstall()
    })
    autoUpdater.checkForUpdatesAndNotify().catch(() => {})
  } catch (err) {
    console.warn('auto-update setup failed:', err?.message || err)
  }
}

/* ---------- 应用生命周期 ---------- */

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = mainWindow ?? setupWindow
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(async () => {
    Menu.setApplicationMenu(null)

    const savedUrl = normalizeUrl(loadConfig().serverUrl)
    if (savedUrl && (await checkServer(savedUrl))) {
      createMainWindow(savedUrl)
      setupAutoUpdate()
    } else {
      createSetupWindow(
        savedUrl,
        savedUrl ? '上次的服务器地址暂时连不上，可以修改后重试。' : '',
      )
    }

    app.on('activate', () => {
      // macOS：点 Dock 图标时若无窗口则重建
      if (BrowserWindow.getAllWindows().length === 0) {
        const url = normalizeUrl(loadConfig().serverUrl)
        if (url) createMainWindow(url)
        else createSetupWindow('', '')
      }
    })
  })

  app.on('window-all-closed', () => {
    if (!isMac) app.quit()
  })
}
