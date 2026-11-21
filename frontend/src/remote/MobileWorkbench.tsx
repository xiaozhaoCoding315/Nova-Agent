import clsx from 'clsx'
import {
  AlertTriangle, Bell, Check, Link2, RefreshCw, ShieldCheck, Smartphone, Square, WifiOff,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { RemoteApproval, RemoteNotification, RemoteProgressEvent } from '../lib/types'
import {
  clearStoredDevice, createDeviceKeys, cryptoAvailable, loadStoredDevice, pairingParams,
  removePairingHash, saveStoredDevice, signCommand, type StoredDevice,
} from './device'

type Phase = 'boot' | 'pair' | 'pending' | 'active' | 'unsupported'

const STATUS_LABEL: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  paused: '已暂停',
  needs_approval: '等待确认',
  completed: '已完成',
  failed: '失败',
  stopped: '已停止',
}

const KIND_LABEL: Record<string, string> = {
  completed: '完成',
  stopped: '停止',
  failed: '失败',
  device: '设备',
  status: '状态',
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function timeOf(value: string): string {
  if (!value) return ''
  try {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ''
  }
}

export function MobileWorkbench() {
  const [phase, setPhase] = useState<Phase>('boot')
  const [device, setDevice] = useState<StoredDevice | null>(null)
  const [deviceName, setDeviceName] = useState('手机')
  const [pairId, setPairId] = useState('')
  const [token, setToken] = useState('')
  const [sas, setSas] = useState('')
  const [events, setEvents] = useState<RemoteProgressEvent[]>([])
  const [approvals, setApprovals] = useState<RemoteApproval[]>([])
  const [notifications, setNotifications] = useState<RemoteNotification[]>([])
  const [lastUpdated, setLastUpdated] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const booted = useRef(false)

  const refresh = useCallback(async (target: StoredDevice) => {
    try {
      const envelope = await signCommand(target, 'status.get')
      const result = await api.remote.command(envelope)
      if (result.device_status === 'pending_confirmation') {
        setPhase('pending')
        setSas(result.pairing?.sas ?? '')
        return
      }
      if (result.device_status === 'revoked') {
        setPhase('pair')
        setDevice(null)
        setError('这台设备已被电脑撤销，请重新生成配对链接。')
        await clearStoredDevice()
        return
      }
      if (!result.ok) {
        setError(result.decision.reason || '这条命令没有通过本地策略')
        return
      }
      setPhase('active')
      setDevice(target)
      setEvents(result.events ?? [])
      setApprovals(result.approvals ?? [])
      setNotifications(result.notifications ?? [])
      setLastUpdated(new Date().toLocaleTimeString())
      setError('')
    } catch (err) {
      setError(messageOf(err, '连不上电脑，稍后会自动重试'))
    }
  }, [])

  const claim = useCallback(async (nextPairId: string, nextToken: string, name: string) => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const keys = await createDeviceKeys()
      const claimed = await api.remote.claim({
        pair_id: nextPairId,
        token: nextToken,
        device_name: name.trim() || '手机',
        public_key: keys.publicKey,
      })
      const stored: StoredDevice = {
        deviceId: claimed.device_id,
        pairId: claimed.pair_id,
        name: claimed.device_name,
        privateKey: keys.privateKey,
        createdAt: new Date().toISOString(),
      }
      await saveStoredDevice(stored)
      setDevice(stored)
      setSas(claimed.sas)
      setPhase('pending')
      removePairingHash()
    } catch (err) {
      setError(messageOf(err, '配对失败，请让电脑重新生成链接'))
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (booted.current) return
    booted.current = true
    if (!cryptoAvailable()) {
      setPhase('unsupported')
      return
    }
    void (async () => {
      const stored = await loadStoredDevice()
      if (stored) {
        setDevice(stored)
        setPhase('active')
        removePairingHash()
        await refresh(stored)
        return
      }
      const params = pairingParams()
      if (params) {
        setPairId(params.pairId)
        setToken(params.token)
        await claim(params.pairId, params.token, '手机')
        return
      }
      setPhase('pair')
    })()
  }, [claim, refresh])

  useEffect(() => {
    if (!device || (phase !== 'active' && phase !== 'pending')) return
    let cancelled = false
    const tick = () => {
      if (document.hidden || cancelled) return
      void refresh(device)
    }
    const timer = setInterval(tick, phase === 'pending' ? 3000 : 5000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [device, phase, refresh])

  const stop = async () => {
    if (!device) return
    if (!window.confirm('停止电脑上正在运行的任务？')) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await api.remote.command(await signCommand(device, 'run.stop'))
      if (!result.ok) {
        setError(result.decision.reason || '停止命令没有通过本地策略')
        return
      }
      const count = result.stopped_task_ids?.length ?? 0
      setNotice(count > 0 ? `已停止 ${count} 个任务` : '当前没有运行中的任务')
      await refresh(device)
    } catch (err) {
      setError(messageOf(err, '停止失败，请稍后重试'))
    } finally {
      setBusy(false)
    }
  }

  const decide = async (approval: RemoteApproval, approve: boolean) => {
    if (!device) return
    const verb = approve ? '同意' : '拒绝'
    if (!window.confirm(`${verb}「${approval.title}」？`)) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await api.remote.command(await signCommand(device, 'approval.decide', {
        approvalId: approval.approval_id,
        actionHash: approval.action_hash,
        decision: approve ? 'approve' : 'reject',
      }))
      if (!result.ok) {
        setError(result.decision.reason || '审批没有通过本地策略')
        return
      }
      setNotice(`已${verb}：${approval.title}`)
      await refresh(device)
    } catch (err) {
      setError(messageOf(err, '审批失败，请稍后重试'))
    } finally {
      setBusy(false)
    }
  }

  const markRead = async () => {
    try {
      await api.remote.readNotifications()
      setNotifications((items) => items.map((item) => ({ ...item, read: true })))
    } catch {
      /* 已读状态下次刷新会同步 */
    }
  }

  const unpairLocally = async () => {
    if (!window.confirm('从这台手机移除设备密钥？电脑上的设备不会自动撤销。')) return
    await clearStoredDevice()
    setDevice(null)
    setEvents([])
    setApprovals([])
    setNotifications([])
    setPhase('pair')
    setNotice('已从手机移除。电脑上仍可在「遥控」里撤销这台设备。')
  }

  const unread = notifications.filter((item) => !item.read).length

  if (phase === 'boot') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base font-mono text-sm text-dim">
        <RefreshCw size={14} className="mr-2 animate-spin" /> 正在连接…
      </div>
    )
  }

  if (phase === 'unsupported') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base px-6 text-ink">
        <div className="max-w-sm">
          <p className="flex items-center gap-2 text-sm font-medium"><WifiOff size={16} /> 需要 HTTPS</p>
          <p className="mt-2 text-sm leading-relaxed text-dim">
            手机工作台用浏览器生成的设备密钥签名命令，只有 HTTPS 或 localhost 才允许。
            请通过部署好的 HTTPS 地址打开这个页面。
          </p>
        </div>
      </div>
    )
  }

  if (phase === 'pair') {
    return (
      <div className="min-h-screen bg-base px-4 py-8 text-ink">
        <div className="mx-auto max-w-sm">
          <p className="flex items-center gap-2 font-mono text-2xs uppercase tracking-wider text-faint">
            <Smartphone size={14} className="text-accent" /> Nova 手机工作台
          </p>
          <h1 className="mt-2 text-xl font-medium">和电脑配对</h1>
          <p className="mt-2 text-sm leading-relaxed text-dim">
            在电脑上打开「遥控」，点「生成配对链接」，再扫二维码或用链接打开本页。
            配对时手机会生成一对只留在本机的密钥。
          </p>

          {notice && (
            <p className="mt-3 rounded-sm border border-ok/30 bg-ok/10 px-2.5 py-2 text-xs text-ok">{notice}</p>
          )}
          {error && (
            <p className="mt-3 flex items-start gap-1.5 rounded-sm border border-err/30 bg-err/10 px-2.5 py-2 text-xs text-err">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {error}
            </p>
          )}

          <div className="mt-4 space-y-2 rounded-md border border-edge bg-panel/40 p-3">
            <label className="block text-xs text-dim">
              配对 ID
              <input
                value={pairId}
                onChange={(event) => setPairId(event.target.value)}
                className="mt-1 w-full rounded-sm border border-edge bg-base px-2 py-1.5 font-mono text-xs text-ink outline-none focus:border-accent"
                placeholder="pair_…"
                autoCapitalize="off"
                autoCorrect="off"
              />
            </label>
            <label className="block text-xs text-dim">
              一次性 token
              <input
                value={token}
                onChange={(event) => setToken(event.target.value)}
                className="mt-1 w-full rounded-sm border border-edge bg-base px-2 py-1.5 font-mono text-xs text-ink outline-none focus:border-accent"
                placeholder="扫描链接会自动填入"
                autoCapitalize="off"
                autoCorrect="off"
              />
            </label>
            <label className="block text-xs text-dim">
              设备名称
              <input
                value={deviceName}
                onChange={(event) => setDeviceName(event.target.value)}
                className="mt-1 w-full rounded-sm border border-edge bg-base px-2 py-1.5 text-xs text-ink outline-none focus:border-accent"
                maxLength={60}
              />
            </label>
            <button
              onClick={() => void claim(pairId.trim(), token.trim(), deviceName)}
              disabled={busy || !pairId.trim() || !token.trim()}
              className="flex w-full items-center justify-center gap-1.5 rounded-sm bg-accent px-3 py-2 text-sm font-medium text-base transition-opacity disabled:opacity-50"
            >
              {busy ? <RefreshCw size={14} className="animate-spin" /> : <Link2 size={14} />}
              开始配对
            </button>
          </div>

          <p className="mt-4 flex items-start gap-1.5 text-2xs leading-relaxed text-faint">
            <ShieldCheck size={12} className="mt-0.5 shrink-0" />
            手机只能看到脱敏进度、执行停止和接收完成通知；高风险操作仍需在电脑上确认。
          </p>
        </div>
      </div>
    )
  }

  if (phase === 'pending') {
    return (
      <div className="flex min-h-screen flex-col bg-base px-4 py-8 text-ink">
        <div className="mx-auto w-full max-w-sm">
          <p className="flex items-center gap-2 font-mono text-2xs uppercase tracking-wider text-faint">
            <Smartphone size={14} className="text-accent" /> 等待电脑确认
          </p>
          <h1 className="mt-2 text-xl font-medium">核对这串数字</h1>
          <p className="mt-2 text-sm leading-relaxed text-dim">
            电脑上应该显示同样的数字。确认一致后，在电脑上点「确认绑定」。
          </p>
          <div className="mt-6 rounded-lg border border-accent/40 bg-accentSoft/20 py-6 text-center">
            <p className="font-mono text-4xl tracking-[0.2em] text-ink">{sas || '—— ——'}</p>
            <p className="mt-2 text-2xs text-faint">验证串</p>
          </div>
          <div className="mt-4 flex items-center justify-between text-xs text-dim">
            <span className="flex items-center gap-1.5">
              <RefreshCw size={12} className="animate-spin" /> 每 3 秒检查一次
            </span>
            <button onClick={() => device && void refresh(device)} className="underline underline-offset-2">
              立即检查
            </button>
          </div>
          {error && (
            <p className="mt-3 rounded-sm border border-err/30 bg-err/10 px-2.5 py-2 text-xs text-err">{error}</p>
          )}
          <button
            onClick={() => void unpairLocally()}
            className="mt-6 w-full rounded-sm border border-edge px-3 py-2 text-xs text-dim hover:text-ink"
          >
            取消，换一台设备
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-base pb-24 text-ink">
      <header className="sticky top-0 z-10 border-b border-edge bg-base/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-xl items-center gap-2">
          <Smartphone size={16} className="text-accent" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{device?.name || '手机工作台'}</p>
            <p className="font-mono text-2xs text-faint">
              {lastUpdated ? `更新于 ${lastUpdated}` : '连接中'}
              {unread > 0 ? ` · ${unread} 条未读` : ''}
            </p>
          </div>
          <button
            onClick={() => device && void refresh(device)}
            className="rounded-sm border border-edge p-1.5 text-dim hover:text-ink"
            aria-label="刷新进度"
          >
            <RefreshCw size={13} />
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-xl space-y-4 px-4 py-4">
        {error && (
          <div className="flex items-start gap-2 rounded-md border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1">{error}</span>
          </div>
        )}
        {notice && (
          <div className="flex items-start gap-2 rounded-md border border-ok/30 bg-ok/10 px-3 py-2 text-xs text-ok">
            <Check size={13} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1">{notice}</span>
          </div>
        )}

        <section>
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-dim">当前进度</p>
            <span className="font-mono text-2xs text-faint">{events.length} 个任务</span>
          </div>
          {events.length === 0 ? (
            <div className="mt-2 rounded-md border border-edge bg-panel/40 px-3 py-6 text-center">
              <p className="text-sm text-dim">电脑上暂时没有运行中的任务</p>
              <p className="mt-1 text-2xs text-faint">任务完成后，通知会出现在下面。</p>
            </div>
          ) : (
            <ul className="mt-2 space-y-2">
              {events.map((event) => (
                <li key={event.event_id} className="rounded-md border border-edge bg-panel/40 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span
                      className={clsx(
                        'rounded-sm px-1.5 py-0.5 font-mono text-2xs',
                        event.status === 'running'
                          ? 'bg-accentSoft/40 text-accent'
                          : 'bg-raised text-dim',
                      )}
                    >
                      {STATUS_LABEL[event.status] ?? (event.status || '进行中')}
                    </span>
                    <span className="truncate font-mono text-2xs text-faint">
                      {event.stage || event.task_id.slice(0, 8)}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed">{event.summary}</p>
                  {event.percent !== null && event.percent !== undefined && (
                    <div className="mt-2 h-1 overflow-hidden rounded-full bg-raised">
                      <div
                        className="h-full rounded-full bg-accent transition-[width] duration-500"
                        style={{ width: `${event.percent}%` }}
                      />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-xs font-medium text-dim">
              <ShieldCheck size={13} /> 待审批
            </p>
            {approvals.length > 0 && (
              <span className="font-mono text-2xs text-faint">{approvals.length} 项</span>
            )}
          </div>
          {approvals.length === 0 ? (
            <p className="mt-2 text-2xs text-faint">没有等待你确认的操作。</p>
          ) : (
            <ul className="mt-2 space-y-2">
              {approvals.map((approval) => (
                <li key={approval.approval_id} className="rounded-md border border-edge bg-panel/40 p-3">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={clsx(
                        'rounded-sm px-1.5 py-0.5 font-mono text-2xs',
                        approval.risk === 'high'
                          ? 'bg-err/15 text-err'
                          : approval.risk === 'medium'
                            ? 'bg-warn/15 text-warn'
                            : 'bg-raised text-dim',
                      )}
                    >
                      {approval.risk === 'high' ? '高风险' : approval.risk === 'medium' ? '中风险' : '低风险'}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-xs text-ink">{approval.title}</span>
                  </div>
                  {approval.reason && (
                    <p className="mt-1 text-2xs leading-relaxed text-dim">{approval.reason}</p>
                  )}
                  {approval.remote_decidable ? (
                    <div className="mt-2 flex gap-1.5">
                      <button
                        onClick={() => void decide(approval, true)}
                        disabled={busy}
                        className="flex-1 rounded-sm bg-accent px-2 py-1.5 text-xs font-medium text-base disabled:opacity-50"
                      >
                        同意
                      </button>
                      <button
                        onClick={() => void decide(approval, false)}
                        disabled={busy}
                        className="flex-1 rounded-sm border border-edge px-2 py-1.5 text-xs text-dim disabled:opacity-50"
                      >
                        拒绝
                      </button>
                    </div>
                  ) : (
                    <p className="mt-2 flex items-center gap-1 text-2xs text-warn">
                      <AlertTriangle size={11} /> 高风险操作只能在电脑上确认
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-xs font-medium text-dim">
              <Bell size={13} /> 通知
            </p>
            {unread > 0 && (
              <button onClick={() => void markRead()} className="text-2xs text-accent underline underline-offset-2">
                全部已读
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <p className="mt-2 text-2xs text-faint">还没有通知。</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {notifications.slice(0, 12).map((item) => (
                <li
                  key={item.id}
                  className={clsx(
                    'rounded-sm border px-2.5 py-2',
                    item.read ? 'border-edge bg-panel/30' : 'border-accent/30 bg-accentSoft/20',
                  )}
                >
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-2xs text-faint">
                      {timeOf(item.created_at)}
                    </span>
                    <span className="rounded-sm bg-raised px-1 py-0.5 text-2xs text-dim">
                      {KIND_LABEL[item.kind] ?? item.kind}
                    </span>
                    {!item.read && <span className="h-1.5 w-1.5 rounded-full bg-accent" />}
                  </div>
                  <p className="mt-0.5 text-xs leading-relaxed text-ink">{item.summary}</p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <p className="flex items-start gap-1.5 pt-2 text-2xs leading-relaxed text-faint">
          <ShieldCheck size={12} className="mt-0.5 shrink-0" />
          这里只有任务 ID、脱敏摘要和阶段；中低风险审批可以处理，高风险操作必须回电脑确认。
          源码、路径、密钥与完整日志留在电脑上。
        </p>

        <button
          onClick={() => void unpairLocally()}
          className="w-full text-center text-2xs text-faint underline underline-offset-2 hover:text-dim"
        >
          从这台手机移除设备
        </button>
      </main>

      <div className="fixed inset-x-0 bottom-0 border-t border-edge bg-base/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto max-w-xl">
          <button
            onClick={() => void stop()}
            disabled={busy}
            className="flex w-full items-center justify-center gap-2 rounded-md border border-err/40 bg-err/10 px-4 py-3 text-sm font-medium text-err transition-colors hover:bg-err/20 disabled:opacity-50"
          >
            {busy ? <RefreshCw size={15} className="animate-spin" /> : <Square size={15} />}
            停止电脑上的任务
          </button>
        </div>
      </div>
    </div>
  )
}
