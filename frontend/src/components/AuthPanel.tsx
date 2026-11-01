import clsx from 'clsx'
import { KeyRound, Loader2, UserPlus } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../stores/auth'
import { Spinner } from './common'

export type AuthMode = 'login' | 'register' | 'reset'

const inputClass =
  'w-full rounded-md border border-edge bg-raised px-3 py-2 text-base text-ink outline-none transition-colors placeholder:text-faint focus:border-accent/50'

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
      setError(err instanceof ApiError ? err.message : '操作失败，请重试')
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
        {(['login', 'register', 'reset'] as AuthMode[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={mode === key}
            onClick={() => { setMode(key); setError(null); setNotice(null) }}
            className={clsx(
              'flex-1 rounded-sm px-2 py-1.5 text-sm transition-colors duration-150',
              mode === key ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:text-ink',
              // 找回密码需要可达；只有关闭注册时隐藏注册页签。
              key === 'register' && !registrationOpen && 'hidden',
            )}
          >
            {key === 'login' ? '登录' : key === 'register' ? '注册' : '找回密码'}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="space-y-3">
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

        {mode === 'reset' && !resetByEmail && (
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
                className="shrink-0 rounded-md border border-accent/40 bg-accentSoft/40 px-3 text-xs text-accent transition-colors duration-150 hover:bg-accentSoft/60 disabled:cursor-not-allowed disabled:opacity-40"
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
