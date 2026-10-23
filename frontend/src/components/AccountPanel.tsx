import { KeyRound, LogOut, ShieldCheck, UserRound } from 'lucide-react'
import { useState } from 'react'
import { ApiError } from '../lib/api'
import { useAuth } from '../stores/auth'
import { Badge, Button, Spinner } from './common'

const inputClass =
  'w-full rounded-lg border border-edge bg-base/60 px-3 py-2 text-[12.5px] text-ink outline-none transition-colors focus:border-accent/60'

export function AccountPanel() {
  const { user, updateProfile, changePassword, logout } = useAuth()
  const [displayName, setDisplayName] = useState(user?.display_name || user?.username || '')
  const [profileBusy, setProfileBusy] = useState(false)
  const [profileMsg, setProfileMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [passwordBusy, setPasswordBusy] = useState(false)
  const [passwordMsg, setPasswordMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const saveProfile = async () => {
    setProfileBusy(true)
    setProfileMsg(null)
    try {
      await updateProfile(displayName.trim())
      setProfileMsg({ ok: true, text: '显示名已更新' })
    } catch (err) {
      setProfileMsg({ ok: false, text: err instanceof ApiError ? err.message : '保存失败' })
    } finally {
      setProfileBusy(false)
    }
  }

  const savePassword = async () => {
    if (newPassword !== confirmPassword) {
      setPasswordMsg({ ok: false, text: '两次输入的新密码不一致' })
      return
    }
    setPasswordBusy(true)
    setPasswordMsg(null)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setPasswordMsg({ ok: true, text: '密码已更新，其他设备的登录状态已失效' })
    } catch (err) {
      setPasswordMsg({ ok: false, text: err instanceof ApiError ? err.message : '修改失败' })
    } finally {
      setPasswordBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <UserRound size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">个人资料</h3>
          {user?.is_guest && <Badge tone="warn">游客</Badge>}
          <Badge tone={user?.role === 'admin' ? 'accent' : 'dim'}>{user?.role}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-accentSoft/50 text-[15px] font-semibold text-accent">
            {(user?.display_name || user?.username || '?').slice(0, 1).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px]">{user?.username}</p>
            <p className="text-[11px] text-dim">
              {user?.is_guest
                ? `游客空间将在 ${user.expires_at ? new Date(user.expires_at).toLocaleString() : '到期后'} 自动清理`
                : '账号数据仅自己可见'}
            </p>
          </div>
        </div>
        <div className="mt-3 flex items-end gap-2">
          <label className="min-w-0 flex-1">
            <span className="mb-1 block text-[11px] text-dim">显示名</span>
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              maxLength={80}
              className={inputClass}
            />
          </label>
          <Button size="sm" onClick={() => void saveProfile()} disabled={profileBusy || !displayName.trim()}>
            {profileBusy ? <Spinner /> : null} 保存
          </Button>
        </div>
        {profileMsg && (
          <p className={`mt-1.5 text-[11px] ${profileMsg.ok ? 'text-ok' : 'text-err'}`}>{profileMsg.text}</p>
        )}
      </section>

      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <KeyRound size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">修改密码</h3>
        </div>
        <div className="space-y-2">
          <input
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            placeholder="当前密码"
            autoComplete="current-password"
            className={inputClass}
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <input
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder="新密码（至少 8 位）"
              autoComplete="new-password"
              className={inputClass}
            />
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="再次输入新密码"
              autoComplete="new-password"
              className={inputClass}
            />
          </div>
        </div>
        {passwordMsg && (
          <p className={`mt-1.5 text-[11px] ${passwordMsg.ok ? 'text-ok' : 'text-err'}`}>{passwordMsg.text}</p>
        )}
        <div className="mt-3 flex items-center justify-between">
          <p className="flex items-center gap-1 text-[10.5px] text-dim/70">
            <ShieldCheck size={11} /> 修改后旧 token 立即失效
          </p>
          <Button
            size="sm"
            onClick={() => void savePassword()}
            disabled={passwordBusy || !currentPassword || !newPassword || !confirmPassword}
          >
            {passwordBusy ? <Spinner /> : null} 更新密码
          </Button>
        </div>
      </section>

      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="flex items-center gap-2">
          <h3 className="text-[13px] font-medium">会话</h3>
          <Button size="sm" variant="danger" className="ml-auto" onClick={() => void logout()}>
            <LogOut size={12} /> 退出登录
          </Button>
        </div>
      </section>
    </div>
  )
}
