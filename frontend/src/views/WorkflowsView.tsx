import clsx from 'clsx'
import { ArrowLeft, FlaskConical, GitPullRequest, Info, Moon } from 'lucide-react'
import { useState } from 'react'
import { NightQueuePanel } from '../components/NightQueuePanel'
import { useRepos } from '../stores/repos'
import { ChangesView } from './ChangesView'
import { TasksView } from './TasksView'

export type WorkflowTab = 'changes' | 'tasks'

const TABS: { key: WorkflowTab; label: string; hint: string; icon: typeof GitPullRequest }[] = [
  {
    key: 'changes',
    label: '变更',
    hint: '跨文件功能 / 重构',
    icon: GitPullRequest,
  },
  {
    key: 'tasks',
    label: '修复任务',
    hint: '单个 Bug 红绿修复',
    icon: FlaskConical,
  },
]

export function WorkflowsView({
  initialTab = 'changes',
  initialRepoId,
  onBackToChat,
}: {
  initialTab?: WorkflowTab
  initialRepoId?: string
  onBackToChat?: () => void
}) {
  const [tab, setTab] = useState<WorkflowTab>(initialTab)
  const [nightOpen, setNightOpen] = useState(false)
  const { repos } = useRepos()

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-edge/80 bg-panel/25 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex rounded-lg border border-edge/80 bg-base/40 p-0.5">
            {TABS.map(({ key, label, hint, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={clsx(
                  'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] transition-colors',
                  tab === key ? 'bg-accentSoft/45 text-ink' : 'text-dim hover:text-ink',
                )}
              >
                <Icon size={13} className={tab === key ? 'text-accent' : ''} />
                {label}
                <span className="hidden text-[10px] text-dim/70 sm:inline">{hint}</span>
              </button>
            ))}
          </div>
          <button
            onClick={() => setNightOpen(!nightOpen)}
            className={clsx(
              'flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors',
              nightOpen
                ? 'border-accent/60 bg-accentSoft/30 text-ink'
                : 'border-edge/80 text-dim hover:text-ink',
            )}
            title="睡前排队，夜间窗口内自动执行，早上看报告批准"
          >
            <Moon size={12} className={nightOpen ? 'text-accent' : ''} />
            夜间队列
          </button>
          {onBackToChat && (
            <button
              onClick={onBackToChat}
              className="ml-auto flex items-center gap-1 rounded-lg border border-edge/80 px-2.5 py-1.5 text-[11px] text-dim transition-colors hover:text-ink"
            >
              <ArrowLeft size={12} /> 回到对话
            </button>
          )}
        </div>

        <div className="mt-2 flex items-start gap-2 rounded-lg border border-edge/70 bg-base/35 px-3 py-2 text-[11.5px] leading-relaxed text-dim">
          <Info size={13} className="mt-0.5 shrink-0 text-accent/80" />
          <span>
            {tab === 'changes'
              ? '适合跨多个文件的新功能或重构：先冻结 SPEC 与验收，再拆任务逐个过 Gate，最后统一 diff 审查并应用。'
              : '适合已经定位的单个 Bug：先在沙箱写失败测试复现，再给最小补丁并跑到通过，审查后批准写入。'}
            <span className="ml-1 text-dim/70">
              与对话的区别：对话里「完成」由模型自己判断，一轮最多 5 次工具调用，适合问答和小改动；
              工作流是确定性流水线——每个任务必须真实跑过编译/测试 Gate（失败自动回喂修复，最多 3 次）、
              只读审查对照 SPEC 范围把关、批准后切独立分支写入并可回滚。
              改动越复杂，越需要用工作流而不是更长的对话。
            </span>
          </span>
        </div>
      </div>

      {nightOpen && (
        <div className="max-h-[45%] shrink-0 overflow-y-auto px-4 py-3">
          <NightQueuePanel repos={repos} />
        </div>
      )}

      <div className="min-h-0 flex-1">
        {tab === 'changes'
          ? <ChangesView initialRepoId={initialRepoId} />
          : <TasksView initialRepoId={initialRepoId} />}
      </div>
    </div>
  )
}
