import {
  CheckCircle2, Eye, EyeOff, KeyRound, Plus, Server, Star, Trash2, XCircle, Zap,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { ProviderIcon } from './ProviderIcon'
import { Badge, Button, Modal, Spinner } from './common'
import type { LlmCredential, LlmProvider, LlmSettings } from '../lib/types'
import { ApiError } from '../lib/api'
import { useLlm } from '../stores/llm'

const inputClass =
  'w-full rounded-lg border border-edge bg-base/60 px-3 py-2 text-[12.5px] text-ink outline-none transition-colors focus:border-accent/60 disabled:opacity-50'

const GROUP_LABEL: Record<string, string> = {
  domestic: '国内厂商',
  international: '国际厂商',
  aggregator: '聚合网关',
  local: '本地 / 自定义',
}

type Feedback = { ok: boolean; text: string }

export function ModelSettings({
  settings, loading, onReload,
}: {
  settings: LlmSettings | null
  loading: boolean
  onReload: () => void
}) {
  const { saveCredential, deleteCredential, setDefault, test } = useLlm()
  const [editing, setEditing] = useState<string | null>(null)
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [contextWindow, setContextWindow] = useState('')
  const [reasoningEffort, setReasoningEffort] = useState('')
  const [makeDefault, setMakeDefault] = useState(false)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)
  const [feedback, setFeedback] = useState<Feedback | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const runAction = (task: Promise<unknown>) => {
    setActionError(null)
    void task
      .then(onReload)
      .catch((err) => {
        setActionError(err instanceof ApiError ? err.message : '操作失败')
      })
  }

  const providers = settings?.providers ?? []
  const credentials = settings?.credentials ?? []
  const defaultCredential = credentials.find((item) => item.is_default) ?? credentials[0]
  const spec = providers.find((item) => item.id === editing)
  const current = credentials.find((item) => item.provider === editing)

  const grouped = useMemo(() => {
    const groups = new Map<string, LlmProvider[]>()
    for (const provider of providers) {
      const list = groups.get(provider.group) ?? []
      list.push(provider)
      groups.set(provider.group, list)
    }
    return [...groups.entries()]
  }, [providers])

  const openAdd = (provider: LlmProvider) => {
    setEditing(provider.id)
    setModel(provider.models[0] ?? '__custom__')
    setCustomModel('')
    setBaseUrl(provider.base_url)
    setApiKey('')
    setShowKey(false)
    setContextWindow(String(provider.context_window || ''))
    setReasoningEffort('')
    setMakeDefault(credentials.length === 0)
    setFeedback(null)
  }

  const openEdit = (credential: LlmCredential) => {
    const provider = providers.find((item) => item.id === credential.provider)
    setEditing(credential.provider)
    setModel(
      provider?.models.includes(credential.model) ? credential.model : '__custom__',
    )
    setCustomModel(
      provider?.models.includes(credential.model) ? '' : credential.model,
    )
    setBaseUrl(credential.base_url)
    setApiKey('')
    setShowKey(false)
    setContextWindow(
      credential.context_window ? String(credential.context_window) : '',
    )
    setReasoningEffort(credential.reasoning_effort || '')
    setMakeDefault(credential.is_default)
    setFeedback(null)
  }

  const close = () => {
    setEditing(null)
    setFeedback(null)
    setBusy(false)
    setTesting(false)
  }

  const effectiveModel = model === '__custom__' ? customModel.trim() : model

  const submit = async (mode: 'save' | 'test') => {
    if (!spec || !effectiveModel) {
      setFeedback({ ok: false, text: '请选择或填写模型名称' })
      return
    }
    if (mode === 'save') setBusy(true)
    else setTesting(true)
    setFeedback(null)
    const input = {
      provider: spec.id,
      model: effectiveModel,
      base_url: spec.base_url_locked ? null : baseUrl.trim() || null,
      api_key: apiKey.trim() || null,
      context_window: contextWindow.trim() ? Number(contextWindow.trim()) : 0,
      reasoning_effort: reasoningEffort,
    }
    try {
      if (mode === 'save') {
        await saveCredential(spec.id, { ...input, is_default: makeDefault })
        onReload()
        close()
      } else {
        const result = await test(input)
        setFeedback({
          ok: result.ok,
          text: `${result.message}${result.latency_ms ? `（${result.latency_ms} ms）` : ''}`,
        })
      }
    } catch (err) {
      setFeedback({
        ok: false,
        text: err instanceof ApiError ? err.message : '操作失败',
      })
    } finally {
      setBusy(false)
      setTesting(false)
    }
  }

  if (!settings) {
    return (
      <p className="flex items-center gap-2 text-[12.5px] text-dim">
        {loading ? <Spinner /> : null} 加载模型配置…
      </p>
    )
  }

  const sourceUser = settings.source === 'user'

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="flex items-start gap-3">
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
            sourceUser ? 'bg-accentSoft/50 text-accent' : 'bg-raised text-dim'
          }`}>
            {sourceUser ? <KeyRound size={16} /> : <Server size={16} />}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-[13px] font-medium">
                {sourceUser
                  ? '正在使用你自己的 API Key'
                  : settings.source === 'server'
                    ? '正在使用服务端共享密钥'
                    : '尚未配置可用模型'}
              </p>
              <Badge tone={sourceUser ? 'accent' : settings.source === 'server' ? 'ok' : 'err'}>
                {sourceUser ? '个人' : settings.source === 'server' ? '共享' : '未配置'}
              </Badge>
            </div>
            <p className="mt-1 break-all text-[11.5px] text-dim">
              {defaultCredential
                ? `${defaultCredential.label} · ${defaultCredential.model}`
                : settings.model ?? '—'}
              {defaultCredential?.key_hint ? ` · ${defaultCredential.key_hint}` : ''}
            </p>
            {!sourceUser && settings.source === 'server' && (
              <p className="mt-1 text-[11px] leading-relaxed text-dim/80">
                对话会消耗部署者的额度。保存自己的 Key 后将完全改用你的配置，不回退到共享密钥。
              </p>
            )}
            {settings.source === 'none' && !settings.allow_server_fallback && (
              <p className="mt-1 text-[11px] leading-relaxed text-warn">
                当前账号需使用个人 API Key：请在下方配置后即可开始对话（Key 加密存储，仅供你自己的对话使用）。
              </p>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-edge bg-panel p-4">
        <div className="mb-3 flex items-center gap-2">
          <Star size={14} className="text-accent" />
          <h3 className="text-[13px] font-medium">已配置厂商</h3>
          <span className="text-[10.5px] text-dim">
            {credentials.length > 0 ? `${credentials.length} 家` : '还没有配置'}
          </span>
          <Button size="sm" className="ml-auto" onClick={() => setEditing('__add__')}>
            <Plus size={12} /> 添加厂商
          </Button>
        </div>

        {credentials.length === 0 ? (
          <p className="text-[12px] leading-relaxed text-dim">
            先添加一家厂商。推荐智谱 GLM：注册后即可使用免费的 glm-4.7-flash。
          </p>
        ) : (
          <div className="space-y-2">
            {credentials.map((credential) => (
              <div
                key={credential.provider}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-edge/80 bg-base/30 px-3 py-2"
              >
                <ProviderIcon id={credential.provider} size={20} />
                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-1.5 truncate text-[12.5px] font-medium">
                    {credential.label}
                    {credential.is_default && <Badge tone="accent">默认</Badge>}
                  </p>
                  <p className="truncate font-mono text-[10.5px] text-dim">
                    {credential.model} · {credential.key_hint || '无 Key'}
                  </p>
                </div>
                <Button size="sm" onClick={() => openEdit(credential)}>编辑</Button>
                {!credential.is_default && (
                  <Button
                    size="sm"
                    onClick={() => runAction(setDefault(credential.provider))}
                  >
                    设为默认
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => setConfirmDelete(credential.provider)}
                >
                  <Trash2 size={12} />
                </Button>
              </div>
            ))}
          </div>
        )}
        {actionError && (
          <p className="mt-2 text-[11.5px] text-err">{actionError}</p>
        )}
      </section>

      {editing === '__add__' && (
        <section className="rounded-xl border border-edge bg-panel p-4">
          <div className="mb-3 flex items-center gap-2">
            <Plus size={14} className="text-accent" />
            <h3 className="text-[13px] font-medium">选择厂商</h3>
            <Button size="sm" className="ml-auto" onClick={close}>取消</Button>
          </div>
          <div className="space-y-3">
            {grouped.map(([group, items]) => (
              <div key={group}>
                <p className="mb-1.5 text-[10.5px] uppercase tracking-[0.12em] text-dim/70">
                  {GROUP_LABEL[group] ?? group}
                </p>
                <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
                  {items.map((provider) => (
                    <button
                      key={provider.id}
                      type="button"
                      onClick={() => openAdd(provider)}
                      className="flex items-center gap-2 rounded-lg border border-edge/80 px-2.5 py-2 text-left transition-colors hover:border-accentSoft hover:bg-raised/40"
                    >
                      <ProviderIcon id={provider.id} size={20} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12px] font-medium">
                          {provider.label}
                        </span>
                        <span className="block truncate text-[10px] text-dim">
                          {provider.free_tier ? '免费额度' : provider.models[0] || '手动填写模型'}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <Modal
        open={Boolean(spec)}
        onClose={close}
        title={current ? `编辑 ${spec?.label ?? ''}` : `添加 ${spec?.label ?? ''}`}
        width="max-w-lg"
      >
        {spec && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded-lg border border-edge/70 bg-base/30 px-3 py-2">
              <ProviderIcon id={spec.id} size={22} />
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] font-medium">{spec.label}</p>
                <p className="truncate font-mono text-[10px] text-dim">{spec.base_url}</p>
              </div>
              {spec.free_tier && <Badge tone="ok">免费</Badge>}
            </div>

            {!spec.base_url_locked && (
              <label className="block">
                <span className="mb-1 block text-[11.5px] text-dim">Base URL</span>
                <input
                  className={inputClass}
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  placeholder="https://api.example.com/v1"
                  spellCheck={false}
                />
              </label>
            )}

            <label className="block">
              <span className="mb-1 block text-[11.5px] text-dim">
                API Key
                {current?.has_key ? `（已保存 ${current.key_hint}，留空保持不变）` : ''}
              </span>
              <div className="relative">
                <input
                  className={`${inputClass} pr-9`}
                  type={showKey ? 'text' : 'password'}
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder={current?.has_key ? '留空则继续使用已保存的 Key' : 'sk-…'}
                  autoComplete="off"
                  spellCheck={false}
                />
                <button
                  type="button"
                  onClick={() => setShowKey((value) => !value)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-dim hover:text-ink"
                  aria-label={showKey ? '隐藏密钥' : '显示密钥'}
                >
                  {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <span className="mt-1 block text-[10px] text-dim/70">
                Key 以 SECRET_KEY 派生密钥加密；接口只返回掩码。
              </span>
            </label>

            <label className="block">
              <span className="mb-1 block text-[11.5px] text-dim">模型</span>
              {spec.models.length > 0 ? (
                <select
                  className={inputClass}
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                >
                  {spec.models.map((item) => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                  <option value="__custom__">自定义模型…</option>
                </select>
              ) : null}
              {(model === '__custom__' || spec.models.length === 0) && (
                <input
                  className={`${inputClass} ${spec.models.length ? 'mt-2' : ''}`}
                  value={customModel}
                  onChange={(event) => setCustomModel(event.target.value)}
                  placeholder="填写模型 ID，例如 glm-4.6 或 ep-2026…"
                  spellCheck={false}
                />
              )}
            </label>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1 block text-[11.5px] text-dim">上下文窗口（tokens）</span>
                <input
                  className={inputClass}
                  value={contextWindow}
                  onChange={(event) => setContextWindow(event.target.value.replace(/[^0-9]/g, ''))}
                  placeholder="例如 131072"
                  inputMode="numeric"
                  spellCheck={false}
                />
              </label>
              {spec.supports_reasoning && (
                <label className="block">
                  <span className="mb-1 block text-[11.5px] text-dim">推理强度</span>
                  <select
                    className={inputClass}
                    value={reasoningEffort}
                    onChange={(event) => setReasoningEffort(event.target.value)}
                  >
                    <option value="">默认</option>
                    <option value="low">低 · 响应更快</option>
                    <option value="medium">中</option>
                    <option value="high">高 · 深度思考</option>
                  </select>
                </label>
              )}
            </div>

            <label className="flex items-center gap-2 text-[12px] text-dim">
              <input
                type="checkbox"
                checked={makeDefault}
                onChange={(event) => setMakeDefault(event.target.checked)}
              />
              设为默认厂商（新对话使用）
            </label>

            {feedback && (
              <p className={`flex items-start gap-1.5 text-[11.5px] ${
                feedback.ok ? 'text-ok' : 'text-err'
              }`}>
                {feedback.ok
                  ? <CheckCircle2 size={13} className="mt-0.5 shrink-0" />
                  : <XCircle size={13} className="mt-0.5 shrink-0" />}
                <span className="break-all">{feedback.text}</span>
              </p>
            )}

            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Button variant="primary" size="sm" disabled={busy} onClick={() => void submit('save')}>
                {busy ? <Spinner /> : <KeyRound size={12} />} 保存配置
              </Button>
              <Button size="sm" disabled={testing} onClick={() => void submit('test')}>
                {testing ? <Spinner /> : <Zap size={12} />} 测试连接
              </Button>
              <Button size="sm" className="ml-auto" onClick={close}>取消</Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={Boolean(confirmDelete)}
        onClose={() => setConfirmDelete(null)}
        title="删除厂商配置"
        width="max-w-sm"
      >
        <p className="text-[12.5px] leading-relaxed text-dim">
          删除后，该厂商的 Key 与模型设置会被移除；如果它是默认厂商，会自动切换到最近使用的另一家。
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" onClick={() => setConfirmDelete(null)}>取消</Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => {
              const provider = confirmDelete
              setConfirmDelete(null)
              if (provider) runAction(deleteCredential(provider))
            }}
          >
            确认删除
          </Button>
        </div>
      </Modal>
    </div>
  )
}
