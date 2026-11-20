import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Button, Spinner } from '../components/common'
import type { ThesisDisclosureInput } from '../lib/types'
import { useThesis } from '../stores/thesis'

const INPUT_CLASS =
  'mt-1 w-full rounded-md border border-edge bg-base px-2.5 py-1.5 text-sm text-ink outline-none transition-colors duration-150 focus:border-accent'

const EMPTY_FORM: ThesisDisclosureInput = {
  tool: '',
  tool_version: '',
  stage: '',
  purpose: '',
  prompt: '',
  output: '',
  modified: true,
}

function formatDate(value?: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('zh-CN')
}

export function DisclosurePanel() {
  const { disclosures, busy, addDisclosure, removeDisclosure, exportPackage } = useThesis()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<ThesisDisclosureInput>(EMPTY_FORM)

  const update = (patch: Partial<ThesisDisclosureInput>) => {
    setForm((value) => ({ ...value, ...patch }))
  }

  const submit = async () => {
    if (!form.tool.trim()) return
    try {
      await addDisclosure(form)
      setForm(EMPTY_FORM)
      setOpen(false)
    } catch {
      /* store.error 已展示 */
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-ink">AI 使用声明</h2>
        <span className="text-2xs text-faint">{disclosures.length} 条记录</span>
        <Button size="sm" onClick={() => setOpen((value) => !value)}>
          <Plus size={13} /> 登记一条
        </Button>
        <Button size="sm" onClick={() => void exportPackage()} disabled={busy}>
          {busy ? <Spinner /> : null} 导出定稿包
        </Button>
      </div>

      <div className="rounded-md border border-accent/20 bg-accentSoft/20 px-3 py-2 text-xs leading-relaxed text-dim">
        这里记录的是<b>你实际使用 AI 工具的情况</b>，用于生成学校要求的声明。
        Nova 不做 AIGC 检测，也不会帮你掩盖使用痕迹；声明导出后请在 Word 中补全姓名、学号并签名。
      </div>

      {open && (
        <div className="rounded-md border border-edge bg-panel/40 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="block text-xs text-dim">
              工具名称 *
              <input
                autoFocus
                value={form.tool}
                onChange={(event) => update({ tool: event.target.value })}
                className={INPUT_CLASS}
                placeholder="例如：Nova Agent / ChatGPT"
              />
            </label>
            <label className="block text-xs text-dim">
              版本（可选）
              <input
                value={form.tool_version}
                onChange={(event) => update({ tool_version: event.target.value })}
                className={INPUT_CLASS}
                placeholder="例如：2.2.1 / GPT-4o"
              />
            </label>
            <label className="block text-xs text-dim">
              使用环节
              <input
                value={form.stage}
                onChange={(event) => update({ stage: event.target.value })}
                className={INPUT_CLASS}
                placeholder="例如：文献梳理 / 语言润色"
              />
            </label>
            <label className="block text-xs text-dim">
              用途说明
              <input
                value={form.purpose}
                onChange={(event) => update({ purpose: event.target.value })}
                className={INPUT_CLASS}
                placeholder="例如：检查段落逻辑，未直接生成正文"
              />
            </label>
          </div>
          <label className="mt-2 block text-xs text-dim">
            提示词摘要（可选）
            <textarea
              value={form.prompt}
              onChange={(event) => update({ prompt: event.target.value })}
              className={`${INPUT_CLASS} min-h-[64px] resize-y`}
              placeholder="概括你让工具做的事情，不必粘贴全文"
            />
          </label>
          <label className="mt-2 block text-xs text-dim">
            生成内容与修改情况（可选）
            <textarea
              value={form.output}
              onChange={(event) => update({ output: event.target.value })}
              className={`${INPUT_CLASS} min-h-[64px] resize-y`}
              placeholder="例如：生成了提纲草稿，本人重写并核对了引用"
            />
          </label>
          <label className="mt-2 flex items-center gap-2 text-xs text-dim">
            <input
              type="checkbox"
              checked={form.modified ?? true}
              onChange={(event) => update({ modified: event.target.checked })}
            />
            我在使用后进行了实质性修改与核对
          </label>
          <div className="mt-3 flex justify-end gap-2">
            <Button size="sm" onClick={() => setOpen(false)}>取消</Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void submit()}
              disabled={!form.tool.trim() || busy}
            >
              {busy ? <Spinner /> : <Plus size={13} />} 保存记录
            </Button>
          </div>
        </div>
      )}

      {disclosures.length === 0 ? (
        <div className="rounded-md border border-edge bg-panel/40 px-3 py-4 text-xs leading-relaxed text-dim">
          还没有登记。未登记时导出的声明会显示「未使用 AI 工具」，请如实填写后再提交。
        </div>
      ) : (
        <div className="overflow-hidden rounded-md border border-edge bg-panel/40">
          <table className="w-full text-left text-xs">
            <thead className="bg-panel/95 text-2xs text-faint">
              <tr>
                <th className="px-3 py-1.5 font-normal">工具</th>
                <th className="px-3 py-1.5 font-normal">环节</th>
                <th className="px-3 py-1.5 font-normal">用途</th>
                <th className="px-3 py-1.5 font-normal">时间</th>
                <th className="w-10 px-3 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {disclosures.map((item) => (
                <tr key={item.id} className="border-t border-edge/60 align-top">
                  <td className="px-3 py-1.5 text-ink">
                    {item.tool} {item.tool_version && <span className="text-faint">{item.tool_version}</span>}
                  </td>
                  <td className="px-3 py-1.5 text-dim">{item.stage || '—'}</td>
                  <td className="px-3 py-1.5 text-dim">{item.purpose || '—'}</td>
                  <td className="px-3 py-1.5 text-faint">{formatDate(item.created_at)}</td>
                  <td className="px-3 py-1.5">
                    <button
                      onClick={() => void removeDisclosure(item.id)}
                      className="text-faint transition-colors duration-150 hover:text-err"
                      title="删除这条记录"
                      aria-label="删除这条记录"
                    >
                      <Trash2 size={13} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
