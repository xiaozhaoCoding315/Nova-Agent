import {
  ArrowLeft, Check, Copy, HardDrive, Loader2, MonitorDown, RefreshCw, Server, Terminal,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { IcpNotice } from '../components/IcpNotice'
import { StatusDot } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { DownloadFile, DownloadsListing, Health } from '../lib/types'
import { formatBytes } from '../lib/ui'

const STEPS = [
  {
    no: '01',
    title: '下载并安装',
    text: '安装包支持覆盖升级；项目、会话与索引都在数据目录里，不会因为重装而丢失。',
  },
  {
    no: '02',
    title: '选择运行方式',
    text: '首次启动会让你二选一：在本机运行（自带后端与数据库），或连接一台已有的 Nova 服务器。',
  },
  {
    no: '03',
    title: '填入服务器地址',
    text: '连服务器时填写形如 http://<服务器IP>:8000 的地址，然后用在网页端注册的同一套账号登录。',
  },
]

function platformIcon(platform: string) {
  if (platform === 'Windows') return MonitorDown
  return HardDrive
}

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function FileRow({ file }: { file: DownloadFile }) {
  const Icon = platformIcon(file.platform)
  return (
    <a
      href={file.url}
      download
      className="group flex items-center gap-3 rounded-lg border border-edge bg-panel px-4 py-3 transition-colors duration-150 hover:border-accent/50 hover:bg-raised"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-edge bg-base/60 text-accent">
        <Icon size={16} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="rounded-sm bg-accentSoft px-1.5 py-0.5 font-mono text-2xs uppercase tracking-[0.12em] text-accent">
            {file.platform}
          </span>
          <span className="min-w-0 break-all font-mono text-sm text-ink">{file.name}</span>
        </span>
        <span className="mt-0.5 block font-mono text-2xs text-faint">
          {formatBytes(file.size)} · {formatDate(file.modified_at)}
        </span>
      </span>
      <span className="shrink-0 font-mono text-2xs text-dim transition-colors group-hover:text-accent">
        下载
      </span>
    </a>
  )
}

export function DownloadsView() {
  const [listing, setListing] = useState<DownloadsListing | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [copied, setCopied] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      setListing(await api.downloads())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '读取安装包列表失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    api.status.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  const origin = window.location.origin
  const copyOrigin = async () => {
    try {
      await navigator.clipboard.writeText(origin)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* 剪贴板不可用时用户仍可手动选中 */
    }
  }

  const files = listing?.files ?? []
  const windowsFile = files.find((file) => file.platform === 'Windows') ?? files[0]
  const others = files.filter((file) => file !== windowsFile)

  return (
    <div className="relative min-h-screen bg-base">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(to right, rgba(237,232,222,0.045) 1px, transparent 1px), linear-gradient(to bottom, rgba(237,232,222,0.045) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse 70% 50% at 50% 0%, black 0%, transparent 100%)',
          WebkitMaskImage: 'radial-gradient(ellipse 70% 50% at 50% 0%, black 0%, transparent 100%)',
        }}
      />

      <header className="relative z-10 mx-auto flex w-full max-w-4xl items-center gap-3 px-5 py-5 md:px-8">
        <a href="/" className="flex items-center gap-2.5" aria-label="Nova Agent 首页">
          <span className="grid h-7 w-7 place-items-center rounded-sm border border-accent/40 bg-accentSoft/40 font-mono text-sm font-semibold text-accent">
            N
          </span>
          <span className="font-mono text-xs font-medium uppercase tracking-[0.22em] text-ink">
            Nova Agent
          </span>
        </a>
        <a
          href="/"
          className="ml-auto flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-dim transition-colors hover:text-ink"
        >
          <ArrowLeft size={13} />
          返回工作台
        </a>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-4xl px-5 pb-20 md:px-8">
        <p className="font-mono text-2xs uppercase tracking-[0.18em] text-faint">desktop client</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          在桌面打开 Nova Agent
        </h1>
        <p className="mt-3 max-w-2xl text-md leading-7 text-dim">
          安装包有两种用法：在本机运行（自带后端与数据库，数据留在这台电脑），
          或连接本服务器（项目、会话与执行结果保存在服务器上）。
          也可以不安装任何东西，直接在浏览器里使用同一个工作台。
        </p>

        <div className="mt-7 rounded-xl border border-edge bg-panel/60 p-4 md:p-5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-medium text-ink">安装包</h2>
            <span className="font-mono text-2xs text-faint">
              {loading ? '读取中…' : `${files.length} 个文件`}
            </span>
            <button
              onClick={() => void load()}
              disabled={loading}
              className="ml-auto flex h-7 items-center gap-1.5 rounded-md px-2 text-xs text-dim transition-colors hover:bg-raised hover:text-ink disabled:opacity-50"
            >
              {loading ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
              刷新
            </button>
          </div>

          <div className="mt-3 space-y-2">
            {error && (
              <p className="rounded-md border border-err/40 bg-err/10 px-3 py-2 text-sm text-err" role="alert">
                {error}
              </p>
            )}
            {!error && loading && !listing && (
              <div className="flex items-center gap-2 rounded-md border border-edge/70 px-3 py-6 text-sm text-dim">
                <Loader2 size={13} className="animate-spin" />
                正在读取安装包目录…
              </div>
            )}
            {!error && listing && files.length === 0 && (
              <div className="rounded-md border border-dashed border-edge px-4 py-6 text-sm leading-6 text-dim">
                暂无安装包。
                {listing.hint || '管理员把安装包放进下载目录后刷新本页即可。'}
                <span className="mt-1 block font-mono text-2xs text-faint">{listing.directory}</span>
              </div>
            )}
            {windowsFile && <FileRow file={windowsFile} />}
            {others.map((file) => <FileRow key={file.name} file={file} />)}
          </div>

          <p className="mt-3 text-2xs leading-5 text-faint">
            覆盖安装即可升级，数据不受影响。本机运行没有容器隔离，Agent 执行的命令会直接影响那台电脑；
            需要隔离时请连接服务器，用 Docker 沙箱执行。
          </p>
        </div>

        <section className="mt-10" aria-label="安装步骤">
          <h2 className="text-lg font-semibold text-ink">三步接入</h2>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {STEPS.map((step) => (
              <div key={step.no} className="rounded-lg border border-edge bg-panel/40 p-4">
                <span className="font-mono text-2xs text-accent">{step.no}</span>
                <p className="mt-1.5 text-base font-medium text-ink">{step.title}</p>
                <p className="mt-1 text-xs leading-5 text-dim">{step.text}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-8 grid gap-3 md:grid-cols-2" aria-label="两种运行方式">
          <div className="rounded-lg border border-edge bg-panel/40 p-4">
            <div className="flex items-center gap-2">
              <HardDrive size={14} className="text-accent" />
              <span className="font-mono text-2xs uppercase tracking-[0.16em] text-faint">local</span>
            </div>
            <p className="mt-2 text-base font-medium text-ink">在本机运行</p>
            <ul className="mt-2 space-y-1.5 text-xs leading-5 text-dim">
              {['数据不离开这台电脑', '无需服务器，也不需要 Docker', '适合单人使用与离线环境'].map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="text-accent" aria-hidden="true">─</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-edge bg-panel/40 p-4">
            <div className="flex items-center gap-2">
              <Server size={14} className="text-accent" />
              <span className="font-mono text-2xs uppercase tracking-[0.16em] text-faint">server</span>
            </div>
            <p className="mt-2 text-base font-medium text-ink">连接本服务器</p>
            <ul className="mt-2 space-y-1.5 text-xs leading-5 text-dim">
              {['命令在 Docker 沙箱里执行', '项目与会话跟着账号走', '团队可共享同一个项目'].map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="text-accent" aria-hidden="true">─</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex items-center gap-2 rounded-md border border-edge bg-base/60 px-2.5 py-1.5">
              <Terminal size={12} className="shrink-0 text-faint" />
              <span className="min-w-0 flex-1 truncate font-mono text-2xs text-dim">{origin}</span>
              <button
                onClick={() => void copyOrigin()}
                className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-2xs text-dim transition-colors hover:bg-raised hover:text-ink"
                title="复制服务器地址"
              >
                {copied ? <Check size={11} className="text-ok" /> : <Copy size={11} />}
                {copied ? '已复制' : '复制'}
              </button>
            </div>
          </div>
        </section>

        <section className="mt-8 rounded-xl border border-edge bg-panel/50 px-4 py-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-base font-medium text-ink">不想装任何东西？</p>
              <p className="mt-0.5 text-xs leading-5 text-dim">
                浏览器里是同一个工作台：登录后即可导入项目、提问与查看证据。
              </p>
            </div>
            <a
              href="/"
              className="inline-flex shrink-0 items-center justify-center gap-2 rounded-md bg-accent px-4 py-2 text-base font-semibold text-graphite transition-colors duration-150 hover:bg-accent/85"
            >
              <Terminal size={14} />
              在浏览器中打开
            </a>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-edge/60">
        <div className="mx-auto flex w-full max-w-4xl flex-wrap items-center gap-x-2 gap-y-1 px-5 py-5 text-2xs text-faint md:px-8">
          <span className="flex items-center gap-1.5">
            <StatusDot state={health ? (health.status === 'ok' ? 'ok' : 'warn') : 'warn'} />
            {health ? (health.status === 'ok' ? '服务正常' : '部分降级') : '服务离线'}
          </span>
          <span aria-hidden="true">·</span>
          <span className="font-mono">v{health?.version ?? '—'}</span>
          <span aria-hidden="true">·</span>
          <span>无遥测</span>
          <span className="ml-auto hidden items-center gap-2 font-mono uppercase tracking-[0.16em] md:flex">
            <IcpNotice className="normal-case tracking-normal text-dim hover:text-ink" />
            Nova Agent / evidence-first
          </span>
        </div>
      </footer>
    </div>
  )
}
