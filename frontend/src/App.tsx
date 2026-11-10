import { AppShell } from './shell/AppShell'
import { DownloadsView } from './views/DownloadsView'
import { NotFoundView } from './views/NotFoundView'

/**
 * 极简路由：这个应用只有三个入口（工作台、下载页、404），
 * 为一个 `pathname` 判断引入路由库不划算。
 *
 * 后端 `/downloads` 已经接住并返回 SPA 外壳（见 backend/app/main.py），
 * 所以这里只需按路径挑组件，不需要 history 监听——站内跳转都是整页导航。
 */
export default function App() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/'
  if (path === '/downloads') return <DownloadsView />
  if (path === '/') return <AppShell />
  return <NotFoundView />
}
