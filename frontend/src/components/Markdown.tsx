import { memo, useMemo, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import cpp from 'highlight.js/lib/languages/cpp'
import css from 'highlight.js/lib/languages/css'
import go from 'highlight.js/lib/languages/go'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import python from 'highlight.js/lib/languages/python'
import rust from 'highlight.js/lib/languages/rust'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

// highlight.js core + only the languages developers actually paste (~90KB
// instead of the ~500KB full build).
const LANGS: Record<string, any> = {
  bash, cpp, css, go, java, javascript, json, markdown, python, rust, sql, typescript, xml, yaml,
}
const ALIASES: Record<string, string> = {
  js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
  py: 'python', sh: 'bash', shell: 'bash', yml: 'yaml', html: 'xml', vue: 'xml',
}
for (const [name, def] of Object.entries(LANGS)) hljs.registerLanguage(name, def)

function highlight(code: string, lang?: string): string | null {
  const resolved = lang ? ALIASES[lang] ?? lang : undefined
  try {
    if (resolved && hljs.getLanguage(resolved)) {
      return hljs.highlight(code, { language: resolved }).value
    }
    return hljs.highlightAuto(code).value
  } catch {
    return null
  }
}

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
        <span className="font-mono text-[11px] text-dim">{lang ?? 'text'}</span>
        <button className="text-[11px] text-dim transition-colors hover:text-ink" onClick={copy}>
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