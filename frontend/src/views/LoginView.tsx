import {
  ArrowUpRight, Check, HardDrive, Loader2, MonitorDown, Server, ShieldCheck, Terminal, X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { AuthPanel, type AuthMode } from '../components/AuthPanel'
import { HeroComposer } from '../components/HeroComposer'
import { IcpNotice } from '../components/IcpNotice'
import { StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import { useFocusTrap } from '../lib/focus'
import type { Health } from '../lib/types'
import { useAuth } from '../stores/auth'

const PROOFS = [
  {
    label: 'REFERENCE',
    value: 'src/api/orders.py:41',
    text: '每一条「文件: 行号」引用都会核验；不存在的引用直接标红。',
  },
  {
    label: 'EXECUTION',
    value: 'exit 0 · 8 passed',
    text: '命令在沙箱或本机真实执行，输出与退出码都能回看。',
  },
  {
    label: 'APPROVAL',
    value: '+12 −3 · 待批准',
    text: '补丁先展示 diff，由你批准后才写入项目。',
  },
]

const RUN_STEPS = [
  { no: '01', tool: 'grep', text: '"Order.items" src/api', meta: '2 hits' },
  { no: '02', tool: 'read', text: 'src/api/orders.py:1-84', meta: '84 lines' },
  { no: '03', tool: 'edit', text: 'src/api/orders.py', meta: '+12 −3' },
  { no: '04', tool: 'run', text: 'pytest tests/api/test_orders.py -q', meta: '8 passed' },
]

function RunLedger() {
  return (
    <div className="relative min-w-0">
      <div className="overflow-hidden rounded-xl border border-edge bg-panel/85 shadow-pop">
        <div className="flex items-center justify-between gap-3 border-b border-edge/80 px-4 py-3">
          <span className="font-mono text-2xs uppercase tracking-[0.16em] text-faint">run 0042</span>
          <span className="flex items-center gap-1.5 font-mono text-2xs text-accent">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
            verified
          </span>
        </div>

        <div className="px-4 py-4 font-mono text-sm">
          <p className="flex gap-2 text-ink">
            <span className="shrink-0 text-accent">›</span>
            <span>修复 orders 列表的 N+1 查询</span>
          </p>

          <div className="mt-4 border-l border-edge/80 pl-4">
            {RUN_STEPS.map((step) => (
              <div key={step.no} className="relative pb-3 last:pb-0">
                <span
                  className="absolute -left-[21px] top-[7px] h-px w-3 bg-edge"
                  aria-hidden="true"
                />
                <div className="flex items-baseline gap-2">
                  <span className="w-6 shrink-0 text-2xs text-faint">{step.no}</span>
                  <span className="w-9 shrink-0 text-2xs text-dim">{step.tool}</span>
                  <span className="min-w-0 flex-1 truncate text-xs text-ink/90">{step.text}</span>
                  <span className="shrink-0 text-2xs text-faint">{step.meta}</span>
                </div>
              </div>
            ))}
            <div className="relative">
              <span
                className="absolute -left-[23px] top-[6px] h-1.5 w-1.5 rounded-full bg-accent"
                aria-hidden="true"
              />
              <div className="flex items-baseline gap-2">
                <span className="w-6 shrink-0 text-2xs text-faint">05</span>
                <span className="shrink-0 text-2xs text-accent">cite</span>
                <span className="min-w-0 flex-1 truncate text-xs text-ink/90">
                  src/api/orders.py:41
                </span>
                <span className="shrink-0 text-2xs text-accent">已核验</span>
              </div>
            </div>
          </div>

          <div className="mt-4 rounded-sm border border-edge/70 bg-base/60 px-3 py-2 text-2xs leading-5">
            <p className="text-err/90"><span className="text-faint">- </span>for order in orders:</p>
            <p className="text-err/90"><span className="text-faint">- </span>    order.items</p>
            <p className="text-accent"><span className="text-faint">+ </span>selectinload(Order.items)</p>
          </div>
        </div>

        <div className="grid grid-cols-3 divide-x divide-edge/70 border-t border-edge/80 bg-base/50 text-center font-mono text-2xs">
          <div className="px-2 py-2.5">
            <p className="text-faint">引用</p>
            <p className="mt-0.5 text-accent">4 / 4</p>
          </div>
          <div className="px-2 py-2.5">
            <p className="text-faint">测试</p>
            <p className="mt-0.5 text-ink">8 passed</p>
          </div>
          <div className="px-2 py-2.5">
            <p className="text-faint">退出码</p>
            <p className="mt-0.5 text-ink">0</p>
          </div>
        </div>
      </div>
      <p className="mt-2.5 text-right font-mono text-2xs text-faint">
        一次真实会话的摘录 · 工具、引用与执行结果
      </p>
    </div>
  )
}

function RunMode({
  kind,
  title,
  text,
  points,
  action,
}: {
  kind: 'desktop' | 'server'
  title: string
  text: string
  points: string[]
  action: React.ReactNode
}) {
  const Icon = kind === 'desktop' ? HardDrive : Server
  return (
    <div className="flex min-w-0 flex-col rounded-lg border border-edge bg-panel/45 p-5">
      <div className="flex items-center gap-2">
        <Icon size={14} className="text-accent" />
        <span className="font-mono text-2xs uppercase tracking-[0.16em] text-faint">
          {kind === 'desktop' ? 'desktop client' : 'self-hosted'}
        </span>
      </div>
      <h3 className="mt-3 text-lg font-semibold text-ink">{title}</h3>
      <p className="mt-1.5 text-sm leading-6 text-dim">{text}</p>
      <ul className="mt-4 space-y-2 font-mono text-xs text-dim">
        {points.map((point) => (
          <li key={point} className="flex gap-2">
            <span className="text-accent" aria-hidden="true">─</span>
            <span className="min-w-0">{point}</span>
          </li>
        ))}
      </ul>
      <div className="mt-5 pt-1">{action}</div>
    </div>
  )
}

const primaryAction =
  'inline-flex items-center justify-center gap-2 rounded-md bg-accent px-4 py-2.5 text-base font-semibold text-graphite transition-colors duration-150 hover:bg-accent/85'
const secondaryAction =
  'inline-flex items-center justify-center gap-2 rounded-md border border-edge px-4 py-2.5 text-base text-ink transition-colors duration-150 hover:border-accent/40 hover:text-accent'

export function LoginView() {
  const { guest, loadConfig, config } = useAuth()
  const [authOpen, setAuthOpen] = useState(false)
  const authPanelRef = useRef<HTMLDivElement>(null)
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [authNonce, setAuthNonce] = useState(0)
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

  useEffect(() => {
    if (!authOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAuthOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
    }
  }, [authOpen])

  useFocusTrap(authPanelRef, authOpen)

  const openAuth = (mode: AuthMode) => {
    setAuthMode(mode)
    setAuthNonce((value) => value + 1)
    setGuestError(null)
    setAuthOpen(true)
  }

  const startGuest = async () => {
    setGuestBusy(true)
    setGuestError(null)
    try {
      await guest()
      setAuthOpen(false)
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
  const guestEnabled = config?.guest_enabled !== false
  const downloadLabel = '下载 Windows 版'

  return (
    <div className="relative min-h-screen overflow-hidden bg-base">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(to right, rgba(237,232,222,0.045) 1px, transparent 1px), linear-gradient(to bottom, rgba(237,232,222,0.045) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse 70% 55% at 50% 0%, black 0%, transparent 100%)',
          WebkitMaskImage: 'radial-gradient(ellipse 70% 55% at 50% 0%, black 0%, transparent 100%)',
        }}
      />

      <header className="relative z-10 mx-auto flex w-full max-w-6xl items-center gap-3 px-5 py-5 md:px-8">
        <a href="/" className="flex items-center gap-2.5" aria-label="Nova Agent 首页">
          <span className="grid h-7 w-7 place-items-center rounded-sm border border-accent/40 bg-accentSoft/40 font-mono text-sm font-semibold text-accent">
            N
          </span>
          <span className="font-mono text-xs font-medium uppercase tracking-[0.22em] text-ink">
            Nova Agent
          </span>
        </a>

        <nav className="ml-6 hidden items-center gap-5 text-xs text-dim md:flex" aria-label="页面导航">
          <a className="transition-colors hover:text-ink" href="#proof">证据</a>
          <a className="transition-colors hover:text-ink" href="#ledger">账本</a>
          <a className="transition-colors hover:text-ink" href="#run-modes">运行方式</a>
          <a className="transition-colors hover:text-ink" href="#download">下载</a>
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <span className="mr-1 hidden items-center gap-1.5 text-2xs text-faint sm:flex" role="status" aria-live="polite">
            <StatusDot state={healthState} />
            {healthLabel}
          </span>
          {guestEnabled && (
            <button
              onClick={() => void startGuest()}
              disabled={guestBusy}
              className="hidden rounded-md px-2.5 py-1.5 text-sm text-dim transition-colors hover:text-ink disabled:cursor-not-allowed disabled:opacity-50 sm:inline-flex sm:items-center sm:gap-1.5"
            >
              {guestBusy && <Loader2 size={12} className="animate-spin" />}
              游客试用
            </button>
          )}
          <button
            onClick={() => openAuth('login')}
            className="rounded-md border border-edge px-3 py-1.5 text-sm text-ink transition-colors duration-150 hover:border-accent/40"
          >
            登录
          </button>
          <a href="/downloads" className="hidden rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-graphite transition-colors duration-150 hover:bg-accent/85 sm:block">
            下载
          </a>
        </div>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-6xl px-5 md:px-8">
        <section className="grid gap-10 pb-16 pt-10 md:pt-16 lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:gap-14">
          <div className="min-w-0">
            <p className="flex items-center gap-2 font-mono text-2xs uppercase tracking-[0.18em] text-dim">
              <span className="h-px w-6 bg-accent/60" aria-hidden="true" />
              self-hosted engineering agent
            </p>

            <h1 className="mt-5 text-3xl font-semibold leading-[1.2] tracking-tight text-ink sm:text-4xl sm:leading-[1.15] lg:text-5xl">
              每个结论，
              <br />
              都能回到<span className="text-accent">那一行代码</span>。
            </h1>

            <p className="mt-5 max-w-lg text-md leading-7 text-dim">
              Nova Agent 在你的项目里读写文件、运行测试、核对引用。
              它不做没有证据的断言，也不把未验证的补丁交给你。
            </p>

            <div className="mt-7 flex flex-wrap items-center gap-3">
              <a href="/downloads" className={primaryAction}>
                <MonitorDown size={15} />
                {downloadLabel}
                <ArrowUpRight size={14} className="opacity-70" />
              </a>
              {guestEnabled ? (
                <button onClick={() => void startGuest()} disabled={guestBusy} className={secondaryAction}>
                  {guestBusy ? <Loader2 size={14} className="animate-spin" /> : <Terminal size={14} />}
                  在此服务器试用
                </button>
              ) : (
                <button onClick={() => openAuth('login')} className={secondaryAction}>
                  <Terminal size={14} />
                  登录工作区
                </button>
              )}
            </div>

            <p className="mt-4 font-mono text-2xs leading-5 text-faint">
              Windows 安装包 · 本机运行或连接服务器 · 无遥测
            </p>
            {guestError && (
              <p className="mt-3 text-sm text-err" role="alert">{guestError}</p>
            )}
          </div>

          <HeroComposer onStart={() => openAuth('login')} />
        </section>

        <section id="proof" className="border-y border-edge/60" aria-label="证据链">
          <div className="grid divide-y divide-edge/60 md:grid-cols-3 md:divide-x md:divide-y-0">
            {PROOFS.map((proof) => (
              <div key={proof.label} className="py-6 md:px-6 md:first:pl-0 md:last:pr-0">
                <p className="font-mono text-2xs uppercase tracking-[0.16em] text-faint">{proof.label}</p>
                <p className="mt-2 font-mono text-sm text-ink">{proof.value}</p>
                <p className="mt-1.5 text-xs leading-5 text-dim">{proof.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="ledger" className="grid gap-8 py-16 md:py-20 lg:grid-cols-[0.85fr_1.15fr] lg:items-start lg:gap-14">
          <div className="min-w-0">
            <p className="font-mono text-2xs uppercase tracking-[0.18em] text-faint">one run</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink md:text-3xl">
              一次会话留下的，是一条可复查的账本。
            </h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-dim">
              每一步工具调用都记着参数与结果，每一条引用都指向真实文件行，
              补丁在写入前以 diff 呈现。会话结束后，这条账本仍然在。
            </p>
            <ul className="mt-5 space-y-2 font-mono text-xs text-dim">
              {[
                '工具、命令与退出码逐条留痕',
                '引用核验：不存在或越界的行号直接标红',
                '未验证的结论会被显式标为未验证',
              ].map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="text-accent" aria-hidden="true">─</span>
                  <span className="min-w-0">{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <RunLedger />
        </section>

        <section id="run-modes" className="py-16 md:py-20">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="font-mono text-2xs uppercase tracking-[0.18em] text-faint">run modes</p>
              <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink md:text-3xl">
                把你的环境，变成工作台。
              </h2>
            </div>
            <p className="max-w-sm text-sm leading-6 text-dim">
              桌面客户端或自托管服务器，共用同一套工具、证据与审批流程。
            </p>
          </div>

          <div className="mt-8 grid gap-4 md:grid-cols-2">
            <RunMode
              kind="desktop"
              title="桌面客户端"
              text="安装到本机后可以直接在本机运行（自带后端与数据库），也可以连接你自己的 Nova 服务器。"
              points={['本机运行，数据不离开这台电脑', '或连接已有服务器，共用账号与会话', '下载文件落到你选择的目录', 'Windows 安装包；macOS / Linux 构建中']}
              action={(
                <a href="/downloads" className={primaryAction}>
                  <MonitorDown size={15} />
                  {downloadLabel}
                </a>
              )}
            />
            <RunMode
              kind="server"
              title="自托管服务器"
              text="一条 docker compose 命令启动完整工作台。项目、索引与密钥都留在你的机器上。"
              points={['Docker 沙箱执行命令', '多用户、配额与邀请码', '浏览器直接打开，无需安装', '支持团队共享项目']}
              action={(
                <button onClick={() => openAuth('login')} className={secondaryAction}>
                  <Server size={14} />
                  登录此服务器
                </button>
              )}
            />
          </div>
        </section>

        <section id="download" className="mb-16 rounded-xl border border-edge bg-panel/50 px-5 py-7 md:px-8 md:py-8">
          <div className="flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <p className="font-mono text-2xs uppercase tracking-[0.18em] text-faint">get started</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight text-ink md:text-2xl">
                把 Nova 放到你自己的环境里。
              </h2>
              <p className="mt-1.5 text-sm leading-6 text-dim">
                桌面客户端，或者一条 docker compose 命令。没有云端账号，没有数据托管。
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <a href="/downloads" className={primaryAction}>
                <MonitorDown size={15} />
                {downloadLabel}
              </a>
              <button onClick={() => openAuth('register')} className={secondaryAction}>
                <ShieldCheck size={14} />
                创建工作区
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-edge/60">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-2 gap-y-1 px-5 py-5 text-2xs text-faint md:px-8">
          <span className="flex items-center gap-1.5" role="status" aria-live="polite">
            <StatusDot state={healthState} />
            {healthLabel}
          </span>
          <span aria-hidden="true">·</span>
          <span className="font-mono">v{health?.version ?? '2.2.1'}</span>
          <span aria-hidden="true">·</span>
          <span>无遥测</span>
          <span className="ml-auto hidden items-center gap-2 font-mono uppercase tracking-[0.16em] md:flex">
            <IcpNotice className="normal-case tracking-normal text-dim hover:text-ink" />
            Nova Agent / evidence-first
          </span>
        </div>
      </footer>

      {authOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-black/70 p-4 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAuthOpen(false)
          }}
        >
          <div
            ref={authPanelRef}
            tabIndex={-1}
            className="relative w-full max-w-[420px] py-6 outline-none"
            role="dialog"
            aria-modal="true"
            aria-label="登录与注册"
          >
            <button
              onClick={() => setAuthOpen(false)}
              className="absolute right-3 top-7 z-10 rounded-md p-1.5 text-dim transition-colors hover:bg-raised hover:text-ink"
              aria-label="关闭登录窗口"
            >
              <X size={16} />
            </button>
            <AuthPanel
              key={authNonce}
              initialMode={authMode}
              onDone={() => setAuthOpen(false)}
            />
            {guestEnabled && (
              <button
                onClick={() => void startGuest()}
                disabled={guestBusy}
                className="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md border border-edge bg-base/50 px-3 py-2 text-sm text-dim transition-colors hover:border-accent/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-50"
              >
                {guestBusy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                不注册，以游客身份试用
              </button>
            )}
            {guestError && <p className="mt-2 text-center text-sm text-err" role="alert">{guestError}</p>}
          </div>
        </div>
      )}
    </div>
  )
}
