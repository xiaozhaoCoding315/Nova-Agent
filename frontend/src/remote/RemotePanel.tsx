import clsx from 'clsx'
import {
  AlertTriangle, Bell, Check, Clock, Copy, RefreshCw, ShieldCheck, Smartphone, Trash2,
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type {
  RemoteAudit, RemoteConfig, RemoteDevice, RemoteNotification, RemotePairing,
} from '../lib/types'

type CreatedPairing = {
  pairing: RemotePairing
  token: string
  link: string
  expires_at: string
  ttl_seconds: number
  note: string
}

const DEVICE_STATUS: Record<string, { label: string; tone: 'ok' | 'warn' | 'err' | 'dim' }> = {
  pending: { label: '待确认', tone: 'warn' },
  active: { label: '已绑定', tone: 'ok' },
  revoked: { label: '已撤销', tone: 'err' },
}

const NOTIFICATION_LABEL: Record<string, string> = {
  completed: '完成',
  stopped: '停止',
  failed: '失败',
  device: '设备',
  status: '状态',
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function remainingSeconds(expiresAt: string): number {
  const value = new Date(expiresAt).getTime()
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.round((value - Date.now()) / 1000))
}

export function RemotePanel({
  open,
  onClose,
  onUnreadChange,
}: {
  open: boolean
  onClose: () => void
  onUnreadChange?: (count: number) => void
}) {
  const [config, setConfig] = useState<RemoteConfig | null>(null)
  const [created, setCreated] = useState<CreatedPairing | null>(null)
  const [pairing, setPairing] = useState<RemotePairing | null>(null)
  const [devices, setDevices] = useState<RemoteDevice[]>([])
  const [notifications, setNotifications] = useState<RemoteNotification[]>([])
  const [audit, setAudit] = useState<RemoteAudit | null>(null)
  const [unread, setUnread] = useState(0)
  const [seconds, setSeconds] = useState(0)
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [configData, deviceData, notificationData, auditData] = await Promise.all([
        api.remote.config(),
        api.remote.devices(),
        api.remote.notifications(),
        api.remote.audit(),
      ])
      setConfig(configData)
      setDevices(deviceData.devices)
      setNotifications(notificationData.notifications)
      setUnread(notificationData.unread)
      onUnreadChange?.(notificationData.unread)
      setAudit(auditData)
    } catch (err) {
      setError(messageOf(err, '远程工作台不可用'))
    } finally {
      setLoading(false)
    }
  }, [onUnreadChange])

  useEffect(() => {
    if (open) void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!created) return
    setSeconds(remainingSeconds(created.expires_at))
    const tick = setInterval(() => setSeconds((value) => Math.max(0, value - 1)), 1000)
    return () => clearInterval(tick)
  }, [created])

  useEffect(() => {
    if (!open || !created) return
    const status = pairing?.status ?? 'pending'
    if (status !== 'pending' && status !== 'claimed') return
    let cancelled = false
    const poll = async () => {
      try {
        const data = await api.remote.pairing(created.pairing.pair_id)
        if (cancelled) return
        setPairing(data.pairing)
        if (data.pairing.status === 'confirmed') {
          setNotice('设备已绑定，可以让手机查看进度了')
          await load()
        }
      } catch {
        /* 轮询失败保留上一状态 */
      }
    }
    void poll()
    const timer = setInterval(poll, 2000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [open, created, pairing?.status, load])

  const createLink = async () => {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const data = await api.remote.createPairing()
      setCreated(data)
      setPairing(data.pairing)
      setSeconds(remainingSeconds(data.expires_at))
    } catch (err) {
      setError(messageOf(err, '生成配对链接失败'))
    } finally {
      setBusy(false)
    }
  }

  const confirmPairing = async () => {
    if (!pairing) return
    setBusy(true)
    setError('')
    try {
      await api.remote.confirm(pairing.pair_id, pairing.sas)
      setNotice('设备已绑定')
      setPairing({ ...pairing, status: 'confirmed' })
      await load()
    } catch (err) {
      setError(messageOf(err, '确认绑定失败'))
    } finally {
      setBusy(false)
    }
  }

  const rejectPairing = async () => {
    if (!pairing) return
    setBusy(true)
    setError('')
    try {
      await api.remote.reject(pairing.pair_id)
      setPairing({ ...pairing, status: 'rejected' })
      setCreated(null)
      setNotice('已拒绝这次配对')
      await load()
    } catch (err) {
      setError(messageOf(err, '拒绝配对失败'))
    } finally {
      setBusy(false)
    }
  }

  const revoke = async (device: RemoteDevice) => {
    if (!window.confirm(`撤销「${device.name}」？旧命令会立即失效。`)) return
    setBusy(true)
    setError('')
    try {
      await api.remote.revoke(device.device_id)
      setNotice(`已撤销「${device.name}」`)
      await load()
    } catch (err) {
      setError(messageOf(err, '撤销设备失败'))
    } finally {
      setBusy(false)
    }
  }

  const markRead = async () => {
    try {
      await api.remote.readNotifications()
      setNotifications((items) => items.map((item) => ({ ...item, read: true })))
      setUnread(0)
      onUnreadChange?.(0)
    } catch (err) {
      setError(messageOf(err, '标记已读失败'))
    }
  }

  const copyLink = async () => {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.link)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('浏览器不允许读取剪贴板，请手动复制链接')
    }
  }

  const activeDevices = useMemo(
    () => devices.filter((device) => device.status === 'active'),
    [devices],
  )

  return (
    <Modal open={open} onClose={onClose} title="遥控" width="max-w-2xl">
      <div className="space-y-4">
        <div className="flex items-start gap-2 rounded-md border border-edge bg-panel/40 px-3 py-2">
          <Smartphone size={15} className="mt-0.5 shrink-0 text-accent" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">手机看进度、收通知、停止任务</p>
            <p className="mt-0.5 text-2xs leading-relaxed text-dim">
              不新开公网端口：手机打开本站的手机工作台，用一次性链接配对。手机上只看到脱敏进度；
              高风险操作仍需在这台电脑上确认。
            </p>
            {config && (
              <p className="mt-1 font-mono text-2xs text-faint">
                模式：{config.mode === 'relay' ? '受控中继' : '同站直连'} · 可用命令：
                {config.commands.join(' / ')} · {config.transport}
              </p>
            )}
          </div>
          <Badge tone="dim">{activeDevices.length} 台在线</Badge>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-sm border border-err/30 bg-err/10 px-2.5 py-2 text-xs text-err">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1">{error}</span>
            <button onClick={() => setError('')} className="underline">关闭</button>
          </div>
        )}
        {notice && (
          <p className="flex items-center gap-1.5 rounded-sm border border-ok/30 bg-ok/10 px-2.5 py-2 text-xs text-ok">
            <Check size={12} /> {notice}
          </p>
        )}

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="text-xs font-medium text-ink">配对</p>
            {(!created || pairing?.status === 'expired' || pairing?.status === 'rejected') && (
              <Button size="sm" onClick={() => void createLink()} disabled={busy || loading}>
                {busy ? <Spinner /> : <RefreshCw size={12} />} 生成配对链接
              </Button>
            )}
          </div>

          {!created ? (
            <p className="text-2xs leading-relaxed text-faint">
              生成后 5 分钟内有效，链接只能用一次。秘密在链接的 # 后面，不会进入服务器查询日志。
            </p>
          ) : (
            <div className="rounded-md border border-edge bg-panel/40 p-3">
              <div className="flex flex-col gap-3 sm:flex-row">
                <div className="mx-auto shrink-0 rounded-sm bg-white p-2">
                  <QRCodeSVG value={created.link} size={156} level="M" />
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  {pairing?.status === 'claimed' ? (
                    <>
                      <p className="text-xs text-ink">
                        「{pairing.device_name || '手机'}」请求绑定。核对手机上的验证串：
                      </p>
                      <p className="rounded-sm border border-accent/40 bg-accentSoft/20 py-2 text-center font-mono text-2xl tracking-[0.2em]">
                        {pairing.sas}
                      </p>
                      <div className="flex gap-1.5">
                        <Button size="sm" variant="primary" onClick={() => void confirmPairing()} disabled={busy}>
                          数字一致，确认绑定
                        </Button>
                        <Button size="sm" onClick={() => void rejectPairing()} disabled={busy}>
                          拒绝
                        </Button>
                      </div>
                    </>
                  ) : pairing?.status === 'confirmed' ? (
                    <p className="flex items-center gap-1.5 text-xs text-ok">
                      <Check size={13} /> 配对完成，手机工作台已可用
                    </p>
                  ) : (
                    <>
                      <p className="flex items-center gap-1.5 text-xs text-dim">
                        <Clock size={12} />
                        {seconds > 0 ? `等待手机扫码，${seconds} 秒后失效` : '链接已失效，请重新生成'}
                      </p>
                      <div className="flex items-center gap-1.5 rounded-sm border border-edge bg-base px-2 py-1.5">
                        <code className="min-w-0 flex-1 truncate font-mono text-2xs text-dim">
                          {created.link}
                        </code>
                        <button
                          onClick={() => void copyLink()}
                          className="shrink-0 text-dim hover:text-ink"
                          aria-label="复制配对链接"
                        >
                          {copied ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                        </button>
                      </div>
                      <p className="text-2xs leading-relaxed text-faint">
                        手机打开链接或扫二维码后，这里会显示设备名称和验证串。
                      </p>
                    </>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>

        <section className="space-y-1.5">
          <p className="text-xs font-medium text-ink">设备</p>
          {devices.length === 0 ? (
            <p className="text-2xs text-faint">还没有绑定设备。</p>
          ) : (
            <ul className="space-y-1">
              {devices.map((device) => {
                const status = DEVICE_STATUS[device.status] ?? DEVICE_STATUS.pending
                return (
                  <li
                    key={device.device_id}
                    className="flex items-center gap-2 rounded-sm border border-edge bg-panel/40 px-2 py-1.5"
                  >
                    <Smartphone size={13} className="shrink-0 text-dim" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs text-ink">{device.name || '手机'}</p>
                      <p className="font-mono text-2xs text-faint">
                        {new Date(device.created_at).toLocaleString()}
                        {device.last_seen_at ? ` · 最近 ${new Date(device.last_seen_at).toLocaleTimeString()}` : ''}
                      </p>
                    </div>
                    <Badge tone={status.tone}>{status.label}</Badge>
                    {device.status !== 'revoked' && (
                      <button
                        onClick={() => void revoke(device)}
                        disabled={busy}
                        className="shrink-0 rounded-sm p-1 text-dim hover:text-err"
                        title="撤销设备"
                        aria-label={`撤销 ${device.name}`}
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section className="space-y-1.5">
          <div className="flex items-center justify-between">
            <p className="flex items-center gap-1.5 text-xs font-medium text-ink">
              <Bell size={13} /> 完成通知
              {unread > 0 && <Badge tone="warn">{unread} 未读</Badge>}
            </p>
            {unread > 0 && (
              <button onClick={() => void markRead()} className="text-2xs text-accent underline underline-offset-2">
                全部已读
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <p className="text-2xs text-faint">还没有通知。任务结束时会出现在这里。</p>
          ) : (
            <ul className="space-y-1">
              {notifications.slice(0, 8).map((item) => (
                <li
                  key={item.id}
                  className={clsx(
                    'flex items-start gap-2 rounded-sm border px-2 py-1.5',
                    item.read ? 'border-edge bg-panel/30' : 'border-accent/30 bg-accentSoft/20',
                  )}
                >
                  <span className="mt-0.5 shrink-0 rounded-sm bg-raised px-1 py-0.5 text-2xs text-dim">
                    {NOTIFICATION_LABEL[item.kind] ?? item.kind}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-ink">{item.summary}</p>
                    <p className="font-mono text-2xs text-faint">
                      {new Date(item.created_at).toLocaleString()}
                      {item.task_id ? ` · ${item.task_id.slice(0, 8)}` : ''}
                    </p>
                  </div>
                  {!item.read && <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />}
                </li>
              ))}
            </ul>
          )}
        </section>

        <details className="rounded-sm border border-edge bg-panel/30 px-2.5 py-2">
          <summary className="cursor-pointer text-xs text-dim">最近审计</summary>
          {!audit ? (
            <p className="mt-1 text-2xs text-faint">加载中…</p>
          ) : audit.local.length === 0 ? (
            <p className="mt-1 text-2xs text-faint">还没有远程操作记录。</p>
          ) : (
            <ul className="mt-1.5 space-y-0.5 font-mono text-2xs text-faint">
              {audit.local.slice(0, 10).map((item, index) => (
                <li key={String(item.event_id ?? index)} className="truncate">
                  {String(item.created_at ?? '').slice(11, 19)} · {String(item.action ?? '')}
                  {item.type ? ` · ${String(item.type)}` : ''} · {String(item.decision ?? '')}
                  {item.reason ? ` · ${String(item.reason)}` : ''}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1.5 flex items-start gap-1 text-2xs leading-relaxed text-faint">
            <ShieldCheck size={11} className="mt-0.5 shrink-0" />
            本地与中继各留一份审计；中继只有设备、命令 ID、意图和决定。
          </p>
        </details>
      </div>
    </Modal>
  )
}
