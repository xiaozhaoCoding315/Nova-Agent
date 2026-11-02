// Nova Agent 桌面壳。
//
// 两种运行方式：
//   local  —— 在本机启动随安装包分发的后端（内嵌 PostgreSQL），数据留在本机；
//   server —— 连接一台已部署的 Nova 服务器，本机只做界面。
// 首次启动让用户二选一，之后记住；菜单「运行」可随时切换。
const { app, BrowserWindow, Menu, dialog, ipcMain, net, shell } = require('electron')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const path = require('node:path')

const isMac = process.platform === 'darwin'
const LOCAL_START_TIMEOUT_MS = 120_000
const LOCAL_STOP_TIMEOUT_MS = 8_000

let mainWindow = null
let setupWindow = null
let launchWindow = null
let launchStatus = null
let backend = null
let backendUrl = ''
let stoppingBackend = false
let quitting = false

/* ---------- 配置持久化 ---------- */

// 桌面壳自己的配置（运行方式、服务器地址）。本地后端的 nova-config.json
// 由后端自己管理，位于系统配置目录，命令行 nova.py local 与桌面端共用。
function configFile() {
  return path.join(app.getPath('userData'), 'nova-config.json')
}

function loadConfig() {
  try {
    const data = JSON.parse(fs.readFileSync(configFile(), 'utf8'))
    return data && typeof data === 'object' ? data : {}
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

function errorText(err) {
  return String(err && err.message ? err.message : err || '未知错误')
}

function showMessage(options) {
  if (mainWindow && !mainWindow.isDestroyed()) return dialog.showMessageBox(mainWindow, options)
  return dialog.showMessageBox(options)
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

// 后端的 listening 事件在 uvicorn 真正 bind 之前就会打印，加载窗口前要等
// health 返回，否则首屏会落进 chrome-error（连接被拒）。
async function waitForHealth(url, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await net.fetch(`${url}/api/v1/status/health`, {
        signal: AbortSignal.timeout(2000),
      })
      if (res.ok) return true
    } catch {
      // 端口还没起来，继续等
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  return false
}

/* ---------- 本地后端进程 ---------- */

function backendLaunchSpec() {
  const override = String(process.env.NOVA_BACKEND_EXE || '').trim()
  if (override) return { command: override, args: [] }

  if (app.isPackaged) {
    const binary = process.platform === 'win32' ? 'nova-backend.exe' : 'nova-backend'
    return {
      command: path.join(process.resourcesPath, 'backend', binary),
      args: [],
    }
  }

  const backendDir = path.resolve(__dirname, '..', 'backend')
  const venvPython = path.join(backendDir, '.venv', 'Scripts', 'python.exe')
  const script = path.join(backendDir, 'nova.py')
  if (fs.existsSync(venvPython)) return { command: venvPython, args: [script] }
  return { command: process.env.NOVA_PYTHON || 'python', args: [script] }
}

function sendLaunchStatus(payload) {
  launchStatus = payload
  if (!launchWindow || launchWindow.isDestroyed()) return
  if (launchWindow.webContents.isLoading()) return
  launchWindow.webContents.send('nova:launch-status', payload)
}

function startLocalBackend() {
  return new Promise((resolve, reject) => {
    const spec = backendLaunchSpec()
    if (!fs.existsSync(spec.command)) {
      reject(new Error(
        `找不到本地后端：${spec.command}\n请重新安装 Nova Agent，或先构建 backend/dist/nova-backend。`,
      ))
      return
    }

    sendLaunchStatus({ message: '正在启动本地服务…', detail: '首次启动需要初始化本地数据库，可能需要几十秒。' })

    const env = {
      ...process.env,
      NOVA_PARENT_WATCH: '1',
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
    }
    delete env.ELECTRON_RUN_AS_NODE

    let child
    try {
      child = spawn(spec.command, [...spec.args, 'local', '--port', '0'], {
        cwd: path.dirname(spec.command),
        env,
        windowsHide: true,
        stdio: ['pipe', 'pipe', 'pipe'],
      })
    } catch (err) {
      reject(new Error(`无法启动本地服务进程：${errorText(err)}`))
      return
    }

    backend = child
    backendUrl = ''

    let settled = false
    let failedStart = false
    let timer = null
    const logs = []
    const remember = (line) => {
      const text = String(line || '').trim()
      if (!text) return
      logs.push(text)
      if (logs.length > 80) logs.shift()
    }
    const finish = () => {
      settled = true
      if (timer) clearTimeout(timer)
      timer = null
    }
    const fail = (message) => {
      if (settled) return
      failedStart = true
      finish()
      if (backend === child) backend = null
      try { child.kill() } catch {}
      const tail = logs.slice(-8).join('\n')
      reject(new Error(tail ? `${message}\n\n${tail}` : message))
    }

    timer = setTimeout(() => fail('本地服务启动超时（120 秒）'), LOCAL_START_TIMEOUT_MS)

    let stdoutBuffer = ''
    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      stdoutBuffer += chunk
      let index
      while ((index = stdoutBuffer.indexOf('\n')) >= 0) {
        const line = stdoutBuffer.slice(0, index).replace(/\r$/, '')
        stdoutBuffer = stdoutBuffer.slice(index + 1)
        if (!line.trim()) continue

        let event = null
        try { event = JSON.parse(line) } catch {}
        if (event && event.event === 'listening') {
          const url = normalizeUrl(event.url)
          if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(url)) {
            fail('本地服务返回了非预期的监听地址，已停止启动。')
            return
          }
          backendUrl = url
          sendLaunchStatus({ message: '正在等待本地服务就绪…', detail: '' })
          void waitForHealth(url).then((ready) => {
            if (settled) return
            if (!ready) {
              fail('本地服务启动后没有响应健康检查。')
              return
            }
            finish()
            sendLaunchStatus({ message: '本地服务已就绪', detail: '' })
            resolve(url)
          })
          return
        }
        remember(line)
      }
    })

    let stderrBuffer = ''
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk) => {
      stderrBuffer += chunk
      let index
      while ((index = stderrBuffer.indexOf('\n')) >= 0) {
        remember(stderrBuffer.slice(0, index).replace(/\r$/, ''))
        stderrBuffer = stderrBuffer.slice(index + 1)
      }
    })

    child.on('error', (err) => fail(`无法启动本地服务：${errorText(err)}`))
    child.on('exit', (code) => {
      if (backend === child) {
        backend = null
        backendUrl = ''
      }
      if (!settled) {
        fail(`本地服务异常退出（exit ${code}）`)
        return
      }
      if (failedStart || stoppingBackend || quitting) return
      if (mainWindow) {
        void showMessage({
          type: 'error',
          title: '本地服务已停止',
          message: `本地服务意外退出（exit ${code}）。`,
          detail: logs.slice(-8).join('\n') || undefined,
          buttons: ['重新启动', '打开设置', '关闭'],
          defaultId: 0,
          cancelId: 2,
        }).then(async ({ response }) => {
          if (response === 0) {
            try { await startLocalMode() } catch (err) {
              await showMessage({ type: 'error', title: '启动失败', message: errorText(err) })
            }
          } else if (response === 1) {
            await showSetupWindow()
          }
        })
      }
    })
  })
}

function stopLocalBackend() {
  const child = backend
  backend = null
  backendUrl = ''
  if (!child || child.exitCode !== null) return Promise.resolve()

  stoppingBackend = true
  return new Promise((resolve) => {
    let done = false
    let timer = null
    const finish = () => {
      if (done) return
      done = true
      if (timer) clearTimeout(timer)
      stoppingBackend = false
      resolve()
    }
    child.once('exit', finish)
    timer = setTimeout(() => {
      try { child.kill() } catch {}
      finish()
    }, LOCAL_STOP_TIMEOUT_MS)

    // 关闭 stdin 让后端走 uvicorn 的正常退出路径，从而 stop PostgreSQL。
    try { child.stdin.end() } catch {}
  })
}

/* ---------- 窗口 ---------- */

function createMainWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 880,
    minWidth: 960,
    minHeight: 600,
    backgroundColor: '#0B0C0E',
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

  let loadRetries = 0
  mainWindow.webContents.on('did-finish-load', () => {
    loadRetries = 0
  })
  // 首屏偶尔仍会连接被拒（本地服务刚 bind），重试几次再报错。
  mainWindow.webContents.on('did-fail-load', (_event, code, description, failedUrl, isMainFrame) => {
    if (!isMainFrame || code === -3) return
    if (!String(failedUrl || '').startsWith(url)) return
    if (loadRetries >= 5) {
      void showMessage({
        type: 'error',
        title: '页面加载失败',
        message: `无法打开 ${url}（${description}）`,
        buttons: ['重试', '关闭'],
        defaultId: 0,
        cancelId: 1,
      }).then(({ response }) => {
        if (response === 0 && mainWindow && !mainWindow.isDestroyed()) mainWindow.loadURL(url)
      })
      return
    }
    loadRetries += 1
    setTimeout(() => {
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.loadURL(url)
    }, 400 * loadRetries)
  })

  mainWindow.loadURL(url)
  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function createSetupWindow(savedUrl, warning) {
  setupWindow = new BrowserWindow({
    width: 600,
    height: 700,
    resizable: false,
    backgroundColor: '#0B0C0E',
    autoHideMenuBar: true,
    title: '运行 Nova Agent',
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

function createLaunchWindow() {
  if (launchWindow && !launchWindow.isDestroyed()) return launchWindow
  launchStatus = null
  launchWindow = new BrowserWindow({
    width: 460,
    height: 300,
    frame: false,
    resizable: false,
    backgroundColor: '#0B0C0E',
    title: 'Nova Agent',
    icon: path.join(__dirname, 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  launchWindow.loadFile('launch.html')
  launchWindow.webContents.on('did-finish-load', () => {
    if (launchStatus) launchWindow.webContents.send('nova:launch-status', launchStatus)
  })
  launchWindow.on('closed', () => {
    launchWindow = null
  })
  return launchWindow
}

function closeLaunchWindow() {
  if (launchWindow && !launchWindow.isDestroyed()) launchWindow.close()
  launchWindow = null
}

/* ---------- 运行方式 ---------- */

async function startLocalMode() {
  await stopLocalBackend()
  createLaunchWindow()
  const url = await startLocalBackend()
  if (quitting) return url
  saveConfig({ mode: 'local' })
  closeLaunchWindow()

  if (mainWindow) {
    mainWindow.loadURL(url)
  } else {
    createMainWindow(url)
  }
  if (setupWindow) setupWindow.close()
  setupAutoUpdate()
  return url
}

async function showSetupWindow(reason = '') {
  await stopLocalBackend()
  createSetupWindow(normalizeUrl(loadConfig().serverUrl), reason)
  if (mainWindow) mainWindow.close()
}

async function switchToLocal() {
  try {
    await startLocalMode()
  } catch (err) {
    closeLaunchWindow()
    if (quitting) return
    await showMessage({
      type: 'error',
      title: '本地服务启动失败',
      message: errorText(err),
      buttons: ['打开设置', '关闭'],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) void showSetupWindow('本地服务启动失败，可以重试或改连服务器。')
    })
  }
}

/* ---------- IPC ---------- */

ipcMain.handle('nova:start-local', async () => {
  try {
    await startLocalMode()
    return { ok: true }
  } catch (err) {
    closeLaunchWindow()
    return { ok: false, error: errorText(err) }
  }
})

ipcMain.handle('nova:connect', async (_event, rawUrl) => {
  const url = normalizeUrl(rawUrl)
  if (!/^https?:\/\/.+/.test(url)) {
    return { ok: false, error: '请输入有效的服务器地址，例如 http://192.168.1.10:8000' }
  }
  const ok = await checkServer(url)
  if (!ok) {
    return { ok: false, error: '连不上这个地址：请确认服务器已启动、地址与端口正确（health 接口不可达）' }
  }
  await stopLocalBackend()
  saveConfig({ mode: 'server', serverUrl: url })
  if (mainWindow) {
    mainWindow.loadURL(url)
  } else {
    createMainWindow(url)
  }
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
      const { response } = await showMessage({
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

/* ---------- 菜单 ---------- */

function buildMenu() {
  const template = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    {
      label: '运行',
      submenu: [
        { label: '在本机运行', click: () => void switchToLocal() },
        { label: '连接服务器…', click: () => void showSetupWindow() },
        { type: 'separator' },
        {
          label: '重新启动本地服务',
          click: async () => {
            if (!backend && loadConfig().mode !== 'local') return
            await switchToLocal()
          },
        },
        { type: 'separator' },
        { role: 'quit', label: '退出' },
      ],
    },
    {
      label: '视图',
      submenu: [
        { role: 'reload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于 Nova Agent',
          click: () => {
            const mode = backendUrl ? `本机运行 · ${backendUrl}` : '连接服务器'
            void showMessage({
              type: 'info',
              title: '关于 Nova Agent',
              message: `Nova Agent ${app.getVersion()}`,
              detail: `${mode}\n数据保存在你自己的环境里；无遥测。`,
              buttons: ['好'],
            })
          },
        },
      ],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

/* ---------- 应用生命周期 ---------- */

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = mainWindow ?? setupWindow ?? launchWindow
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(async () => {
    buildMenu()

    const cfg = loadConfig()
    const savedUrl = normalizeUrl(cfg.serverUrl)
    const mode = cfg.mode || (savedUrl ? 'server' : '')

    if (mode === 'local') {
      try {
        await startLocalMode()
      } catch (err) {
        closeLaunchWindow()
        if (!quitting) createSetupWindow(savedUrl, `本地服务启动失败：${errorText(err)}`)
      }
    } else if (mode === 'server') {
      if (savedUrl && (await checkServer(savedUrl))) {
        createMainWindow(savedUrl)
        setupAutoUpdate()
      } else {
        createSetupWindow(
          savedUrl,
          savedUrl ? '上次的服务器地址暂时连不上，可以修改后重试。' : '',
        )
      }
    } else {
      createSetupWindow(savedUrl, '')
    }

    app.on('activate', () => {
      // macOS：点 Dock 图标时若无窗口则重建
      if (BrowserWindow.getAllWindows().length > 0) return
      const nextUrl = normalizeUrl(loadConfig().serverUrl)
      if (loadConfig().mode === 'local') {
        startLocalMode().catch(() => createSetupWindow(nextUrl, '本地服务启动失败。'))
      } else if (nextUrl) {
        createMainWindow(nextUrl)
      } else {
        createSetupWindow('', '')
      }
    })
  })

  app.on('before-quit', (event) => {
    if (quitting || !backend || backend.exitCode !== null) return
    quitting = true
    event.preventDefault()
    void stopLocalBackend().finally(() => app.quit())
  })

  app.on('window-all-closed', () => {
    if (!isMac) app.quit()
  })
}
