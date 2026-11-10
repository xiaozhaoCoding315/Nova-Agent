import clsx from 'clsx'
import { Check, ChevronDown, ChevronRight, Loader2, Plus, Search, Star, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ProviderIcon } from '../components/ProviderIcon'
import { ApiError } from '../lib/api'
import { useFocusTrap } from '../lib/focus'
import {
  providerSupportsReasoning, providerSupportsTemperature, sanitizeOverrides,
} from '../lib/overrides'
import type { LlmOverrides, LlmProvider, LlmSettings } from '../lib/types'
import { inputClass } from '../lib/ui'
import { useChat } from '../stores/chat'
import { useLlm } from '../stores/llm'

const REASONING_OPTIONS: { value: '' | 'low' | 'medium' | 'high'; label: string }[] = [
  { value: '', label: '自动' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
]

/** 「自动」是开关，不是一档；三档强度单独成组，语义与滑块/分段控件一致。 */
const EFFORT_STEPS: { value: 'low' | 'medium' | 'high'; label: string }[] = [
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
]

const CONTEXT_PRESETS = [32_000, 64_000, 128_000, 200_000]

/** 低于该值的上下文窗口没有实际意义，直接拒绝。 */
const MIN_CONTEXT_WINDOW = 2048

const optionClass = (selected: boolean, disabled = false) => clsx(
  'rounded-sm border px-1.5 py-1 text-xs transition-colors',
  selected
    ? 'border-accent/50 bg-accentSoft/40 text-ink'
    : 'border-edge text-dim hover:border-accent/30 hover:text-ink',
  disabled && 'cursor-not-allowed opacity-40 hover:border-edge hover:text-dim',
)

function formatWindow(value: number): string {
  return value >= 1000 ? `${Math.round(value / 1000)}k` : String(value)
}

export function ModelPicker({
  open,
  onClose,
  settings,
  value,
  onChange,
  onSetDefault,
  onConfigure,
  reasoningCleared = false,
  placement = 'above',
}: {
  open: boolean
  onClose: () => void
  settings: LlmSettings | null
  value: LlmOverrides
  onChange: (patch: LlmOverrides) => void
  onSetDefault: () => Promise<void>
  onConfigure: () => void
  /** 会话持久化过 reasoning_effort: "" sentinel，自动不会再继承默认。 */
  reasoningCleared?: boolean
  /** 输入框内的 popover 向上展开；项目头里的向下展开。 */
  placement?: 'above' | 'below'
}) {
  const [query, setQuery] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [customContext, setCustomContext] = useState('')
  const [contextError, setContextError] = useState<string | null>(null)
  const [tempDraft, setTempDraft] = useState(1)
  /** 「更多参数」默认收起：首屏只留厂商 / 模型 / 推理强度。 */
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [savingDefault, setSavingDefault] = useState(false)
  const [defaultFeedback, setDefaultFeedback] = useState<{ ok: boolean; text: string } | null>(null)
  const feedbackTimer = useRef<number | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  // 浮层自带全屏遮罩，是模态的：Tab 关在里面，关闭后焦点回到触发按钮。
  useFocusTrap(panelRef, open)

  const providers = settings?.providers ?? []
  const credentials = settings?.credentials ?? []
  const credentialMap = useMemo(
    () => new Map(credentials.map((credential) => [credential.provider, credential])),
    [credentials],
  )
  const defaultCredential = credentials.find((credential) => credential.is_default) ?? credentials[0] ?? null
  const activeProviderId = value.provider ?? defaultCredential?.provider ?? settings?.provider ?? null
  const activeProvider = providers.find((provider) => provider.id === activeProviderId) ?? null
  const activeCredential = activeProviderId ? credentialMap.get(activeProviderId) ?? null : null

  const orderedProviders = useMemo(() => {
    const configured = credentials
      .map((credential) => providers.find((provider) => provider.id === credential.provider))
      .filter((provider): provider is LlmProvider => Boolean(provider))
    const rest = providers.filter((provider) => !credentialMap.has(provider.id))
    return [...configured, ...rest]
  }, [credentials, providers, credentialMap])

  const currentModel = value.model ?? activeCredential?.model ?? null
  const currentEffort = value.reasoning_effort ?? ''
  const currentContext = value.context_window ?? null
  const maxWindow = activeProvider?.context_window && activeProvider.context_window > 0
    ? activeProvider.context_window
    : null
  /** 「自动」实际继承的默认值，仅作次要说明展示，不参与 aria-pressed。 */
  const defaultEffort = activeCredential?.reasoning_effort ?? ''
  const defaultEffortLabel = REASONING_OPTIONS.find(
    (option) => option.value !== '' && option.value === defaultEffort,
  )?.label ?? null
  const defaultContextWindow = activeCredential?.context_window != null
    && activeCredential.context_window > 0
    ? activeCredential.context_window
    : null

  const modelChoices = useMemo(() => {
    const models = activeProvider?.models ?? []
    const extra = currentModel && !models.includes(currentModel) ? [currentModel] : []
    const all = [...extra, ...models]
    const needle = query.trim().toLowerCase()
    return needle ? all.filter((model) => model.toLowerCase().includes(needle)) : all
  }, [activeProvider, currentModel, query])

  useEffect(() => {
    if (!open) return
    setQuery('')
    setCustomModel('')
    setCustomContext(
      currentContext != null && !CONTEXT_PRESETS.includes(currentContext) ? String(currentContext) : '',
    )
    setContextError(null)
    setTempDraft(value.temperature ?? 1)
    setDefaultFeedback(null)
    // 会话里已经改过上下文或温度时，直接展开，别让用户以为设置丢了。
    setAdvancedOpen(value.context_window != null || value.temperature != null)
    if (feedbackTimer.current != null) {
      window.clearTimeout(feedbackTimer.current)
      feedbackTimer.current = null
    }
    // 只在打开时重置；打开期间的选择应立即可见。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    setTempDraft(value.temperature ?? 1)
  }, [value.temperature])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      event.preventDefault()
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  useEffect(() => () => {
    if (feedbackTimer.current != null) window.clearTimeout(feedbackTimer.current)
  }, [])

  if (!open) return null

  const selectProvider = (provider: LlmProvider) => {
    const credential = credentialMap.get(provider.id)
    if (!credential) return
    setContextError(null)
    const nextModel = credential.model || provider.models[0] || null
    // 新厂商不支持的参数立即清空、上下文收敛到新上限，UI 与发送保持一致。
    const sanitized = sanitizeOverrides(
      {
        provider: provider.id,
        model: nextModel,
        reasoning_effort: value.reasoning_effort,
        context_window: value.context_window,
        temperature: value.temperature,
      },
      provider,
    )
    onChange({
      provider: provider.id,
      model: nextModel,
      reasoning_effort: sanitized.reasoning_effort ?? null,
      context_window: sanitized.context_window ?? null,
      temperature: sanitized.temperature ?? null,
    })
  }

  const commitCustomModel = () => {
    const next = customModel.trim()
    if (!next) return
    onChange({ model: next })
    setCustomModel('')
  }

  const commitContext = () => {
    const parsed = Number(customContext.replace(/[^0-9]/g, ''))
    if (!parsed) return
    const capped = maxWindow != null ? Math.min(parsed, maxWindow) : parsed
    if (capped < MIN_CONTEXT_WINDOW) {
      setContextError(`上下文至少需 ${MIN_CONTEXT_WINDOW} tokens`)
      return
    }
    setContextError(null)
    onChange({ context_window: capped })
    setCustomContext(String(capped))
  }

  const commitTemperature = () => {
    const next = Math.round(tempDraft * 10) / 10
    if (next !== value.temperature) onChange({ temperature: next })
  }

  const handleSetDefault = async () => {
    setSavingDefault(true)
    setDefaultFeedback(null)
    try {
      await onSetDefault()
      setDefaultFeedback({ ok: true, text: '已设为默认' })
      if (feedbackTimer.current != null) window.clearTimeout(feedbackTimer.current)
      feedbackTimer.current = window.setTimeout(() => {
        setDefaultFeedback(null)
        feedbackTimer.current = null
      }, 2000)
    } catch (err) {
      setDefaultFeedback({
        ok: false,
        text: err instanceof ApiError ? err.message : '设为默认失败',
      })
    } finally {
      setSavingDefault(false)
    }
  }

  const handleConfigure = () => {
    onClose()
    onConfigure()
  }

  const canSetDefault = Boolean(activeCredential && currentModel)

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label="模型选择"
        tabIndex={-1}
        className={clsx(
          'z-50 w-[360px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-edge bg-panel shadow-pop outline-none',
          placement === 'below'
            ? 'fixed inset-x-2 top-12 sm:absolute sm:inset-x-auto sm:left-0 sm:top-full sm:mt-1.5'
            : 'absolute bottom-full right-0 mb-2',
        )}
      >
        <div className="flex items-center justify-between border-b border-edge/70 px-3 py-2">
          <p className="text-sm font-medium text-ink">
            模型 <span className="font-mono text-2xs uppercase tracking-[0.12em] text-faint">仅本会话</span>
          </p>
          <button
            type="button"
            onClick={onClose}
            className="flex h-5 w-5 items-center justify-center rounded-sm text-dim transition-colors hover:bg-raised hover:text-ink"
            aria-label="关闭模型选择"
          >
            <X size={12} />
          </button>
        </div>

        <div className="max-h-[calc(100vh-190px)] space-y-3 overflow-y-auto px-3 py-2.5">
          <section>
            <p className="mb-1.5 text-2xs uppercase tracking-[0.12em] text-faint">厂商</p>
            <div className="max-h-52 space-y-px overflow-y-auto pr-0.5">
              {orderedProviders.length === 0 && (
                <p className="px-1 py-1 text-xs text-dim">还没有可用的厂商配置。</p>
              )}
              {orderedProviders.map((provider) => {
                const credential = credentialMap.get(provider.id)
                if (!credential) {
                  return (
                    <button
                      key={provider.id}
                      type="button"
                      onClick={onConfigure}
                      title={`${provider.label} 还没有保存 Key，点击配置`}
                      aria-label={`配置 ${provider.label}`}
                      className="flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-xs text-faint transition-colors hover:bg-raised hover:text-dim"
                    >
                      <ProviderIcon id={provider.id} size={13} className="shrink-0" />
                      <span className="min-w-0 flex-1 truncate">{provider.label}</span>
                      <Plus size={11} className="shrink-0" />
                    </button>
                  )
                }
                const selected = provider.id === activeProviderId
                return (
                  <button
                    key={provider.id}
                    type="button"
                    onClick={() => selectProvider(provider)}
                    aria-pressed={selected}
                    title={`${provider.label} · ${credential.model}`}
                    className={clsx(
                      'flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left text-xs transition-colors',
                      selected
                        ? 'bg-accentSoft/40 text-ink'
                        : 'text-dim hover:bg-raised hover:text-ink',
                    )}
                  >
                    <ProviderIcon
                      id={provider.id}
                      size={13}
                      className={selected ? 'shrink-0 text-accent' : 'shrink-0 text-faint'}
                    />
                    <span className="min-w-0 flex-1 truncate">{provider.label}</span>
                    <span className="shrink-0 font-mono text-2xs text-faint">{credential.model}</span>
                    {selected && <Check size={11} className="shrink-0 text-accent" />}
                  </button>
                )
              })}
            </div>
          </section>

          <section>
            <div className="mb-1.5 flex items-center justify-between">
              <p className="text-2xs uppercase tracking-[0.12em] text-faint">模型</p>
              {activeProvider && (
                <span className="font-mono text-2xs text-faint">{activeProvider.label}</span>
              )}
            </div>
            {activeProvider && activeCredential ? (
              <>
                <label className="relative block">
                  <Search
                    size={12}
                    className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-faint"
                  />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="搜索模型"
                    aria-label="搜索模型"
                    spellCheck={false}
                    className={clsx(inputClass, 'w-full pl-7')}
                  />
                </label>
                <div className="mt-1.5 max-h-36 space-y-0.5 overflow-y-auto pr-0.5">
                  {modelChoices.length === 0 && (
                    <p className="px-1 py-1 text-xs text-dim">没有匹配的模型。</p>
                  )}
                  {modelChoices.map((model) => {
                    const selected = model === currentModel
                    return (
                      <button
                        key={model}
                        type="button"
                        onClick={() => onChange({ model })}
                        aria-pressed={selected}
                        className={clsx(
                          'flex w-full items-center gap-2 rounded-sm px-2 py-1 text-left font-mono text-xs transition-colors',
                          selected
                            ? 'bg-accentSoft/40 text-ink'
                            : 'text-dim hover:bg-raised hover:text-ink',
                        )}
                      >
                        <span className="min-w-0 flex-1 truncate">{model}</span>
                        {selected && <Check size={11} className="shrink-0 text-accent" />}
                      </button>
                    )
                  })}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <input
                    value={customModel}
                    onChange={(event) => setCustomModel(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key !== 'Enter') return
                      event.preventDefault()
                      commitCustomModel()
                    }}
                    placeholder="自定义模型 ID"
                    aria-label="自定义模型 ID"
                    spellCheck={false}
                    className={clsx(inputClass, 'min-w-0 flex-1 font-mono')}
                  />
                  <button
                    type="button"
                    onClick={commitCustomModel}
                    disabled={!customModel.trim()}
                    className="shrink-0 rounded-sm border border-edge px-2 py-1 text-xs text-dim transition-colors hover:border-accent/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    使用
                  </button>
                </div>
              </>
            ) : (
              <p className="px-1 py-1 text-xs leading-relaxed text-dim">
                {activeProvider
                  ? '这家厂商还没有保存 Key，先配置后再选择模型。'
                  : '先在上面选择一家已配置的厂商。'}
              </p>
            )}
          </section>

          {activeProvider && providerSupportsReasoning(activeProvider) && (
            <section>
              <div className="mb-1.5 flex items-center justify-between">
                <p className="text-2xs uppercase tracking-[0.12em] text-faint">推理强度</p>
                <button
                  type="button"
                  onClick={() => onChange({ reasoning_effort: '' })}
                  aria-pressed={currentEffort === ''}
                  className={clsx(
                    'rounded-full px-1.5 py-0.5 text-2xs transition-colors',
                    currentEffort === ''
                      ? 'bg-accentSoft/40 text-accent'
                      : 'text-faint hover:bg-raised hover:text-dim',
                  )}
                  title="不覆盖厂商默认，跟随凭据里的设置"
                >
                  自动
                </button>
              </div>
              <div
                role="radiogroup"
                aria-label="推理强度"
                className={clsx(
                  'grid grid-cols-3 gap-1 transition-opacity',
                  currentEffort === '' && 'opacity-50',
                )}
              >
                {EFFORT_STEPS.map((option) => {
                  const active = currentEffort === option.value
                  return (
                    <button
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      onClick={() => onChange({ reasoning_effort: option.value })}
                      className={clsx(
                        'rounded-sm border py-1 text-xs transition-colors',
                        active
                          ? 'border-accent/50 bg-accentSoft/40 text-ink'
                          : 'border-edge text-dim hover:border-accent/30 hover:text-ink',
                      )}
                    >
                      {option.label}
                    </button>
                  )
                })}
              </div>
              {currentEffort === '' && (
                reasoningCleared ? (
                  <p className="mt-1 text-2xs text-dim">已关闭（不继承默认）</p>
                ) : defaultEffortLabel ? (
                  <p className="mt-1 text-2xs text-faint">自动（默认 {defaultEffortLabel}）</p>
                ) : (
                  <p className="mt-1 text-2xs text-faint">自动：跟随凭据里的默认强度</p>
                )
              )}
            </section>
          )}

          {activeProvider && (
            <section>
              <button
                type="button"
                onClick={() => setAdvancedOpen((value) => !value)}
                aria-expanded={advancedOpen}
                className="flex w-full items-center gap-1.5 rounded-sm py-0.5 text-left transition-colors hover:text-ink"
              >
                {advancedOpen
                  ? <ChevronDown size={11} className="shrink-0 text-faint" />
                  : <ChevronRight size={11} className="shrink-0 text-faint" />}
                <span className="text-2xs uppercase tracking-[0.12em] text-faint">更多参数</span>
                {!advancedOpen && (
                  <span className="ml-auto truncate font-mono text-2xs text-faint">
                    {currentContext != null ? formatWindow(currentContext) : '上下文自动'}
                    {value.temperature != null ? ` · T ${value.temperature.toFixed(1)}` : ''}
                  </span>
                )}
              </button>
            </section>
          )}

          {activeProvider && advancedOpen && (
            <section>
              <div className="mb-1.5 flex items-center justify-between">
                <p className="text-2xs uppercase tracking-[0.12em] text-faint">上下文窗口</p>
                {maxWindow != null && (
                  <span className="font-mono text-2xs text-faint">≤ {formatWindow(maxWindow)}</span>
                )}
              </div>
              <div className="flex flex-wrap gap-1">
                <button
                  type="button"
                  aria-pressed={currentContext == null}
                  onClick={() => {
                    setContextError(null)
                    onChange({ context_window: null })
                  }}
                  className={optionClass(currentContext == null)}
                >
                  自动
                </button>
                {CONTEXT_PRESETS.map((preset) => (
                  <button
                    key={preset}
                    type="button"
                    aria-pressed={currentContext === preset}
                    disabled={maxWindow != null && preset > maxWindow}
                    onClick={() => {
                      setContextError(null)
                      onChange({ context_window: preset })
                    }}
                    className={optionClass(
                      currentContext === preset,
                      maxWindow != null && preset > maxWindow,
                    )}
                  >
                    {formatWindow(preset)}
                  </button>
                ))}
              </div>
              {currentContext == null && defaultContextWindow != null && (
                <p className="mt-1 text-2xs text-faint">
                  自动（默认 {formatWindow(defaultContextWindow)}）
                </p>
              )}
              <div className="mt-1.5 flex items-center gap-1.5">
                <input
                  value={customContext}
                  onChange={(event) => {
                    setContextError(null)
                    setCustomContext(event.target.value.replace(/[^0-9]/g, ''))
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== 'Enter') return
                    event.preventDefault()
                    commitContext()
                  }}
                  inputMode="numeric"
                  placeholder="自定义 tokens"
                  aria-label="自定义上下文窗口"
                  spellCheck={false}
                  className={clsx(inputClass, 'min-w-0 flex-1 font-mono')}
                />
                <button
                  type="button"
                  onClick={commitContext}
                  disabled={!customContext}
                  className="shrink-0 rounded-sm border border-edge px-2 py-1 text-xs text-dim transition-colors hover:border-accent/40 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
                >
                  使用
                </button>
              </div>
              {contextError && (
                <p className="mt-1 text-2xs text-err">{contextError}</p>
              )}
            </section>
          )}

          {activeProvider && advancedOpen && providerSupportsTemperature(activeProvider) && (
            <section>
              <div className="mb-1 flex items-center justify-between">
                <p className="text-2xs uppercase tracking-[0.12em] text-faint">温度</p>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    aria-pressed={value.temperature == null}
                    onClick={() => onChange({ temperature: null })}
                    className={optionClass(value.temperature == null)}
                  >
                    自动
                  </button>
                  <span className="font-mono text-2xs text-faint">
                    {value.temperature == null ? '默认' : value.temperature.toFixed(1)}
                  </span>
                </div>
              </div>
              <input
                type="range"
                min={0}
                max={2}
                step={0.1}
                value={tempDraft}
                onChange={(event) => setTempDraft(Number(event.target.value))}
                onPointerUp={commitTemperature}
                onKeyUp={commitTemperature}
                onBlur={commitTemperature}
                aria-label="温度"
                className="w-full accent-accent"
              />
              <div className="flex justify-between font-mono text-2xs text-faint">
                <span>0</span>
                <span>2</span>
              </div>
            </section>
          )}
        </div>

        <div className="flex items-center gap-1.5 border-t border-edge/70 px-3 py-2">
          <button
            type="button"
            onClick={() => void handleSetDefault()}
            disabled={!canSetDefault || savingDefault}
            className="flex items-center gap-1 rounded-md border border-edge bg-raised px-2 py-1 text-xs text-ink transition-colors hover:border-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {savingDefault
              ? <Loader2 size={11} className="animate-spin" />
              : <Star size={11} className="text-accent" />}
            设为默认
          </button>
          <button
            type="button"
            onClick={handleConfigure}
            className="rounded-md px-2 py-1 text-xs text-dim transition-colors hover:text-ink"
          >
            管理密钥
          </button>
          {defaultFeedback && (
            <span className={clsx('ml-auto text-2xs', defaultFeedback.ok ? 'text-ok' : 'text-err')}>
              {defaultFeedback.text}
            </span>
          )}
        </div>
      </div>
    </>
  )
}

/** 把 store 的会话参数与默认 credential 合成 ModelPicker 需要的 props。 */
export function useModelPicker(): {
  settings: LlmSettings | null
  value: LlmOverrides
  onChange: (patch: LlmOverrides) => void
  onSetDefault: () => Promise<void>
  reasoningCleared: boolean
} {
  const settings = useLlm((state) => state.settings)
  const saveCredential = useLlm((state) => state.saveCredential)
  const provider = useChat((state) => state.provider)
  const model = useChat((state) => state.model)
  const reasoningEffort = useChat((state) => state.reasoningEffort)
  const reasoningCleared = useChat((state) => state.reasoningCleared)
  const contextWindow = useChat((state) => state.contextWindow)
  const temperature = useChat((state) => state.temperature)
  const applyOverrides = useChat((state) => state.applyOverrides)

  const credentials = settings?.credentials ?? []
  const defaultCredential = credentials.find((credential) => credential.is_default) ?? credentials[0] ?? null
  const activeProviderId = provider ?? defaultCredential?.provider ?? settings?.provider ?? null
  const activeCredential = credentials.find((credential) => credential.provider === activeProviderId) ?? null
  const activeSpec = settings?.providers.find((item) => item.id === activeProviderId) ?? null

  const value: LlmOverrides = {
    provider: activeProviderId,
    // 模型没有「自动」档，保留 credential 回退以便 chip 显示生效模型。
    model: model ?? activeCredential?.model ?? settings?.model ?? null,
    // 推理与上下文必须用 store 原值：'' / null 才是「自动」，不能被默认值冒充成会话覆盖。
    reasoning_effort: reasoningEffort,
    context_window: contextWindow ?? null,
    temperature,
  }

  const onChange = (patch: LlmOverrides) => {
    void applyOverrides(patch)
  }

  const onSetDefault = async () => {
    if (!activeProviderId) throw new Error('请先选择厂商')
    if (!activeCredential) throw new Error('请先配置该厂商的 Key')
    if (!value.model) throw new Error('请先选择模型')
    // 「自动」时按默认 credential 的生效值保存，避免写空值或 0；
    // 厂商不支持推理时不保存，避免写入无效值。
    const reasoning = activeSpec && !providerSupportsReasoning(activeSpec)
      ? ''
      : reasoningEffort
        || (activeCredential.reasoning_effort as LlmOverrides['reasoning_effort'])
        || ''
    // 上下文不做厂商上限收敛：自定义端点可能配置了高于 preset 的上限，
    // 与 ModelSettings 保持一致；只保证后端 2048 下界，空值按 0（自动）保存。
    const rawContext = contextWindow ?? activeCredential.context_window ?? null
    const contextForDefault = rawContext != null && rawContext > 0 && rawContext < MIN_CONTEXT_WINDOW
      ? MIN_CONTEXT_WINDOW
      : rawContext ?? 0
    await saveCredential(activeProviderId, {
      model: value.model,
      // 后端会拿 preset 覆盖缺失的 base_url：unlocked 厂商必须带回已保存的地址。
      base_url: activeSpec?.base_url_locked ? null : activeCredential.base_url ?? null,
      context_window: contextForDefault,
      reasoning_effort: reasoning,
      is_default: true,
    })
  }

  return { settings, value, onChange, onSetDefault, reasoningCleared }
}
