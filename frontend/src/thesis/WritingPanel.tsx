import clsx from 'clsx'
import {
  BookOpenCheck, FolderOpen, Link2, Loader2, MessageSquareQuote, Save, Unlink,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { LocalFolderDialog } from '../components/LocalFolderDialog'
import { Badge, Button, Modal, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Repo, ThesisProjectDetail } from '../lib/types'
import { useMode } from '../stores/mode'
import { useThesis } from '../stores/thesis'

const WRITING_PROMPTS = [
  {
    title: '梳理项目',
    body: '先读一遍关联工程项目的结构和关键文件，用一段话说明这个项目做了什么、技术栈和主要模块，并列出可以写进论文的证据（文件路径与行号）。',
  },
  {
    title: '生成提纲',
    body: '根据项目实现给出论文提纲（到二级标题），每章标注对应的项目模块或证据；提纲要符合我的学位层次和模板要求。',
  },
  {
    title: '起草系统设计',
    body: '根据项目实现，起草「系统设计」章节初稿：架构、模块划分、数据流与关键接口。技术事实必须引用具体文件路径，参考文献只用我已导入的条目，并标注「AI 草稿，需本人核对」。',
  },
  {
    title: '论文与项目对照',
    body: '检查论文与项目是否一致：哪些实现没有写进论文，哪些论文描述在代码里找不到依据。按「缺证据 / 描述不符 / 建议补充」三类列出。',
  },
]

export function WritingPanel({ project }: { project: ThesisProjectDetail }) {
  const localMode = useMode((state) => state.mode?.local ?? false)
  const updateProject = useThesis((state) => state.updateProject)
  const setChatSeed = useThesis((state) => state.setChatSeed)
  const error = useThesis((state) => state.error)

  const [repos, setRepos] = useState<Repo[]>([])
  const [loadingRepos, setLoadingRepos] = useState(false)
  const [linkOpen, setLinkOpen] = useState(false)
  const [folderOpen, setFolderOpen] = useState(false)
  const [selectedRepo, setSelectedRepo] = useState('')
  const [saving, setSaving] = useState(false)
  const [notes, setNotes] = useState(project.source_notes ?? '')
  const [localError, setLocalError] = useState<string | null>(null)

  useEffect(() => {
    setNotes(project.source_notes ?? '')
  }, [project.id, project.source_notes])

  const loadRepos = async () => {
    setLoadingRepos(true)
    try {
      setRepos(await api.repos.list())
    } catch (err) {
      setLocalError(err instanceof ApiError ? err.message : '加载项目列表失败')
    } finally {
      setLoadingRepos(false)
    }
  }

  useEffect(() => {
    void loadRepos()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (linkOpen && repos.length === 0) void loadRepos()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [linkOpen])

  const linkedRepo = useMemo(
    () => repos.find((repo) => repo.id === project.source_repo_id) ?? null,
    [repos, project.source_repo_id],
  )
  const notesDirty = notes !== (project.source_notes ?? '')

  const saveNotes = async () => {
    setSaving(true)
    setLocalError(null)
    try {
      await updateProject({ source_notes: notes })
    } catch {
      /* store surfaces the error */
    } finally {
      setSaving(false)
    }
  }

  const linkRepo = async () => {
    if (!selectedRepo) return
    setSaving(true)
    setLocalError(null)
    try {
      await updateProject({ source_repo_id: selectedRepo })
      setLinkOpen(false)
      setSelectedRepo('')
    } catch (err) {
      setLocalError(err instanceof ApiError ? err.message : '关联项目失败')
    } finally {
      setSaving(false)
    }
  }

  const unlinkRepo = async () => {
    setSaving(true)
    setLocalError(null)
    try {
      await updateProject({ source_repo_id: '' })
    } catch (err) {
      setLocalError(err instanceof ApiError ? err.message : '取消关联失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-4 space-y-4">
      <section className="rounded-lg border border-edge bg-panel/40 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <BookOpenCheck size={18} className="mt-0.5 shrink-0 text-accent" />
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">工程项目</p>
              <p className="mt-1 text-xs leading-relaxed text-dim">
                关联毕业设计/课程项目的文件夹后，AI 可以像开发模式一样读取代码、检索实现，
                并在你授权的权限模式内修改本地文件。本地模式与开发模式使用同一套本机执行器。
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {project.source_repo_id ? (
                  <Badge tone="ok">
                    {linkedRepo ? linkedRepo.name : project.source_repo_id.slice(0, 8)}
                  </Badge>
                ) : (
                  <Badge tone="dim">未关联</Badge>
                )}
                {linkedRepo?.origin === 'local' && <Badge tone="warn">本地文件夹 · 无容器隔离</Badge>}
                {linkedRepo?.status && (
                  <span className="font-mono text-2xs text-faint">索引：{linkedRepo.status}</span>
                )}
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={() => setLinkOpen(true)}>
              <Link2 size={13} /> 关联已有项目
            </Button>
            <Button
              size="sm"
              onClick={() => setFolderOpen(true)}
              disabled={!localMode}
              title={localMode ? '打开本机文件夹' : '仅桌面客户端本地模式支持'}
            >
              <FolderOpen size={13} /> 打开本地文件夹
            </Button>
            {project.source_repo_id && (
              <Button size="sm" variant="danger" onClick={() => void unlinkRepo()} disabled={saving}>
                <Unlink size={13} /> 取消关联
              </Button>
            )}
          </div>
        </div>
        {!localMode && (
          <p className="mt-2 rounded-sm border border-edge bg-base/40 px-2.5 py-2 text-2xs leading-relaxed text-faint">
            「打开本地文件夹」只在桌面客户端本地模式可用；服务器模式请先创建或导入项目。
            桌面端本地模式与开发模式行为一致：原地读写、不复制文件、执行无容器隔离。
          </p>
        )}
      </section>

      <section className="rounded-lg border border-edge bg-panel/40 p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-sm font-medium text-ink">项目说明</p>
            <p className="mt-1 text-xs leading-relaxed text-dim">
              写给 AI 的项目背景：目标、功能、技术栈、你负责的部分、真实数据与限制。
              这些信息会随每次对话进入上下文，减少它猜测。
            </p>
          </div>
          <Button size="sm" onClick={() => void saveNotes()} disabled={saving || !notesDirty}>
            {saving ? <Spinner /> : <Save size={13} />} 保存
          </Button>
        </div>
        <textarea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          rows={4}
          maxLength={4000}
          placeholder="例：系统面向校内二手交易，后端 FastAPI，前端 React；我负责检索与权限模块；测试数据为 200 条模拟记录，无真实个人信息。"
          className="mt-3 w-full resize-y rounded-md border border-edge bg-base px-2.5 py-2 text-sm leading-relaxed text-ink outline-none focus:border-accent"
        />
        <p className="mt-1.5 flex items-center justify-between text-2xs text-faint">
          <span>只保存在你自己的论文项目里，随对话进入上下文。</span>
          <span className={notesDirty ? 'text-warn' : ''}>
            {notesDirty ? '有未保存的修改' : '已保存'}
          </span>
        </p>
      </section>

      <section className="rounded-lg border border-edge bg-panel/40 p-4">
        <div className="flex items-center gap-2">
          <MessageSquareQuote size={16} className="text-accent" />
          <p className="text-sm font-medium text-ink">写作快捷指令</p>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-dim">
          点击后填入右侧 AI 写作助手；它会先读项目再回答。生成的正文是草稿，需要你核对、改写并记入 AI 使用声明。
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {WRITING_PROMPTS.map((item) => (
            <button
              key={item.title}
              onClick={() => setChatSeed(item.body)}
              className="rounded-md border border-edge bg-base/40 px-3 py-2 text-left transition-colors duration-150 hover:border-accent/40"
            >
              <span className="text-xs font-medium text-ink">{item.title}</span>
              <span className="mt-0.5 block text-2xs leading-relaxed text-faint">
                {item.body.slice(0, 52)}…
              </span>
            </button>
          ))}
        </div>
        <p className="mt-3 text-2xs leading-relaxed text-faint">
          边界：不代写整篇论文、不伪造数据或引用、不提供降重或规避 AIGC 检测的方法；
          参考文献只使用「引用」页里已导入的条目。
        </p>
      </section>

      {(localError || error) && (
        <p className="rounded-md border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
          {localError || error}
        </p>
      )}

      <Modal open={linkOpen} onClose={() => setLinkOpen(false)} title="关联已有项目">
        <div className="space-y-3">
          <p className="text-sm leading-relaxed text-dim">
            选择你在 Nova 里已有的项目。AI 对话会以该项目作为论文的工程依据；
            本地文件夹项目可用「打开本地文件夹」直接登记。
          </p>
          {loadingRepos ? (
            <div className="flex items-center gap-2 text-xs text-faint"><Loader2 size={12} className="animate-spin" /> 加载项目…</div>
          ) : repos.length === 0 ? (
            <p className="rounded-md border border-dashed border-edge px-3 py-4 text-xs text-faint">
              还没有可用项目。请在开发模式导入 ZIP/Git 仓库，或用「打开本地文件夹」登记本机目录。
            </p>
          ) : (
            <div className="max-h-72 space-y-1.5 overflow-y-auto">
              {repos.map((repo) => (
                <button
                  key={repo.id}
                  onClick={() => setSelectedRepo(repo.id)}
                  className={clsx(
                    'flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-sm transition-colors duration-150',
                    selectedRepo === repo.id
                      ? 'border-accent/50 bg-accentSoft/30 text-ink'
                      : 'border-edge bg-base/40 text-dim hover:text-ink',
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate">{repo.name}</span>
                    <span className="block font-mono text-2xs text-faint">
                      {repo.origin === 'local' ? '本地文件夹' : repo.origin === 'git' ? 'Git' : 'ZIP'} · {repo.status}
                    </span>
                  </span>
                  {repo.id === project.source_repo_id && <Badge tone="ok">当前</Badge>}
                </button>
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => setLinkOpen(false)} disabled={saving}>取消</Button>
            <Button size="sm" variant="primary" onClick={() => void linkRepo()} disabled={!selectedRepo || saving}>
              {saving ? <Spinner /> : <Link2 size={12} />} 关联
            </Button>
          </div>
        </div>
      </Modal>

      <LocalFolderDialog
        open={folderOpen}
        onClose={() => setFolderOpen(false)}
        onOpened={(repo) => {
          setRepos((items) => [repo, ...items.filter((item) => item.id !== repo.id)])
          setFolderOpen(false)
          void updateProject({ source_repo_id: repo.id }).catch(() => {})
        }}
      />
    </div>
  )
}
