import { Ban, CheckCircle2, Plus, RefreshCw, Trash2, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { User } from '../lib/types'
import { useAuth } from '../stores/auth'
import { Badge, Button, Modal, Spinner } from './common'

const inputClass =
  'w-full rounded-lg border border-edge bg-base/60 px-3 py-2 text-[12.5px] text-ink outline-none transition-colors focus:border-accent/60'

export function AdminUsersPanel() {
  const current = useAuth((state) => state.user)
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<number | 'create' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newDisplayName, setNewDisplayName] = useState('')
  const [newRole, setNewRole] = useState<'admin' | 'demo'>('demo')

  const [resetTarget, setResetTarget] = useState<User | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      setUsers(await api.admin.users())
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载用户失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const run = async (id: number | 'create', action: () => Promise<unknown>, message: string) => {
    setBusy(id)
    setError(null)
    setNotice(null)
    try {
      await action()
      setNotice(message)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy(null)
    }
  }

  const createUser = () => run('create', async () => {
    await api.admin.createUser(
      newUsername.trim(),
      newPassword,
      newDisplayName.trim() || undefined,
      newRole,
    )
    setNewUsername('')
    setNewPassword('')
    setNewDisplayName('')
    setNewRole('demo')
  }, '账号已创建')

  const toggleStatus = (user: User) => run(
    user.id,
    () => api.admin.updateUser(user.id, { status: user.status === 'disabled' ? 'active' : 'disabled' }),
    user.status === 'disabled' ? '账号已启用' : '账号已禁用，旧登录立即失效',
  )

  const resetUserPassword = () => {
    if (!resetTarget) return
    const target = resetTarget
    void run(target.id, async () => {
      await api.admin.resetPassword(target.id, resetPassword)
      setResetTarget(null)
      setResetPassword('')
    }, `已重置 ${target.username} 的密码`)
  }

  const deleteUser = () => {
    if (!deleteTarget) return
    const target = deleteTarget
    void run(target.id, async () => {
      await api.admin.removeUser(target.id)
      setDeleteTarget(null)
    }, `已删除 ${target.username}`)
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <Users size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">用户管理</h3>
          <span className="text-[10.5px] text-dim">共 {users.length} 个账号</span>
          <Button size="sm" className="ml-auto" onClick={() => void load()} disabled={loading}>
            {loading ? <Spinner /> : <RefreshCw size={12} />} 刷新
          </Button>
        </div>
        {error && <p className="mb-2 text-[11.5px] text-err">{error}</p>}
        {notice && <p className="mb-2 text-[11.5px] text-ok">{notice}</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-[11.5px]">
            <thead>
              <tr className="border-b border-edge text-left text-dim">
                <th className="py-1.5 pr-2 font-medium">用户</th>
                <th className="px-2 py-1.5 font-medium">角色</th>
                <th className="px-2 py-1.5 font-medium">状态</th>
                <th className="px-2 py-1.5 font-medium">创建时间</th>
                <th className="px-2 py-1.5 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((item) => (
                <tr key={item.id} className="border-b border-edge/50">
                  <td className="py-2 pr-2">
                    <p className="text-ink">{item.display_name || item.username}</p>
                    <p className="font-mono text-[10px] text-dim">@{item.username}</p>
                  </td>
                  <td className="px-2 py-2">
                    <Badge tone={item.role === 'admin' ? 'accent' : 'dim'}>{item.role}</Badge>
                    {item.is_guest && <Badge tone="warn">游客</Badge>}
                  </td>
                  <td className="px-2 py-2">
                    <Badge tone={item.status === 'disabled' ? 'err' : 'ok'}>
                      {item.status === 'disabled' ? '已禁用' : '正常'}
                    </Badge>
                  </td>
                  <td className="px-2 py-2 text-dim">
                    {item.created_at ? new Date(item.created_at).toLocaleDateString() : '—'}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex justify-end gap-1">
                      <button
                        onClick={() => void toggleStatus(item)}
                        disabled={busy === item.id || item.id === current?.id}
                        className="rounded p-1 text-dim hover:bg-raised hover:text-ink disabled:opacity-30"
                        title={item.status === 'disabled' ? '启用账号' : '禁用账号'}
                      >
                        {item.status === 'disabled' ? <CheckCircle2 size={13} /> : <Ban size={13} />}
                      </button>
                      <button
                        onClick={() => setResetTarget(item)}
                        disabled={busy === item.id}
                        className="rounded px-1.5 py-1 text-[10.5px] text-dim hover:bg-raised hover:text-ink disabled:opacity-30"
                      >
                        重置密码
                      </button>
                      <button
                        onClick={() => setDeleteTarget(item)}
                        disabled={busy === item.id || item.id === current?.id}
                        className="rounded p-1 text-dim hover:bg-err/10 hover:text-err disabled:opacity-30"
                        title="删除账号"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <Plus size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">创建账号</h3>
          <span className="text-[10.5px] text-dim">管理员直接开通，不受注册开关限制</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <input
            value={newUsername}
            onChange={(event) => setNewUsername(event.target.value)}
            placeholder="用户名（3-32 位字母/数字/下划线）"
            className={inputClass}
          />
          <input
            value={newDisplayName}
            onChange={(event) => setNewDisplayName(event.target.value)}
            placeholder="显示名（可选）"
            className={inputClass}
          />
          <input
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            placeholder="初始密码（至少 8 位）"
            className={inputClass}
          />
          <select
            value={newRole}
            onChange={(event) => setNewRole(event.target.value as 'admin' | 'demo')}
            className={inputClass}
          >
            <option value="demo">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </div>
        <div className="mt-3 flex justify-end">
          <Button
            size="sm"
            variant="primary"
            onClick={() => void createUser()}
            disabled={busy === 'create' || !newUsername.trim() || newPassword.length < 8}
          >
            {busy === 'create' ? <Spinner /> : <Plus size={12} />} 创建账号
          </Button>
        </div>
      </section>

      <Modal
        open={Boolean(resetTarget)}
        onClose={() => { setResetTarget(null); setResetPassword('') }}
        title={`重置密码：${resetTarget?.username ?? ''}`}
        width="max-w-sm"
      >
        <input
          type="password"
          value={resetPassword}
          onChange={(event) => setResetPassword(event.target.value)}
          placeholder="新密码（至少 8 位）"
          className={inputClass}
          autoFocus
        />
        <p className="mt-2 text-[10.5px] text-dim">重置后该用户所有旧登录状态立即失效。</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" onClick={() => { setResetTarget(null); setResetPassword('') }}>取消</Button>
          <Button size="sm" variant="primary" onClick={resetUserPassword} disabled={resetPassword.length < 8}>
            确认重置
          </Button>
        </div>
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title={`删除账号：${deleteTarget?.username ?? ''}`}
        width="max-w-sm"
      >
        <p className="text-[12px] leading-relaxed text-dim">
          将删除该账号的会话、项目、文件与记忆，此操作无法撤销。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" onClick={() => setDeleteTarget(null)}>取消</Button>
          <Button size="sm" variant="danger" onClick={deleteUser}>确认删除</Button>
        </div>
      </Modal>
    </div>
  )
}
