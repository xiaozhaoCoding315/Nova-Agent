import { Ban, CheckCircle2, Coins, Copy, Plus, RefreshCw, SlidersHorizontal, Ticket, Trash2, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { AdminUser, InviteCode } from '../lib/types'
import { useAuth } from '../stores/auth'
import { Badge, Button, Modal, Spinner } from './common'

const inputClass =
  'w-full rounded-lg border border-edge bg-base/60 px-3 py-2 text-[12.5px] text-ink outline-none transition-colors focus:border-accent/60'

const QUOTA_FIELDS: { key: keyof AdminUser & string; label: string; hint: string }[] = [
  { key: 'quota_daily_tokens', label: '每日 token 上限', hint: '如 200000' },
  { key: 'quota_hourly_messages', label: '每小时消息数', hint: '如 30' },
  { key: 'quota_sandbox_daily', label: '每日沙箱执行', hint: '如 10' },
  { key: 'quota_job_hourly', label: '每小时后台任务', hint: '如 5' },
  { key: 'quota_storage_mb', label: '存储（MB）', hint: '如 500' },
]

function hasCustomQuota(user: AdminUser): boolean {
  return QUOTA_FIELDS.some(({ key }) => user[key] != null)
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function AdminUsersPanel() {
  const current = useAuth((state) => state.user)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [sources, setSources] = useState<{ source: string; model: string; calls: number; tokens: number }[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<number | 'create' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newDisplayName, setNewDisplayName] = useState('')
  const [newRole, setNewRole] = useState<'admin' | 'demo'>('demo')

  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null)
  const [quotaTarget, setQuotaTarget] = useState<AdminUser | null>(null)
  const [quotaForm, setQuotaForm] = useState<Record<string, string>>({})
  const [quotaError, setQuotaError] = useState<string | null>(null)

  const [invites, setInvites] = useState<InviteCode[]>([])
  const [inviteNote, setInviteNote] = useState('')
  const [inviteMaxUses, setInviteMaxUses] = useState('1')
  const [inviteExpiresDays, setInviteExpiresDays] = useState('30')
  const [inviteBusy, setInviteBusy] = useState(false)
  const [copiedCode, setCopiedCode] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [userList, sourceUsage, inviteList] = await Promise.all([
        api.admin.users(),
        api.admin.usageSources().catch(() => []),
        api.admin.invites.list().catch(() => [] as InviteCode[]),
      ])
      setUsers(userList)
      setSources(sourceUsage)
      setInvites(inviteList)
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

  const toggleStatus = (user: AdminUser) => run(
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

  const openQuota = (user: AdminUser) => {
    setQuotaTarget(user)
    setQuotaError(null)
    setQuotaForm(Object.fromEntries(
      QUOTA_FIELDS.map(({ key }) => [key, user[key] == null ? '' : String(user[key])]),
    ))
  }

  const copyCode = async (code: string) => {
    try {
      await navigator.clipboard.writeText(code)
      setCopiedCode(code)
      setTimeout(() => setCopiedCode(null), 1500)
    } catch {
      /* 剪贴板不可用时忽略，用户仍可手动选中复制 */
    }
  }

  const createInvite = async () => {
    setInviteBusy(true)
    setError(null)
    try {
      await api.admin.invites.create(
        inviteNote.trim(),
        Math.max(1, Number(inviteMaxUses) || 1),
        Math.max(0, Number(inviteExpiresDays) || 0),
      )
      setInviteNote('')
      setInviteMaxUses('1')
      setInviteExpiresDays('30')
      setInvites(await api.admin.invites.list())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '生成邀请码失败')
    } finally {
      setInviteBusy(false)
    }
  }

  const removeInvite = async (id: number) => {
    setError(null)
    try {
      await api.admin.invites.remove(id)
      setInvites(await api.admin.invites.list())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除邀请码失败')
    }
  }

  const saveQuota = () => {
    if (!quotaTarget) return
    const target = quotaTarget
    const patch: Record<string, number | null> = {}
    for (const { key } of QUOTA_FIELDS) {
      const raw = (quotaForm[key] ?? '').trim()
      if (raw === '') {
        patch[key] = null
        continue
      }
      const value = Number(raw)
      if (!Number.isInteger(value) || value < 0) {
        setQuotaError('限额需为非负整数（0 表示不限，留空表示跟随默认档）')
        return
      }
      patch[key] = value
    }
    void run(target.id, async () => {
      await api.admin.updateUser(target.id, patch)
      setQuotaTarget(null)
    }, `已更新 ${target.username} 的限额`)
  }

  return (
    <div className="space-y-4">
      {sources.length > 0 && (
        <section className="rounded-xl border border-edge bg-panel p-4">
          <div className="mb-2 flex items-center gap-2">
            <Coins size={14} className="text-accent" />
            <h3 className="text-[13px] font-medium">用量来源（近 7 天）</h3>
            <span className="text-[10.5px] text-dim">按调用来源与模型聚合，用于成本归因</span>
          </div>
          <table className="w-full border-collapse text-[11.5px]">
            <thead>
              <tr className="border-b border-edge text-left text-dim">
                <th className="py-1.5 pr-2 font-medium">来源</th>
                <th className="px-2 py-1.5 font-medium">模型</th>
                <th className="px-2 py-1.5 font-medium">次数</th>
                <th className="px-2 py-1.5 text-right font-medium">tokens</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((row) => (
                <tr key={`${row.source}:${row.model}`} className="border-b border-edge/50">
                  <td className="py-1.5 pr-2 font-mono text-[10.5px]">{row.source}</td>
                  <td className="px-2 py-1.5 font-mono text-[10.5px] text-dim">{row.model || '—'}</td>
                  <td className="px-2 py-1.5 tabular-nums text-dim">{row.calls}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{row.tokens.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <Ticket size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">注册邀请码</h3>
          <span className="text-[10.5px] text-dim">当前部署注册需邀请码；游客体验不受影响</span>
        </div>
        <div className="grid gap-2 sm:grid-cols-[1fr,90px,90px,auto]">
          <input
            value={inviteNote}
            onChange={(event) => setInviteNote(event.target.value)}
            placeholder="备注（用途 / 发给谁）"
            className={inputClass}
          />
          <input
            value={inviteMaxUses}
            onChange={(event) => setInviteMaxUses(event.target.value)}
            placeholder="可用次数"
            inputMode="numeric"
            className={inputClass}
          />
          <input
            value={inviteExpiresDays}
            onChange={(event) => setInviteExpiresDays(event.target.value)}
            placeholder="有效天数"
            inputMode="numeric"
            className={inputClass}
          />
          <Button size="sm" variant="primary" onClick={() => void createInvite()} disabled={inviteBusy}>
            {inviteBusy ? <Spinner /> : <Plus size={12} />} 生成
          </Button>
        </div>
        <div className="mt-3 overflow-x-auto">
          {invites.length === 0 ? (
            <p className="py-2 text-[11.5px] text-dim">
              还没有邀请码。生成后把码发给需要注册的人，注册页输入即可创建账号。
            </p>
          ) : (
            <table className="w-full border-collapse text-[11.5px]">
              <thead>
                <tr className="border-b border-edge text-left text-dim">
                  <th className="py-1.5 pr-2 font-medium">邀请码</th>
                  <th className="px-2 py-1.5 font-medium">备注</th>
                  <th className="px-2 py-1.5 font-medium">已用 / 次数</th>
                  <th className="px-2 py-1.5 font-medium">有效期至</th>
                  <th className="px-2 py-1.5 text-right font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {invites.map((invite) => {
                  const exhausted = invite.used_count >= invite.max_uses
                  const expired = invite.expires_at ? new Date(invite.expires_at) < new Date() : false
                  return (
                    <tr key={invite.id} className="border-b border-edge/50">
                      <td className="py-1.5 pr-2">
                        <span className="font-mono text-[11px] text-ink">{invite.code}</span>
                      </td>
                      <td className="px-2 py-1.5 text-dim">{invite.note || '—'}</td>
                      <td className="px-2 py-1.5 tabular-nums text-dim">
                        {invite.used_count} / {invite.max_uses}
                        {exhausted && <Badge tone="dim">已用完</Badge>}
                        {!exhausted && expired && <Badge tone="err">已过期</Badge>}
                      </td>
                      <td className="px-2 py-1.5 text-dim">
                        {invite.expires_at ? new Date(invite.expires_at).toLocaleDateString() : '永久'}
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex justify-end gap-1">
                          <button
                            onClick={() => void copyCode(invite.code)}
                            className="flex items-center gap-1 rounded px-1.5 py-1 text-[10.5px] text-dim hover:bg-raised hover:text-ink"
                            title="复制邀请码"
                          >
                            {copiedCode === invite.code ? <CheckCircle2 size={12} className="text-ok" /> : <Copy size={12} />}
                            {copiedCode === invite.code ? '已复制' : '复制'}
                          </button>
                          <button
                            onClick={() => void removeInvite(invite.id)}
                            className="rounded p-1 text-dim hover:bg-err/10 hover:text-err"
                            title="删除邀请码"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </section>

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
          <table className="w-full min-w-[760px] border-collapse text-[11.5px]">
            <thead>
              <tr className="border-b border-edge text-left text-dim">
                <th className="py-1.5 pr-2 font-medium">用户</th>
                <th className="px-2 py-1.5 font-medium">角色</th>
                <th className="px-2 py-1.5 font-medium">状态</th>
                <th className="px-2 py-1.5 font-medium">用量 / 存储</th>
                <th className="px-2 py-1.5 font-medium">最近登录</th>
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
                    <p>{item.tokens_total.toLocaleString()} tokens</p>
                    <p className="text-[10px] text-dim/70">
                      {item.sessions} 会话 · {item.repos} 项目 · {item.files} 文件 · {formatBytes(item.storage_bytes)}
                    </p>
                    {hasCustomQuota(item) && (
                      <p className="mt-0.5"><Badge tone="accent">自定义限额</Badge></p>
                    )}
                  </td>
                  <td className="px-2 py-2 text-[10.5px] text-dim">
                    {item.last_login_at ? new Date(item.last_login_at).toLocaleString() : '—'}
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
                        onClick={() => openQuota(item)}
                        disabled={busy === item.id}
                        className="rounded p-1 text-dim hover:bg-raised hover:text-ink disabled:opacity-30"
                        title="配置限额"
                      >
                        <SlidersHorizontal size={13} />
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

      <Modal
        open={Boolean(quotaTarget)}
        onClose={() => setQuotaTarget(null)}
        title={`配置限额：${quotaTarget?.username ?? ''}`}
        width="max-w-md"
      >
        <p className="mb-3 text-[11px] leading-relaxed text-dim">
          留空表示跟随角色默认档；填 0 表示不限制；填正数则覆盖默认档。用户自己设置的「个人预算」只会在这些上限之内进一步收紧。
        </p>
        <div className="grid gap-2 sm:grid-cols-2">
          {QUOTA_FIELDS.map(({ key, label, hint }) => (
            <label key={key} className="space-y-1">
              <span className="text-[11px] text-dim">{label}</span>
              <input
                value={quotaForm[key] ?? ''}
                onChange={(event) => setQuotaForm({ ...quotaForm, [key]: event.target.value })}
                placeholder={hint}
                className={inputClass}
                inputMode="numeric"
              />
            </label>
          ))}
        </div>
        {quotaError && <p className="mt-2 text-[11.5px] text-err">{quotaError}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" onClick={() => setQuotaTarget(null)}>取消</Button>
          <Button size="sm" variant="primary" onClick={saveQuota}>
            {busy === quotaTarget?.id ? <Spinner /> : null} 保存限额
          </Button>
        </div>
      </Modal>
    </div>
  )
}
