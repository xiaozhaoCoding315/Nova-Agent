import clsx from 'clsx'
import {
  Bot, BrainCircuit, CheckCircle2, ChevronRight, Download, FlaskConical, Fingerprint,
  KeyRound, Loader2, MonitorDown, Moon, ShieldCheck, Sparkles,
  TerminalSquare, UserPlus, Wand2, X, XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../stores/auth'
import { Spinner } from '../components/common'

type Mode = 'login' | 'register' | 'reset'

const inputClass =
  'w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none placeholder:text-dim/60 focus:border-accentSoft'

/* ================= 滚动进场 ================= */

function useRevealAll() {
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in')
          observer.unobserve(entry.target)
        }
      }),
      { threshold: 0.1 },
    )
    document.querySelectorAll('.reveal').forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])
}

function useInView<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        if (entry.isIntersecting) {
          setInView(true)
          observer.disconnect()
        }
      }),
      { threshold: 0.25 },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return { ref, inView }
}

/* ================= 自打字终端 ================= */

type TermLine = { kind: 'cmd' | 'tool' | 'ok' | 'note'; text: string; tail?: string }

const TERM_SCRIPT: TermLine[] = [
  { kind: 'cmd', text: 'nova "结算时折扣超过 100% 会把总价算成负数，帮我修掉"' },
  { kind: 'tool', text: 'search_code', tail: 'app/pricing.py:42' },
  { kind: 'tool', text: 'run_code · 复现测试', tail: 'exit 1 · 红 ✓ 符合预期' },
  { kind: 'tool', text: 'write_files · 最小补丁', tail: '+2 −1' },
  { kind: 'tool', text: 'run_code · 全量测试', tail: '3 passed · exit 0 · 绿' },
  { kind: 'ok', text: '修复完成，等待用户批准写入仓库' },
  { kind: 'note', text: '证据：引用核验 2/2 通过 · 沙箱实测 · 全程 42s' },
]

function TerminalHero() {
  const [lineCount, setLineCount] = useState(0)
  const [typed, setTyped] = useState('')
  const [runId, setRunId] = useState(0)

  useEffect(() => {
    let alive = true
    const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))
    const run = async () => {
      while (alive) {
        setRunId((v) => v + 1)
        setLineCount(0)
        setTyped('')
        await sleep(700)
        if (!alive) return
        // 逐行推进；首行打字机，其余行渐现
        const first = TERM_SCRIPT[0]
        for (let i = 1; i <= first.text.length; i++) {
          if (!alive) return
          setTyped(first.text.slice(0, i))
          await sleep(26)
        }
        await sleep(350)
        if (!alive) return
        for (let count = 1; count <= TERM_SCRIPT.length; count++) {
          if (!alive) return
          setLineCount(count)
          await sleep(count === 1 ? 250 : 620)
        }
        await sleep(3600)
      }
    }
    void run()
    return () => { alive = false }
  }, [])

  const done = lineCount >= TERM_SCRIPT.length
  return (
    <div className="relative mx-auto mt-12 w-full max-w-3xl">
      <div className="absolute -inset-6 rounded-3xl bg-accent/8 blur-2xl" aria-hidden />
      <div className="nova-sweep relative overflow-hidden rounded-2xl border border-edge bg-panel/90 text-left shadow-2xl">
        <div className="flex items-center gap-1.5 border-b border-edge/70 bg-base/70 px-4 py-2.5">
          <span className="h-2.5 w-2.5 rounded-full bg-err/60" />
          <span className="h-2.5 w-2.5 rounded-full bg-warn/60" />
          <span className="h-2.5 w-2.5 rounded-full bg-ok/60" />
          <span className="ml-2 font-mono text-[10.5px] text-dim">nova — 会话</span>
          <span className="ml-auto flex items-center gap-1 rounded border border-accentSoft/40 bg-accentSoft/10 px-1.5 py-0.5 text-[9.5px] text-accent">
            <ShieldCheck size={9} /> 引用核验
          </span>
        </div>
        <div className="min-h-[300px] px-5 py-4 font-mono text-[12.5px] leading-[1.9]">
          {lineCount >= 1 && (
            <p key={`c${runId}`} className="text-ink">
              <span className="text-accent">❯</span> {typed}
              {lineCount === 1 && <span className="nova-caret text-accent">▍</span>}
            </p>
          )}
          {TERM_SCRIPT.slice(1, Math.max(1, lineCount)).map((line, index) => (
            <p key={`${runId}-${index}`} className="anim-pop flex items-baseline gap-2 pl-4">
              {line.kind === 'tool' && <span className="text-dim/70">⚙</span>}
              {line.kind === 'ok' && <CheckCircle2 size={12} className="shrink-0 translate-y-[2px] text-ok" />}
              {line.kind === 'note' && <span className="text-dim/50">└</span>}
              <span className={clsx(
                line.kind === 'tool' && 'text-dim',
                line.kind === 'ok' && 'text-ok',
                line.kind === 'note' && 'text-dim/70',
              )}>
                {line.text}
              </span>
              {line.tail && (
                <span className={clsx(
                  'ml-auto shrink-0 text-[11px]',
                  line.tail.includes('exit 1') && 'text-warn',
                  (line.tail.includes('exit 0') || line.tail.includes('passed')) && 'text-ok',
                  !line.tail.includes('exit') && !line.tail.includes('passed') && 'text-dim/60',
                )}>
                  {line.tail}
                </span>
              )}
            </p>
          ))}
          {done && (
            <p key={`wait${runId}`} className="anim-pop pl-4 pt-1 text-[11.5px] text-accent">
              <span className="nova-caret">▍</span> 等待用户批准…
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

/* ================= Bento 能力网格 ================= */

function BentoGrid() {
  return (
    <div className="grid auto-rows-[minmax(150px,auto)] grid-cols-2 gap-3 lg:grid-cols-4">
      {/* 大格：红绿验证门 */}
      <div className="reveal col-span-2 row-span-2 overflow-hidden rounded-2xl border border-edge bg-panel/60 p-5 transition-colors hover:border-accentSoft/60">
        <FlaskConical size={16} className="text-accent" />
        <h3 className="mt-2 text-[15px] font-semibold">红绿验证门</h3>
        <p className="mt-1.5 max-w-md text-[12px] leading-relaxed text-dim">
          修 Bug 先写一个失败的测试（红），补丁必须让它转绿并跑通全量测试。
          结论来自沙箱的真实退出码，不是模型的口头承诺。
        </p>
        <RedGreenViz />
      </div>

      {/* 引用核验 */}
      <div className="reveal rounded-2xl border border-edge bg-panel/60 p-4 transition-colors hover:border-accentSoft/60" style={{ transitionDelay: '80ms' }}>
        <Fingerprint size={15} className="text-accent" />
        <h3 className="mt-1.5 text-[13.5px] font-semibold">引用核验器</h3>
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">每条「文件: 行号」引用逐条校验，编造直接标红。</p>
        <div className="mt-3 space-y-1.5 font-mono text-[10px]">
          <p className="flex items-center gap-1.5 text-ok"><CheckCircle2 size={10} /> app/pricing.py:42 ✓</p>
          <p className="flex items-center gap-1.5 text-ok"><CheckCircle2 size={10} /> tests/test_pricing.py:12 ✓</p>
          <p className="flex items-center gap-1.5 text-err line-through"><XCircle size={10} /> utils/calc.py:99 幻觉</p>
        </div>
      </div>

      {/* 夜间队列 */}
      <div className="reveal rounded-2xl border border-edge bg-panel/60 p-4 transition-colors hover:border-accentSoft/60" style={{ transitionDelay: '160ms' }}>
        <Moon size={15} className="text-accent" />
        <h3 className="mt-1.5 text-[13.5px] font-semibold">夜间队列</h3>
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">睡前排队，夜间窗口自动执行，早上带证据审批。</p>
        <div className="mt-3 flex items-center gap-1">
          {[0, 1, 2, 3, 4].map((i) => (
            <span
              key={i}
              className="h-1.5 flex-1 rounded-full bg-accent/40"
              style={{ animation: `nova-pulse 2.4s ease-out ${i * 0.35}s infinite` }}
            />
          ))}
        </div>
        <p className="mt-2 font-mono text-[9.5px] text-dim/60">00:00 → 08:00 自动推进</p>
      </div>

      {/* 本地执行器（宽格） */}
      <div className="reveal col-span-2 overflow-hidden rounded-2xl border border-edge bg-panel/60 p-4 transition-colors hover:border-accentSoft/60" style={{ transitionDelay: '120ms' }}>
        <TerminalSquare size={15} className="text-accent" />
        <h3 className="mt-1.5 text-[13.5px] font-semibold">本地执行器</h3>
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">
          挂上 nova agent，Agent 的手就能伸进你的真实电脑：跑构建、写文件、查环境——每条命令由你确认。
        </p>
        <LocalBridgeViz />
      </div>

      {/* 反思教训 */}
      <div className="reveal rounded-2xl border border-edge bg-panel/60 p-4 transition-colors hover:border-accentSoft/60">
        <BrainCircuit size={15} className="text-accent" />
        <h3 className="mt-1.5 text-[13.5px] font-semibold">反思教训</h3>
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">从失败与返工中提炼教训注入后续对话，同一个坑不踩第二次。</p>
        <p className="mt-3 font-mono text-[9.5px] text-dim/60">失败 → 教训 → 注入 → 避免 ✓</p>
      </div>

      {/* 技能系统 */}
      <div className="reveal rounded-2xl border border-edge bg-panel/60 p-4 transition-colors hover:border-accentSoft/60">
        <Wand2 size={15} className="text-accent" />
        <h3 className="mt-1.5 text-[13.5px] font-semibold">技能系统</h3>
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">团队手册写成 SKILL.md，Nova 在对的时机自动想起。</p>
        <p className="mt-3 font-mono text-[9.5px] text-dim/60">SKILL.md → 触发 → 注入</p>
      </div>
    </div>
  )
}

function RedGreenViz() {
  const { ref, inView } = useInView<HTMLDivElement>()
  const steps = [
    { label: '失败测试 · 红', tone: 'err' },
    { label: '最小补丁', tone: 'dim' },
    { label: '全量通过 · 绿', tone: 'ok' },
    { label: '等待批准', tone: 'dim' },
  ]
  return (
    <div ref={ref} className="mt-4 space-y-1.5">
      {steps.map((step, index) => (
        <div
          key={step.label}
          className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 font-mono text-[10.5px] transition-all duration-700 ${
            inView ? 'translate-x-0 opacity-100' : '-translate-x-3 opacity-25'
          } ${
            step.tone === 'err' ? 'border-err/40 bg-err/10 text-err'
              : step.tone === 'ok' ? 'border-ok/40 bg-ok/10 text-ok'
                : 'border-edge bg-base/50 text-dim'
          }`}
          style={{ transitionDelay: `${index * 320}ms` }}
        >
          <span className="tabular-nums text-dim/50">0{index + 1}</span>
          {step.label}
          {index === 0 && <span className="ml-auto">exit 1</span>}
          {index === 2 && <span className="ml-auto">exit 0</span>}
        </div>
      ))}
    </div>
  )
}

function LocalBridgeViz() {
  return (
    <div className="mt-4 flex items-center gap-3 font-mono text-[10px] text-dim">
      <span className="rounded-lg border border-edge bg-base/60 px-2.5 py-2">你的电脑</span>
      <span className="relative h-px flex-1 bg-gradient-to-r from-accent/60 via-accentSoft/60 to-accent/60">
        <span className="absolute -top-[3px] h-[7px] w-[7px] rounded-full bg-accent" style={{ animation: 'nova-sweep-x 2.6s ease-in-out infinite' }} />
      </span>
      <span className="rounded-lg border border-accentSoft/50 bg-accentSoft/15 px-2.5 py-2 text-accent">Nova 服务器</span>
      <style>{`@keyframes nova-sweep-x { 0% { left: 0 } 50% { left: calc(100% - 7px) } 100% { left: 0 } }`}</style>
    </div>
  )
}

/* ================= 关键词跑马灯 ================= */

const MARQUEE = [
  '引用核验', 'Docker 沙箱实测', '红绿验证门', '夜间队列', '反思教训', '本地执行器',
  '项目大脑', '从 0 建项目', '多用户隔离', '自带模型 Key', 'SKILL.md 技能', 'Git 交付',
]

function Marquee() {
  const items = [...MARQUEE, ...MARQUEE]
  return (
    <div className="relative overflow-hidden border-y border-edge/60 py-3" aria-hidden>
      <div className="flex w-max gap-8" style={{ animation: 'nova-marquee 36s linear infinite' }}>
        {items.map((item, index) => (
          <span key={`${item}-${index}`} className="flex items-center gap-2 whitespace-nowrap text-[11.5px] text-dim/60">
            <Sparkles size={10} className="text-accent/50" /> {item}
          </span>
        ))}
      </div>
      <style>{`@keyframes nova-marquee { from { transform: translateX(0) } to { transform: translateX(-50%) } }`}</style>
    </div>
  )
}

/* ================= 认证弹窗（含邮箱验证码） ================= */

function AuthModal({ initialMode, onClose }: { initialMode: Mode; onClose: () => void }) {
  const { login, register, loadConfig, config } = useAuth()
  const [mode, setMode] = useState<Mode>(initialMode)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [email, setEmail] = useState('')
  const [emailCode, setEmailCode] = useState('')
  const [codeCountdown, setCodeCountdown] = useState(0)
  const [resetByEmail, setResetByEmail] = useState(true)
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  useEffect(() => {
    if (!codeCountdown) return
    const timer = setInterval(() => setCodeCountdown((value) => value - 1), 1000)
    return () => clearInterval(timer)
  }, [codeCountdown])

  const registrationOpen = config?.registration_mode !== 'closed'
  const emailVerification = config?.email_verification === true

  const sendCode = async () => {
    if (!email.trim() || sending || codeCountdown > 0) return
    setSending(true)
    setError(null)
    try {
      await api.emailCode(email.trim(), mode === 'register' ? 'register' : 'reset')
      setCodeCountdown(60)
      setNotice('验证码已发送，请查收邮箱（注意垃圾箱）')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '发送失败')
    } finally {
      setSending(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (mode === 'login') {
        await login(username.trim(), password)
        onClose()
      } else if (mode === 'register') {
        if (password !== confirmPassword) throw new ApiError(400, '两次输入的密码不一致')
        await register(username.trim(), password, {
          displayName: displayName.trim() || undefined,
          inviteCode: inviteCode.trim() || undefined,
          email: emailVerification ? email.trim() : undefined,
          emailCode: emailVerification ? emailCode.trim() : undefined,
        })
        onClose()
      } else if (emailVerification && resetByEmail) {
        await api.resetPasswordByEmail(username.trim(), email.trim(), emailCode.trim(), password)
        setNotice('密码已重置，请使用新密码登录')
        setMode('login')
        setPassword('')
        setEmailCode('')
      } else {
        await api.resetPassword(username.trim(), recoveryCode.trim(), password)
        setNotice('密码已重置，请使用新密码登录')
        setMode('login')
        setPassword('')
        setRecoveryCode('')
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="anim-pop relative w-full max-w-md rounded-2xl border border-edge bg-panel p-6 shadow-2xl">
        <button onClick={onClose} className="absolute right-4 top-4 text-dim hover:text-ink" aria-label="关闭">
          <X size={16} />
        </button>

        <div className="mb-4 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accentSoft/60">
            <Bot size={18} className="text-accent" />
          </div>
          <div>
            <h1 className="text-[16px] font-semibold">Nova Agent</h1>
            <p className="text-[11.5px] text-dim">可验证的工程 Agent</p>
          </div>
        </div>

        <div className="mb-4 flex rounded-lg border border-edge bg-base/40 p-0.5">
          {(['login', 'register', 'reset'] as Mode[]).map((key) => (
            <button
              key={key}
              onClick={() => { setMode(key); setError(null); setNotice(null) }}
              className={clsx('flex-1 rounded-md px-2 py-1.5 text-[12px] transition-colors',
                mode === key ? 'bg-accentSoft/45 text-ink' : 'text-dim hover:text-ink',
                (key === 'register' && !registrationOpen || key === 'reset') && 'hidden')}
            >
              {key === 'login' ? '登录' : key === 'register' ? '注册' : '找回密码'}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="space-y-3">
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="用户名" autoComplete="username" className={inputClass} />

          {mode === 'register' && (
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="显示名（可选）" className={inputClass} />
          )}

          {mode === 'reset' && !resetByEmail && (
            <input value={recoveryCode} onChange={(e) => setRecoveryCode(e.target.value)} placeholder="注册时保存的恢复码" className={inputClass} />
          )}

          {(emailVerification && (mode === 'register' || (mode === 'reset' && resetByEmail))) && (
            <>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                type="email"
                placeholder="邮箱地址"
                autoComplete="email"
                className={inputClass}
              />
              <div className="flex gap-2">
                <input
                  value={emailCode}
                  onChange={(e) => setEmailCode(e.target.value.replace(/[^0-9]/g, ''))}
                  placeholder="邮箱验证码"
                  inputMode="numeric"
                  maxLength={6}
                  className={`${inputClass} flex-1`}
                />
                <button
                  type="button"
                  onClick={() => void sendCode()}
                  disabled={sending || codeCountdown > 0 || !email.trim()}
                  className="shrink-0 rounded-lg border border-accentSoft/60 bg-accentSoft/15 px-3 text-[11.5px] text-accent transition-colors hover:bg-accentSoft/30 disabled:opacity-40"
                >
                  {sending ? <Loader2 size={12} className="animate-spin" /> : codeCountdown > 0 ? `${codeCountdown}s` : '发送验证码'}
                </button>
              </div>
            </>
          )}

          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder={mode === 'reset' ? '新密码' : '密码'}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            className={inputClass}
          />

          {mode === 'register' && (
            <input
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              type="password"
              placeholder="再次输入密码"
              autoComplete="new-password"
              className={inputClass}
            />
          )}

          {mode === 'register' && config?.invite_required && (
            <input value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} placeholder="邀请码（NOVA-XXXX-XXXX-XXXX）" className={inputClass} />
          )}

          {mode === 'register' && (
            <p className="text-[10.5px] leading-relaxed text-dim/70">
              密码至少 {config?.min_password_length ?? 8} 位。注册后会生成一次性恢复码，请妥善保存。
            </p>
          )}

          {error && <p className="text-[12px] text-err">{error}</p>}
          {notice && <p className="text-[12px] text-ok">{notice}</p>}

          <button
            type="submit"
            disabled={busy || !username || !password || (mode === 'register' && !confirmPassword)}
            className="nova-sweep flex w-full items-center justify-center gap-1.5 rounded-xl bg-accent px-3 py-2.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {busy ? <Spinner /> : mode === 'login' ? <KeyRound size={13} /> : <UserPlus size={13} />}
            {mode === 'login' ? '登录' : mode === 'register' ? '创建账号' : '重置密码'}
          </button>
        </form>

        <div className="mt-3 flex items-center justify-between text-[11px] text-dim">
          {mode === 'reset' && emailVerification && (
            <button
              onClick={() => { setResetByEmail((v) => !v); setError(null); setNotice(null) }}
              className="hover:text-ink"
            >
              {resetByEmail ? '改用恢复码找回' : '改用邮箱验证码找回'}
            </button>
          )}
          {mode === 'login' && <span>登录即同意以当前部署的配额使用</span>}
          {mode !== 'login' && mode !== 'reset' && <span />}
        </div>

        <p className="mt-3 text-center text-[10.5px] leading-relaxed text-dim/50">
          {registrationOpen
            ? '注册即创建独立工作区；项目、会话与文件仅自己可见。'
            : '当前部署未开放自助注册，请联系管理员开通账号。'}
        </p>
      </div>
    </div>
  )
}

/* ================= 页面 ================= */

export function LoginView() {
  const { guest, loadConfig, config } = useAuth()
  const [authOpen, setAuthOpen] = useState(false)
  const [authMode, setAuthMode] = useState<Mode>('login')
  const [guestBusy, setGuestBusy] = useState(false)
  const [guestError, setGuestError] = useState<string | null>(null)

  useRevealAll()

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  const openAuth = (mode: Mode) => {
    setAuthMode(mode)
    setAuthOpen(true)
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

  return (
    <div className="relative min-h-screen">
      <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute inset-0 nova-grid-bg" />
        <div className="nova-drift absolute left-1/2 top-[-280px] h-[560px] w-[820px] -translate-x-1/2 rounded-full bg-accent/12 blur-[140px]" />
        <div className="nova-float absolute bottom-[-240px] right-[-160px] h-[440px] w-[600px] rounded-full bg-accentSoft/8 blur-[130px]" />
      </div>

      {authOpen && <AuthModal initialMode={authMode} onClose={() => setAuthOpen(false)} />}

      <div className="relative mx-auto max-w-6xl px-5 lg:px-8">
        {/* 顶栏 */}
        <header className="sticky top-0 z-40 -mx-5 flex items-center gap-3 border-b border-edge/40 bg-base/80 px-5 py-3 backdrop-blur lg:-mx-8 lg:px-8">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accentSoft/60">
            <Bot size={16} className="text-accent" />
          </div>
          <span className="text-[13.5px] font-semibold">Nova Agent</span>
          <nav className="ml-6 hidden items-center gap-5 text-[12px] text-dim md:flex">
            <a href="#why" className="transition-colors hover:text-ink">能力矩阵</a>
            <a href="#how" className="transition-colors hover:text-ink">上手方式</a>
            <a href="#desktop" className="transition-colors hover:text-ink">桌面客户端</a>
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => openAuth('login')}
              className="rounded-lg border border-edge/80 px-3 py-1.5 text-[12px] text-dim transition-colors hover:border-accentSoft hover:text-ink"
            >
              登录
            </button>
            <button
              onClick={() => openAuth('register')}
              className="rounded-lg bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition-opacity hover:opacity-90"
            >
              免费注册
            </button>
          </div>
        </header>

        {/* Hero */}
        <section className="pt-16 text-center sm:pt-24">
          <div className="anim-rise inline-flex items-center gap-1.5 rounded-full border border-accentSoft/50 bg-accentSoft/15 px-3 py-1 text-[11px] text-accent">
            <ShieldCheck size={12} /> 自托管 · 沙箱实测 · 支持任意 OpenAI 兼容模型
          </div>
          <h1 className="anim-rise mx-auto mt-6 max-w-3xl text-[34px] font-bold leading-[1.18] tracking-tight sm:text-[52px]" style={{ animationDelay: '80ms' }}>
            不止生成代码，
            <br />
            <span className="bg-gradient-to-r from-accent via-accentSoft to-accent bg-clip-text text-transparent">每个结论都带着证据</span>
          </h1>
          <p className="anim-rise mx-auto mt-5 max-w-2xl text-[14px] leading-relaxed text-dim" style={{ animationDelay: '160ms' }}>
            Nova 读懂你的代码仓库，回答附上可核验的「文件: 行号」引用；
            改动先在强隔离沙箱里真实跑过测试才交给你批准。不靠模型自评，靠退出码。
          </p>
          <div className="anim-rise mt-8 flex flex-wrap items-center justify-center gap-3" style={{ animationDelay: '240ms' }}>
            {config?.guest_enabled !== false && (
              <button
                onClick={() => void startGuest()}
                disabled={guestBusy}
                className="nova-sweep flex items-center gap-2 rounded-xl bg-accent px-5 py-3 text-[13.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
              >
                {guestBusy ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
                一键游客体验
              </button>
            )}
            <button
              onClick={() => openAuth('register')}
              className="flex items-center gap-1.5 rounded-xl border border-edge/80 bg-panel/70 px-5 py-3 text-[13.5px] font-medium text-ink transition-colors hover:border-accentSoft"
            >
              注册账号 <ChevronRight size={14} />
            </button>
          </div>
          {guestError && <p className="mt-3 text-[12px] text-err">{guestError}</p>}
          <p className="mt-3 text-[10.5px] text-dim/50">游客无需注册，即时获得独立体验空间</p>

          <div className="anim-rise" style={{ animationDelay: '320ms' }}>
            <TerminalHero />
          </div>
        </section>

        {/* 关键词跑马灯 */}
        <div className="mt-16">
          <Marquee />
        </div>

        {/* Bento 能力矩阵 */}
        <section id="why" className="mt-20 scroll-mt-20">
          <div className="reveal mx-auto max-w-2xl text-center">
            <h2 className="text-[24px] font-bold tracking-tight">为什么是 Nova</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-dim">
              市面上的编程 Agent 大多止步于「生成代码 + 祈祷它能跑」。
              Nova 把每一步都变成可验证的确定性环节——下面每一格，都是一个可演示的真实能力。
            </p>
          </div>
          <div className="mt-8">
            <BentoGrid />
          </div>
        </section>

        {/* 上手方式 */}
        <section id="how" className="mt-24 scroll-mt-20">
          <div className="reveal mx-auto max-w-2xl text-center">
            <h2 className="text-[24px] font-bold tracking-tight">三步上手</h2>
          </div>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {[
              { title: '立即体验', desc: '点「一键游客体验」获得独立空间，无需注册（限 3 次对话）。' },
              { title: '导入你的项目', desc: '整个文件夹拖进来或填 Git 地址，索引完成后即可问答、修 Bug、建项目。' },
              { title: '长期使用', desc: '注册并配置自己的模型 Key，或下载桌面客户端从桌面直达。' },
            ].map((step, index) => (
              <div key={step.title} className="reveal rounded-2xl border border-edge bg-panel/50 p-5" style={{ transitionDelay: `${index * 100}ms` }}>
                <span className="font-mono text-[12px] text-accent">0{index + 1}</span>
                <h3 className="mt-1.5 text-[14px] font-semibold">{step.title}</h3>
                <p className="mt-1.5 text-[12px] leading-relaxed text-dim">{step.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 桌面客户端 */}
        <section id="desktop" className="mt-24 scroll-mt-20">
          <div className="reveal relative overflow-hidden rounded-3xl border border-accentSoft/40 bg-gradient-to-br from-accentSoft/15 via-panel to-panel p-8 sm:p-10">
            <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-accent/15 blur-3xl" aria-hidden />
            <div className="relative flex flex-col items-start gap-6 sm:flex-row sm:items-center">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-accentSoft/40">
                <MonitorDown size={26} className="text-accent" />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-[20px] font-bold">装到你的桌面上</h2>
                <p className="mt-2 max-w-xl text-[13px] leading-relaxed text-dim">
                  Windows / macOS / Linux 原生安装包，数据全部留在你的服务器。
                  配合 nova bridge 把本机项目目录接入 Nova，配合 nova agent 让 Nova 直接在你的电脑上执行命令、生成文件——每一步都经你确认。
                </p>
              </div>
              <a
                href="/downloads/"
                target="_blank"
                rel="noreferrer"
                className="nova-sweep flex shrink-0 items-center gap-2 rounded-xl bg-accent px-5 py-3 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
              >
                <Download size={15} /> 获取安装包
              </a>
            </div>
          </div>
        </section>

        <footer className="mt-24 border-t border-edge/60 py-8 text-center text-[10.5px] leading-relaxed text-dim/50">
          游客空间到期自动清理，注册可保留数据 · 支持百炼 / DeepSeek / LongCat / OpenAI 兼容端点
          <br />Nova Agent · 可自托管的工程 Agent · {new Date().getFullYear()}
        </footer>
      </div>
    </div>
  )
}
