import clsx from 'clsx'
import {
  Activity, Blocks, Brain, Cpu, FolderOpen, KeyRound, RefreshCw, Server, Settings, TrendingUp, Users, X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Health } from '../lib/types'
import { useAuth } from '../stores/auth'
import { useLlm } from '../stores/llm'
import { useMode } from '../stores/mode'
import { AccountSection } from './sections/AccountSection'
import { AdminSection } from './sections/AdminSection'
import { ExtensionsSection } from './sections/ExtensionsSection'
import { FilesSection } from './sections/FilesSection'
import { MemorySection } from './sections/MemorySection'
import { MetricsSection } from './sections/MetricsSection'
import { ModelSection } from './sections/ModelSection'
import { SystemSection } from './sections/SystemSection'
import { UsageSection } from './sections/UsageSection'

export type SettingsSection =
  | 'model' | 'usage' | 'metrics' | 'files' | 'memory' | 'extensions' | 'system'
  | 'account' | 'admin'

const SECTIONS: { key: SettingsSection; label: string; icon: typeof Cpu }[] = [
  { key: 'model', label: '模型与密钥', icon: Cpu },
  { key: 'usage', label: '用量与配额', icon: Activity },
  { key: 'metrics', label: '交付指标', icon: TrendingUp },
  { key: 'files', label: '文件与存储', icon: FolderOpen },
  { key: 'memory', label: '长期记忆', icon: Brain },
  { key: 'extensions', label: '扩展与技能', icon: Blocks },
  { key: 'system', label: '系统状态', icon: Server },
  { key: 'account', label: '账号与安全', icon: KeyRound },
  { key: 'admin', label: '用户管理', icon: Users },
]

const DESCRIPTIONS: Record<SettingsSection, string> = {
  model: '配置你自己的模型服务商与 API Key；支持按会话切换模型。',
  usage: '用量、交付指标与运行状态。',
  metrics: '用量、交付指标与运行状态。',
  files: '聊天附件与手动上传的个人文件，计入存储配额。',
  memory: '用量、交付指标与运行状态。',
  extensions: '操作员预置的 MCP 工具与技能手册；只读展示，配置在部署目录完成。',
  system: '用量、交付指标与运行状态。',
  account: '个人资料、密码与会话安全。',
  admin: '管理系统账号、禁用账号与重置密码。',
}

export function SettingsDialog({
  open,
  section,
  onClose,
}: {
  open: boolean
  section?: SettingsSection
  onClose: () => void
}) {
  if (!open) return null
  return <SettingsDialogBody initialSection={section} onClose={onClose} />
}

function SettingsDialogBody({
  initialSection,
  onClose,
}: {
  initialSection?: SettingsSection
  onClose: () => void
}) {
  const user = useAuth((state) => state.user)
  const localMode = useMode((state) => state.mode?.local ?? false)
  const llmSettings = useLlm((state) => state.settings)
  const llmLoading = useLlm((state) => state.loading)
  const loadLlm = useLlm((state) => state.load)

  const sections = useMemo(() => SECTIONS.filter((item) => {
    if (localMode && (item.key === 'usage' || item.key === 'account' || item.key === 'admin')) {
      return false
    }
    return item.key !== 'admin' || user?.role === 'admin'
  }), [localMode, user?.role])

  const [section, setSection] = useState<SettingsSection>(() => (
    initialSection && sections.some((item) => item.key === initialSection) ? initialSection : 'model'
  ))
  const [health, setHealth] = useState<Health | null>(null)
  const [healthLoading, setHealthLoading] = useState(false)
  const [healthError, setHealthError] = useState<string | null>(null)
  const [metricsDays, setMetricsDays] = useState(7)
  const [refreshToken, setRefreshToken] = useState(0)
  const panelRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const loadHealth = async () => {
    setHealthLoading(true)
    try {
      setHealth(await api.status.health())
      setHealthError(null)
    } catch (err) {
      setHealthError(err instanceof ApiError ? err.message : '无法读取服务状态')
    } finally {
      setHealthLoading(false)
    }
  }

  // 打开时把焦点移入弹层，关闭后回到触发按钮（ProjectRail / 模型选择器等）。
  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    panelRef.current?.focus()
    return () => {
      const target = returnFocusRef.current
      if (target && document.contains(target)) target.focus()
    }
  }, [])

  // 只加载弹层外壳需要的数据（版本号）与模型配置；其他 section 按激活时各自加载。
  useEffect(() => {
    void loadHealth()
    void loadLlm()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 运行模式或角色变化后，若当前 section 已不可见则回到第一个可见项。
  useEffect(() => {
    if (!sections.some((item) => item.key === section)) {
      setSection(sections[0]?.key ?? 'model')
    }
  }, [sections, section])

  const active = sections.find((item) => item.key === section) ?? sections[0] ?? SECTIONS[0]

  const refresh = () => {
    if (section === 'model') {
      void loadLlm()
    } else if (section === 'system') {
      void loadHealth()
    } else if (section !== 'account') {
      setRefreshToken((value) => value + 1)
    }
  }

  const refreshing = section === 'model'
    ? llmLoading
    : section === 'system' ? healthLoading : false

  return (
    <div className="fixed inset-0 z-50 bg-black/60" onClick={onClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        tabIndex={-1}
        onClick={(event) => event.stopPropagation()}
        className="mx-auto mt-[6vh] flex h-[84vh] w-[min(980px,94vw)] flex-col overflow-hidden rounded-lg border border-edge bg-panel shadow-pop outline-none max-md:mt-0 max-md:h-full max-md:w-full max-md:max-w-none max-md:rounded-none max-md:border-0"
      >
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-edge px-4">
          <Settings size={14} className="shrink-0 text-accent" />
          <h2 id="settings-title" className="font-mono text-sm font-medium uppercase tracking-[0.14em]">
            设置
          </h2>
          <span aria-hidden="true" className="text-faint">/</span>
          <span className="min-w-0 truncate text-sm text-dim">{active.label}</span>
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <button
              onClick={refresh}
              disabled={refreshing || section === 'account'}
              className="flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
              title="刷新"
              aria-label="刷新设置数据"
            >
              {refreshing ? <Spinner /> : <RefreshCw size={13} />}
            </button>
            <button
              onClick={onClose}
              className="flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
              title="关闭 · Esc"
              aria-label="关闭设置"
            >
              <X size={14} />
            </button>
          </div>
        </header>

        <nav
          aria-label="设置分区（移动端）"
          className="flex shrink-0 gap-1 overflow-x-auto border-b border-edge/70 px-3 py-2 md:hidden"
        >
          {sections.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setSection(key)}
              aria-current={section === key ? 'page' : undefined}
              className={clsx(
                'shrink-0 rounded-full border px-2.5 py-1 text-xs transition-colors duration-150',
                section === key
                  ? 'border-accent/60 bg-accentSoft/40 text-ink'
                  : 'border-edge text-dim hover:text-ink',
              )}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="flex min-h-0 flex-1">
          <nav
            aria-label="设置分区"
            className="hidden w-[200px] shrink-0 flex-col border-r border-edge/70 bg-base/20 p-2 md:flex"
          >
            <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
              {sections.map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  onClick={() => setSection(key)}
                  aria-current={section === key ? 'page' : undefined}
                  className={clsx(
                    'flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors duration-150',
                    section === key
                      ? 'bg-accentSoft/40 text-ink'
                      : 'text-dim hover:bg-raised hover:text-ink',
                  )}
                >
                  <Icon size={14} className={clsx('shrink-0', section === key && 'text-accent')} />
                  <span className="truncate">{label}</span>
                </button>
              ))}
            </div>
            <p className="px-2 pb-1 pt-3 font-mono text-2xs text-faint">
              v{health?.version ?? '2.0.0'} · {user?.display_name || user?.username || '本地用户'}
            </p>
          </nav>

          <div className="min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto max-w-3xl p-4 md:p-6">
              <p className="mb-4 text-xs leading-relaxed text-dim">{DESCRIPTIONS[active.key]}</p>
              {section === 'model' && (
                <ModelSection
                  settings={llmSettings}
                  loading={llmLoading}
                  onReload={() => void loadLlm()}
                />
              )}
              {section === 'usage' && <UsageSection refreshToken={refreshToken} />}
              {section === 'metrics' && (
                <MetricsSection
                  refreshToken={refreshToken}
                  days={metricsDays}
                  onDaysChange={setMetricsDays}
                />
              )}
              {section === 'files' && <FilesSection key={refreshToken} />}
              {section === 'memory' && <MemorySection refreshToken={refreshToken} />}
              {section === 'extensions' && <ExtensionsSection refreshToken={refreshToken} />}
              {section === 'system' && (
                <SystemSection health={health} loading={healthLoading} error={healthError} />
              )}
              {section === 'account' && <AccountSection />}
              {section === 'admin' && user?.role === 'admin' && (
                <AdminSection key={refreshToken} />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
