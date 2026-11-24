import clsx from 'clsx'
import {
  AlertTriangle, Bell, Check, Clock, Copy, MessageSquare, RefreshCw, ShieldCheck,
  Smartphone, Trash2,
} from 'lucide-react'
import { QRCodeSVG } from 'qrcode.react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Badge, Button, Modal, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type {
  RemoteAudit, RemoteConfig, RemoteDevice, RemoteInstruction, RemoteNotification,
  RemotePairing,
} from '../lib/types'
import { useChat } from '../stores/chat'

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
  instruction: '指令',
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function remainingSeconds(expiresAt: string): number {
  const value = new Date(expiresAt).getTime()
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.round((value - Date.now()) / 1000))
}

function needsHttps(link: string): boolean {
  try {
    const url = new URL(link)
    return url.protocol === 'http:'
      && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
  } catch {
    return false
  }
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
  const [instructions, setInstructions] = useState<RemoteInstruction[]>([])
  const [instructionBusy, setInstructionBusy] = useState('')
  // An instruction already sent into the chat whose phone-side status could
  // not be updated.  Keeping it out of the normal send path prevents a second
  // click from sending the same text twice.
  const [unsyncedSends, setUnsyncedSends] = useState<Record<string, true>>({})
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
      const [configData, deviceData, instructionData, notificationData, auditData] =
        await Promise.all([
          api.remote.config(),
          api.remote.devices(),
          api.remote.instructions(),
          api.remote.notifications(),
          api.remote.audit(),
        ])
      setConfig(configData)
      setDevices(deviceData.devices)
      setInstructions(instructionData.instructions)
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
    if (!open) return
    const timer = setInterval(() => {
      if (document.hidden) return
      api.remote.instructions()
        .then((data) => setInstructions(data.instructions))
        .catch(() => {})
    }, 5000)
    return () => clearInterval(timer)
  }, [open])

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

  const resolveSent = async (item: RemoteInstruction) => {
    setInstructionBusy(item.instruction_id)
    setError('')
    try {
      await api.remote.resolveInstruction(item.instruction_id, 'sent')
      setInstructions((items) => (
        items.filter((entry) => entry.instruction_id !== item.instruction_id)
      ))
      setUnsyncedSends((items) => {
        const next = { ...items }
        delete next[item.instruction_id]
        return next
      })
      onClose()
      return true
    } catch (err) {
      setUnsyncedSends((items) => ({ ...items, [item.instruction_id]: true }))
      setError(messageOf(
        err,
        '指令已进入对话，但手机端状态同步失败；请点「重试同步」，不要再次发送',
      ))
      return false
    } finally {
      setInstructionBusy('')
    }
  }

  const sendInstruction = async (item: RemoteInstruction) => {
    const chat = useChat.getState()
    if (chat.streaming || chat.uploading) {
      setError('当前对话还在执行，等它完成后再发送这条指令')
      return
    }
    if (chat.attachments.length > 0) {
      setError('输入框里还有附件，请先发送或移除，再处理手机指令')
      return
    }
    if (chat.sessionId && chat.backgroundTurns[chat.sessionId]) {
      setError('当前会话仍有后台任务，请先停止或重新连接')
      return
    }
    if (chat.productMode === 'thesis' && !chat.thesisProjectId) {
      setError('请先在论文模式里打开一个项目，再发送指令')
      return
    }
    setInstructionBusy(item.instruction_id)
    setError('')
    setNotice('')
    let resolving = false
    const accept = () => {
      if (resolving) return
      resolving = true
      void resolveSent(item)
    }
    const accepted = await chat.send(item.text, chat.selectedRepoIds, accept)
    if (!accepted && !resolving) {
      setInstructionBusy('')
      setError('指令没有进入对话，请检查网络或模型设置后再试；它仍在待确认列表里')
      return
    }
    if (!resolving) {
      resolving = true
      void resolveSent(item)
    }
  }

  const rejectInstruction = async (item: RemoteInstruction) => {
    setInstructionBusy(item.instruction_id)
    setError('')
    setNotice('')
    try {
      await api.remote.resolveInstruction(item.instruction_id, 'rejected')
      setInstructions((items) => (
        items.filter((entry) => entry.instruction_id !== item.instruction_id)
      ))
      setNotice('已拒绝这条指令')
    } catch (err) {
      setError(messageOf(err, '拒绝指令失败'))
    } finally {
      setInstructionBusy('')
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
            <p className="text-sm font-medium">手机看进度、发指令、收通知、停止任务</p>
            <p className="mt-0.5 text-2xs leading-relaxed text-dim">
              不新开公网端口：手机打开本站的手机工作台，用一次性链接配对。手机上只看到脱敏进度；
              手机发来的指令先排队，必须在这台电脑上确认后才会进入对话；高风险操作仍需在电脑上确认。
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
              {needsHttps(created.link) && (
                <p className="mb-2 flex items-start gap-1.5 rounded-sm border border-warn/30 bg-warn/10 px-2.5 py-2 text-2xs leading-relaxed text-warn">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                  当前地址是 HTTP，手机浏览器不会开放设备密钥，扫码后只会看到「需要 HTTPS」。
                  等域名和证书生效后再绑定。
                </p>
              )}
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
              <MessageSquare size={13} /> 手机指令
              {instructions.length > 0 && (
                <Badge tone="warn">{instructions.length} 条待确认</Badge>
              )}
            </p>
          </div>
          {instructions.length === 0 ? (
            <p className="text-2xs text-faint">
              手机发来的指令会先出现在这里；确认后才会作为普通消息进入当前对话。
            </p>
          ) : (
            <ul className="space-y-1.5">
              {instructions.map((item) => (
                <li key={item.instruction_id} className="rounded-sm border border-accent/30 bg-accentSoft/15 px-2.5 py-2">
                  <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-ink">
                    {item.text}
                  </p>
                  <p className="mt-1 font-mono text-2xs text-faint">
                    {item.device_id.slice(0, 12)} · {new Date(item.created_at).toLocaleString()}
                  </p>
                  <p className="mt-1 text-2xs leading-relaxed text-faint">
                    发送后会进入当前会话，使用当前权限模式；不会在手机上直接执行。
                  </p>
                  {unsyncedSends[item.instruction_id] ? (
                    <div className="mt-1.5">
                      <p className="text-2xs leading-relaxed text-warn">
                        指令已进入当前对话，手机端状态还没同步。请重试同步，不要再次发送。
                      </p>
                      <Button
                        size="sm"
                        variant="primary"
                        className="mt-1.5"
                        onClick={() => void resolveSent(item)}
                        disabled={!!instructionBusy}
                      >
                        {instructionBusy === item.instruction_id
                          ? <Spinner />
                          : <RefreshCw size={12} />}
                        重试同步
                      </Button>
                    </div>
                  ) : (
                    <div className="mt-1.5 flex gap-1.5">
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => void sendInstruction(item)}
                        disabled={!!instructionBusy}
                      >
                        {instructionBusy === item.instruction_id ? <Spinner /> : <Check size={12} />}
                        确认并发送到当前对话
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => void rejectInstruction(item)}
                        disabled={!!instructionBusy}
                      >
                        拒绝
                      </Button>
                    </div>
                  )}
                </li>
              ))}
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
