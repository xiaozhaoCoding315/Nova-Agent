import { ArrowLeft, Compass, FolderSearch, Terminal } from 'lucide-react'

/** 命中的最近似路径（只按前缀猜，不做全文检索）。 */
const SUGGESTIONS = [
  { path: '/', label: '工作台' },
  { path: '/downloads', label: '下载桌面客户端' },
]

/**
 * 404：Nova 是单页应用，之前未匹配的路径会静默回落到首页，用户会以为
 * 自己进错了地方。这里显式接住，并给出两条真正存在的去处。
 */
export function NotFoundView() {
  const path = window.location.pathname
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-base px-5 py-16">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(to right, rgba(237,232,222,0.045) 1px, transparent 1px), linear-gradient(to bottom, rgba(237,232,222,0.045) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse 60% 50% at 50% 40%, black 0%, transparent 100%)',
          WebkitMaskImage: 'radial-gradient(ellipse 60% 50% at 50% 40%, black 0%, transparent 100%)',
        }}
      />

      <div className="relative z-10 w-full max-w-md">
        {/* 一条断裂的轨道：信号从这里断了，正好是 404 的意思。 */}
        <svg viewBox="0 0 320 64" className="mx-auto mb-8 w-full max-w-[280px]" aria-hidden="true">
          <line x1="0" y1="32" x2="118" y2="32" stroke="currentColor" strokeWidth="1" className="text-edge" />
          <line x1="202" y1="32" x2="320" y2="32" stroke="currentColor" strokeWidth="1" className="text-edge" />
          <circle cx="132" cy="32" r="3" fill="currentColor" className="text-accent" />
          <circle cx="160" cy="32" r="9" fill="none" stroke="currentColor" strokeWidth="1" className="text-faint" />
          <circle cx="188" cy="32" r="3" fill="currentColor" className="text-faint" />
          <text x="160" y="14" textAnchor="middle" className="fill-faint font-mono text-[9px]">signal lost</text>
        </svg>

        <p className="text-center font-mono text-2xs uppercase tracking-[0.2em] text-faint">404</p>
        <h1 className="mt-2 text-center text-2xl font-semibold tracking-tight text-ink">
          这条路径没有对应的工作区
        </h1>
        <p className="mt-2 text-center text-sm leading-6 text-dim">
          链接可能已经失效，或者地址拼错了一个字符。
          <span className="mt-1 block break-all font-mono text-2xs text-faint">{path}</span>
        </p>

        <div className="mt-7 space-y-2">
          {SUGGESTIONS.map((item) => (
            <a
              key={item.path}
              href={item.path}
              className="group flex items-center gap-3 rounded-lg border border-edge bg-panel px-3.5 py-3 transition-colors duration-150 hover:border-accent/50 hover:bg-raised"
            >
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-edge bg-base/60 text-dim group-hover:text-accent">
                {item.path === '/' ? <Terminal size={13} /> : <FolderSearch size={13} />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-sm text-ink">{item.label}</span>
                <span className="block font-mono text-2xs text-faint">{item.path}</span>
              </span>
              <ArrowLeft size={13} className="shrink-0 rotate-180 text-faint group-hover:text-accent" />
            </a>
          ))}
        </div>

        <p className="mt-6 flex items-center justify-center gap-1.5 text-center font-mono text-2xs text-faint">
          <Compass size={11} />
          直接回到首页重新开始即可，会话都还在。
        </p>
      </div>
    </div>
  )
}
