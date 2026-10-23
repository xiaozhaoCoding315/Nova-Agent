import { Bot, KeyRound, Sparkles, UserPlus } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../stores/auth'
import { Button, Spinner } from '../components/common'

type Mode = 'login' | 'register' | 'reset'

const inputClass =
  'w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none placeholder:text-dim/60 focus:border-accentSoft'

export function LoginView() {
  const { login, register, guest, loadConfig, config } = useAuth()
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    void loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const registrationOpen = config?.registration_mode !== 'closed'
  const guestEnabled = config?.guest_enabled !== false

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (mode === 'login') {
        await login(username.trim(), password)
      } else if (mode === 'register') {
        if (password !== confirmPassword) throw new ApiError(400, '两次输入的密码不一致')
        await register(username.trim(), password, displayName.trim() || undefined, inviteCode.trim() || undefined)
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

  const startGuest = async () => {
    setBusy(true)
    setError(null)
    try {
      await guest()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '游客体验启动失败')
    } finally {
      setBusy(false)
    }
  }

  const switchMode = (next: Mode) => {
    setMode(next)
    setError(null)
    setNotice(null)
    setPassword('')
    setConfirmPassword('')
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-edge bg-panel p-6 shadow-2xl">
        <div className="mb-5 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accentSoft/60">
            <Bot size={18} className="text-accent" />
          </div>
          <div>
            <h1 className="text-[16px] font-semibold">Nova Agent</h1>
            <p className="text-[11.5px] text-dim">可验证的工程 Agent</p>
          </div>
        </div>

        <div className="mb-4 flex rounded-lg border border-edge bg-base/40 p-0.5">
          <button
            onClick={() => switchMode('login')}
            className={`flex-1 rounded-md px-3 py-1.5 text-[12px] ${mode === 'login' ? 'bg-accentSoft/45 text-ink' : 'text-dim hover:text-ink'}`}
          >
            登录
          </button>
          {registrationOpen && (
            <button
              onClick={() => switchMode('register')}
              className={`flex-1 rounded-md px-3 py-1.5 text-[12px] ${mode === 'register' ? 'bg-accentSoft/45 text-ink' : 'text-dim hover:text-ink'}`}
            >
              注册
            </button>
          )}
        </div>

        <form onSubmit={submit} className="space-y-3">
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoFocus
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

          {mode === 'reset' && (
            <input
              value={recoveryCode}
              onChange={(e) => setRecoveryCode(e.target.value)}
              placeholder="注册时保存的恢复码"
              className={inputClass}
            />
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
              placeholder="邀请码"
              className={inputClass}
            />
          )}

          {mode === 'register' && (
            <p className="text-[10.5px] leading-relaxed text-dim/70">
              密码至少 {config?.min_password_length ?? 8} 位。注册后会生成一次性恢复码，请妥善保存。
            </p>
          )}

          {error && <p className="text-[12px] text-err">{error}</p>}
          {notice && <p className="text-[12px] text-ok">{notice}</p>}

          <Button
            type="submit"
            variant="primary"
            className="w-full"
            disabled={busy || !username || !password || (mode === 'register' && !confirmPassword)}
          >
            {busy
              ? <Spinner />
              : mode === 'login'
                ? <KeyRound size={13} />
                : <UserPlus size={13} />}
            {mode === 'login' ? '登录' : mode === 'register' ? '创建账号' : '重置密码'}
          </Button>
        </form>

        <div className="mt-3 flex items-center justify-between text-[11px]">
          <button onClick={() => switchMode('reset')} className="text-dim hover:text-ink">
            忘记密码？
          </button>
          {mode !== 'login' && (
            <button onClick={() => switchMode('login')} className="text-dim hover:text-ink">
              已有账号，去登录
            </button>
          )}
        </div>

        {guestEnabled && (
          <div className="mt-5 border-t border-edge/70 pt-4">
            <button
              onClick={() => void startGuest()}
              disabled={busy}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-accentSoft/60 bg-accentSoft/20 px-3 py-2.5 text-[12.5px] text-ink transition-colors hover:bg-accentSoft/35 disabled:opacity-50"
            >
              {busy ? <Spinner /> : <Sparkles size={14} className="text-accent" />}
              一键体验（24 小时独立游客空间）
            </button>
            <p className="mt-2 text-center text-[10.5px] leading-relaxed text-dim/60">
              游客有独立会话与文件，到期自动清理；额度有限，可随时注册保留数据。
            </p>
          </div>
        )}

        <p className="mt-4 text-center text-[10.5px] leading-relaxed text-dim/50">
          {registrationOpen ? '注册即创建独立工作区；项目、会话与文件仅自己可见。' : '当前部署未开放自助注册，请联系管理员开通账号。'}
        </p>
      </div>
    </div>
  )
}
