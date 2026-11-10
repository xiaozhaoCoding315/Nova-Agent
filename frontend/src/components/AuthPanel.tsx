import clsx from 'clsx'
import { KeyRound, Loader2, UserPlus } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import { inputClass } from '../lib/ui'
import { useAuth } from '../stores/auth'
import { OtpInput } from './OtpInput'
import { Spinner } from './common'

export type AuthMode = 'login' | 'register' | 'reset'

const VISIBLE_MODES: AuthMode[] = ['login', 'register', 'reset']
const tabId = (mode: AuthMode) => `auth-tab-${mode}`
const panelId = 'auth-tab-panel'

/** 登录、注册与找回密码表单；从 LoginView 的 AuthModal 抽出，仅改变外观与布局。 */
export function AuthPanel({
  initialMode,
  onDone,
}: {
  initialMode: AuthMode
  onDone: () => void
}) {
  const { login, register, loadConfig, config } = useAuth()
  const [mode, setMode] = useState<AuthMode>(initialMode)
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  // 邀请链接形如 /?invite=NOVA-XXXX-XXXX-XXXX：管理员在设置里复制链接发给对方，
  // 打开注册页时邀请码已经填好，不用再手工抄一遍。
  const [inviteCode, setInviteCode] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get('invite')?.trim() ?? ''
    } catch {
      return ''
    }
  })
  const [recoveryCode, setRecoveryCode] = useState('')
  const [email, setEmail] = useState('')
  const [emailCode, setEmailCode] = useState('')
  const [codeCountdown, setCodeCountdown] = useState(0)
  const [resetByEmail, setResetByEmail] = useState(true)
  const [busy, setBusy] = useState(false)
  const [sending, setSending] = useState(false)
  /** 验证码提交失败：抖一次并标红，下一次输入即清除。 */
  const [codeInvalid, setCodeInvalid] = useState(false)
  /** 失败计数：同一组错误值重复提交时也要重放抖动。 */
  const [shakeKey, setShakeKey] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  useEffect(() => {
    if (!codeCountdown) return
    const timer = setInterval(() => setCodeCountdown((value) => value - 1), 1000)
    return () => clearInterval(timer)
  }, [codeCountdown])

  const registrationOpen = config?.registration_mode !== 'closed'
  const emailVerification = config?.email_verification === true

  // 注册关闭时「注册」页签不存在；停在那一档会既没有选中项、也没有 Tab 停靠点。
  useEffect(() => {
    if (!registrationOpen && mode === 'register') setMode('login')
  }, [registrationOpen, mode])

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
        onDone()
      } else if (mode === 'register') {
        if (password !== confirmPassword) throw new ApiError(400, '两次输入的密码不一致')
        await register(username.trim(), password, {
          displayName: displayName.trim() || undefined,
          inviteCode: inviteCode.trim() || undefined,
          email: emailVerification ? email.trim() : undefined,
          emailCode: emailVerification ? emailCode.trim() : undefined,
        })
        onDone()
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
      const message = err instanceof ApiError ? err.message : '操作失败，请重试'
      setError(message)
      // 只在「验证码」这个词出现在错误里时才抖：密码错、用户名重复不该让验证码格抖动。
      if (emailCode && message.includes('验证码')) {
        setCodeInvalid(true)
        setShakeKey((value) => value + 1)
      }
    } finally {
      setBusy(false)
    }
  }

  const title = mode === 'login' ? '登录到工作区' : mode === 'register' ? '创建你的工作区' : '重置密码'

  return (
    <div className="rounded-lg border border-edge bg-panel p-5 shadow-pop sm:p-6">
      <div className="mb-4">
        <p className="font-mono text-2xs uppercase tracking-[0.16em] text-faint">认证</p>
        <h2 className="mt-1 text-lg font-semibold text-ink">{title}</h2>
      </div>

      <div role="tablist" aria-label="认证方式" className="mb-4 flex rounded-md border border-edge bg-base/40 p-0.5">
        {VISIBLE_MODES.map((key) => {
          // 注册关闭时该页签整个不渲染：留在 tablist 里会变成一个选不中的「注册」。
          if (key === 'register' && !registrationOpen) return null
          const selected = mode === key
          return (
            <button
              key={key}
              id={tabId(key)}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={panelId}
              // roving tabindex：整组只占一个 Tab 停靠点，组内用方向键切换。
              tabIndex={selected ? 0 : -1}
              onClick={() => { setMode(key); setError(null); setNotice(null) }}
              onKeyDown={(event) => {
                const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
                const list = VISIBLE_MODES.filter((item) => (
                  item !== 'register' || registrationOpen
                ))
                if (event.key === 'Home' || event.key === 'End') {
                  event.preventDefault()
                  const next = event.key === 'Home' ? list[0] : list[list.length - 1]
                  setMode(next)
                  document.getElementById(tabId(next))?.focus()
                  return
                }
                if (!step) return
                event.preventDefault()
                const index = list.indexOf(key)
                const next = list[(index + step + list.length) % list.length]
                setMode(next)
                document.getElementById(tabId(next))?.focus()
              }}
              className={clsx(
                'flex-1 rounded-sm px-2 py-1.5 text-sm transition-colors duration-150',
                selected ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:text-ink',
              )}
            >
              {key === 'login' ? '登录' : key === 'register' ? '注册' : '找回密码'}
            </button>
          )
        })}
      </div>

      <form
        id={panelId}
        role="tabpanel"
        aria-labelledby={tabId(mode)}
        onSubmit={submit}
        className="space-y-3"
      >
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="用户名"
          autoComplete="username"
          className={inputClass}
        />

        {mode === 'register' && (
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="显示名（可选）"
            className={inputClass}
          />
        )}

        {mode === 'reset' && !(emailVerification && resetByEmail) && (
          <input
            value={recoveryCode}
            onChange={(e) => setRecoveryCode(e.target.value)}
            placeholder="注册时保存的恢复码"
            className={inputClass}
          />
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
            <OtpInput
              value={emailCode}
              onChange={(next) => { setEmailCode(next); setCodeInvalid(false) }}
              invalid={codeInvalid}
              shakeKey={shakeKey}
              disabled={busy}
            />
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => void sendCode()}
                aria-label={sending ? '正在发送验证码' : undefined}
                disabled={sending || codeCountdown > 0 || !email.trim()}
                className="flex h-8 shrink-0 items-center rounded-md border border-accent/40 bg-accentSoft/40 px-3 text-xs text-accent transition-colors duration-150 hover:bg-accentSoft/60 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {sending ? <Loader2 size={12} className="animate-spin" /> : codeCountdown > 0 ? `${codeCountdown}s` : '发送验证码'}
              </button>
              <span className="text-2xs text-faint">
                {emailCode.length === 6 ? '已填满，可以提交' : `${emailCode.length} / 6 位`}
              </span>
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
          <input
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            placeholder="邀请码（NOVA-XXXX-XXXX-XXXX）"
            className={inputClass}
          />
        )}

        {mode === 'register' && (
          <p className="text-2xs leading-relaxed text-dim/70">
            密码至少 {config?.min_password_length ?? 8} 位。注册后会生成一次性恢复码，请妥善保存。
          </p>
        )}

        {error && <p className="text-sm text-err" role="alert">{error}</p>}
        {notice && <p className="text-sm text-ok">{notice}</p>}

        <button
          type="submit"
          disabled={busy || !username || !password || (mode === 'register' && !confirmPassword)}
          className="flex w-full items-center justify-center gap-1.5 rounded-md bg-accent px-3 py-2.5 text-base font-semibold text-graphite transition-colors duration-150 hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? <Spinner /> : mode === 'login' ? <KeyRound size={13} /> : <UserPlus size={13} />}
          {mode === 'login' ? '登录' : mode === 'register' ? '创建账号' : '重置密码'}
        </button>
      </form>

      <div className="mt-3 flex items-center justify-between text-xs text-dim">
        {mode === 'reset' && emailVerification && (
          <button
            type="button"
            onClick={() => { setResetByEmail((v) => !v); setError(null); setNotice(null) }}
            className="transition-colors hover:text-ink"
          >
            {resetByEmail ? '改用恢复码找回' : '改用邮箱验证码找回'}
          </button>
        )}
        {mode === 'login' && <span>登录即同意以当前部署的配额使用</span>}
        {mode !== 'login' && mode !== 'reset' && <span />}
      </div>

      <p className="mt-3 text-center text-2xs leading-relaxed text-faint">
        {registrationOpen
          ? '注册即创建独立工作区；项目、会话与文件仅自己可见。'
          : '当前部署未开放自助注册，请联系管理员开通账号。'}
      </p>
    </div>
  )
}
