/// <reference types="vite/client" />

/** 桌面壳（Electron）通过 preload 暴露的桥；浏览器/服务器模式下不存在。 */
interface NovaDesktopBridge {
  connect(url: string): Promise<{ ok: boolean; error?: string }>
  startLocal(): Promise<{ ok: boolean; error?: string }>
  pickDirectory(): Promise<{ ok: boolean; path?: string; canceled?: boolean }>
  onLaunchStatus(callback: (payload: unknown) => void): () => void
}

interface Window {
  novaDesktop?: NovaDesktopBridge
}
