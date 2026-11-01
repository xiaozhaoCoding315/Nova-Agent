import { Bot, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { AuthPanel, type AuthMode } from '../components/AuthPanel'
import { StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Health } from '../lib/types'
import { useAuth } from '../stores/auth'

const CAPABILITIES = [
  {
    no: '01',
    title: '证据引用',
    text: '每条「文件: 行号」引用逐条核验，编造的引用直接标红。',
  },
  {
    no: '02',
    title: '真实执行',
    text: '补丁在隔离沙箱里跑通测试，以退出码为准，再交给你批准。',
  },
  {
    no: '03',
    title: '本地优先',
    text: '自托管部署，项目、会话与密钥留在你的服务器；可接入本机执行器。',
  },
]

export function LoginView() {
  const { guest, loadConfig, config } = useAuth()
  const [authRequest, setAuthRequest] = useState<{ mode: AuthMode; nonce: number }>({
    mode: 'login',
    nonce: 0,
  })
  const [guestBusy, setGuestBusy] = useState(false)
  const [guestError, setGuestError] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [healthFailed, setHealthFailed] = useState(false)

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    let alive = true
    api.status.health()
      .then((value) => {
        if (!alive) return
        setHealth(value)
        setHealthFailed(false)
      })
      .catch(() => {
        if (alive) setHealthFailed(true)
      })
    return () => {
      alive = false
    }
  }, [])

  const openAuth = (mode: AuthMode) => {
    setAuthRequest((value) => ({ mode, nonce: value.nonce + 1 }))
  }

  const startGuest = async () => {
    setGuestBusy(true)
    setGuestError(null)
    try {
      await guest()
    } catch (err) {
      setGuestError(err instanceof ApiError ? err.message : '游客体验启动失败')
    } finally {
      setGuestBusy(false)
    }
  }

  const healthState = healthFailed
    ? 'err'
    : health
      ? health.status === 'ok' ? 'ok' : 'warn'
      : 'warn'
  const healthLabel = healthFailed
    ? '服务离线'
    : health
      ? health.status === 'ok' ? '服务正常' : '部分降级'
      : '正在检测服务…'

  return (
    <div className="flex min-h-screen flex-col bg-base">
      <header className="flex flex-wrap items-center justify-end gap-2 px-5 py-4 md:px-8">
        {guestError && (
          <p className="mr-auto min-w-0 text-sm text-err" role="alert">{guestError}</p>
        )}
        {config?.guest_enabled !== false && (
          <button
            onClick={() => void startGuest()}
            disabled={guestBusy}
            className="flex items-center gap-1.5 rounded-md border border-edge px-3 py-1.5 text-sm text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
          >
            {guestBusy ? <Loader2 size={12} className="animate-spin" /> : null}
            游客体验
          </button>
        )}
        <button
          onClick={() => openAuth('register')}
          className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-graphite transition-colors duration-150 hover:bg-accent/85"
        >
          注册
        </button>
      </header>

      <main className="flex flex-1 items-center justify-center px-5 pb-12 md:px-8">
        <div className="grid w-full max-w-[960px] gap-10 py-8 md:grid-cols-2 md:items-center md:gap-16">
          <section className="min-w-0">
            <div className="flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accentSoft">
                <Bot size={18} className="text-accent" />
              </div>
              <div className="min-w-0">
                <p className="font-mono text-lg font-medium uppercase tracking-[0.16em] text-ink">
                  NOVA AGENT
                </p>
                <p className="text-xs text-faint">自托管的工程 Agent</p>
              </div>
            </div>

            <p className="mt-5 max-w-md text-2xl font-semibold leading-snug tracking-tight text-ink">
              不止生成代码，
              <br />
              每个结论都带着证据。
            </p>
            <p className="mt-3 hidden max-w-md text-sm leading-relaxed text-dim md:block">
              读懂你的代码仓库，回答附可核验的「文件: 行号」引用；改动先在沙箱真实验证，再交给你批准。
            </p>

            <ol className="mt-8 hidden space-y-4 md:block">
              {CAPABILITIES.map(({ no, title, text }) => (
                <li key={no} className="flex gap-3">
                  <span className="mt-0.5 font-mono text-xs text-accent">{no}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-ink">{title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-dim">{text}</p>
                  </div>
                </li>
              ))}
            </ol>
          </section>

          <section className="min-w-0" aria-label="认证">
            <AuthPanel
              key={authRequest.nonce}
              initialMode={authRequest.mode}
              onDone={() => undefined}
            />
          </section>
        </div>
      </main>

      <footer className="flex items-center gap-2 border-t border-edge/60 px-5 py-4 text-2xs text-faint md:px-8">
        <span className="flex items-center gap-1.5">
          <StatusDot state={healthState} />
          {healthLabel}
        </span>
        <span aria-hidden="true">·</span>
        <span className="font-mono">v{health?.version ?? '2.0.0'}</span>
        <span className="ml-auto hidden md:inline">Nova Agent · 可自托管的工程 Agent</span>
      </footer>
    </div>
  )
}
