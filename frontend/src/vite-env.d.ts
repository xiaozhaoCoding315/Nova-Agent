/// <reference types="vite/client" />

/** 构建期环境变量。ICP 备案号留空时不渲染（本地开发/桌面端/海外自托管）。 */
interface ImportMetaEnv {
  readonly VITE_ICP_BEIAN?: string
}

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
