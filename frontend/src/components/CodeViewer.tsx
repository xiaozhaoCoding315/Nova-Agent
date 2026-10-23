import { Check, Copy } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { Badge, EmptyState, Spinner } from './common'

export function CodeViewer({ repoId, path }: { repoId: string; path: string | null }) {
  const [content, setContent] = useState<string | null>(null)
  const [meta, setMeta] = useState<{ language: string; line_count: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!path) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api.repos
      .file(repoId, path)
      .then((data) => {
        if (cancelled) return
        setContent(data.content)
        setMeta({ language: data.language, line_count: data.line_count })
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : '加载文件失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repoId, path])

  if (!path) {
    return <EmptyState title="选择一个文件查看内容" hint="左侧文件树点击文件后会在这里显示（带行号）。" />
  }

  const copyAll = async () => {
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* ignore */
    }
  }

  const lines = content?.split('\n') ?? []

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-edge px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-dim" title={path}>
          {path}
        </span>
        {meta && <Badge tone="dim">{meta.language || 'text'}</Badge>}
        {meta && <span className="text-[11px] text-dim">{meta.line_count} 行</span>}
        <button className="text-dim hover:text-ink" onClick={copyAll} aria-label="复制文件">
          {copied ? <Check size={13} className="text-ok" /> : <Copy size={13} />}
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        {loading && (
          <div className="flex items-center gap-2 p-4 text-[13px] text-dim">
            <Spinner /> 加载中…
          </div>
        )}
        {error && <p className="p-4 text-[13px] text-err">{error}</p>}
        {content !== null && !loading && !error && (
          <table className="w-full border-collapse font-mono text-[12.5px] leading-[1.55]">
            <tbody>
              {lines.map((line, i) => (
                <tr key={i} className="hover:bg-panel/60">
                  <td className="w-12 select-none border-r border-edge/60 px-2 text-right align-top text-dim/60">
                    {i + 1}
                  </td>
                  <td className="whitespace-pre px-3 align-top">{line || ' '}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}