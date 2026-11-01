import { memo, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { highlightCode as highlight } from '../lib/highlight'

function PreBlock({ children }: { children?: any }) {
  const [copied, setCopied] = useState(false)
  const codeEl = Array.isArray(children) ? children[0] : children
  const className: string = codeEl?.props?.className ?? ''
  const lang = /language-(\w+)/.exec(className)?.[1]
  const text = String(codeEl?.props?.children ?? '').replace(/\n$/, '')
  const html = useMemo(() => highlight(text, lang), [text, lang])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-edge bg-[#0d1117]">
      <div className="flex items-center justify-between border-b border-edge bg-panel px-3 py-1">
        <span className="font-mono text-xs text-dim">{lang ?? 'text'}</span>
        <button className="text-xs text-dim transition-colors hover:text-ink" onClick={copy}>
          {copied ? '已复制' : '复制代码'}
        </button>
      </div>
      <pre className="overflow-x-auto p-3">
        {html ? (
          <code className="hljs bg-transparent p-0" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <code className="bg-transparent p-0">{text}</code>
        )}
      </pre>
    </div>
  )
}

export const Markdown = memo(function Markdown({ content }: { content: string }) {
  return (
    <div className="md-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ pre: PreBlock as any }}>
        {content}
      </ReactMarkdown>
    </div>
  )
})