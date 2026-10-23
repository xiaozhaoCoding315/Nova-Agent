import { Bot, KeyRound } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../lib/api'
import { useAuth } from '../stores/auth'
import { Button, Spinner } from '../components/common'

export function LoginView() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const login = useAuth((s) => s.login)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username.trim(), password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '登录失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-2xl border border-edge bg-panel p-6 shadow-2xl">
        <div className="mb-6 flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accentSoft/60">
            <Bot size={18} className="text-accent" />
          </div>
          <div>
            <h1 className="text-[16px] font-semibold">Nova Agent</h1>
            <p className="text-[12px] text-dim">开发者 AI 工作台</p>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-3">
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoFocus
            autoComplete="username"
            className="w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13.5px] outline-none placeholder:text-dim/60 focus:border-accentSoft"
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder="密码"
            autoComplete="current-password"
            className="w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13.5px] outline-none placeholder:text-dim/60 focus:border-accentSoft"
          />
          {error && <p className="text-[12.5px] text-err">{error}</p>}
          <Button type="submit" variant="primary" className="w-full" disabled={busy || !username || !password}>
            {busy ? <Spinner /> : <KeyRound size={13} />} 登录
          </Button>
        </form>

        <p className="mt-4 text-center text-[11.5px] leading-relaxed text-dim">
          演示/答辩访问请使用管理员提供的账号；账号在服务端 .env 中配置。
        </p>
      </div>
    </div>
  )
}