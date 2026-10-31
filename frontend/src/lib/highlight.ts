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

const LANGS: Record<string, any> = {
  bash, cpp, css, go, java, javascript, json, markdown, python, rust, sql, typescript, xml, yaml,
}
const ALIASES: Record<string, string> = {
  js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
  py: 'python', sh: 'bash', shell: 'bash', yml: 'yaml', html: 'xml', vue: 'xml',
}
for (const [name, def] of Object.entries(LANGS)) hljs.registerLanguage(name, def)

const EXT_LANG: Record<string, string> = {
  py: 'python', js: 'javascript', jsx: 'javascript', mjs: 'javascript',
  ts: 'typescript', tsx: 'typescript', go: 'go', java: 'java', rs: 'rust',
  json: 'json', yaml: 'yaml', yml: 'yaml', toml: 'yaml', md: 'markdown',
  sh: 'bash', bash: 'bash', sql: 'sql', html: 'xml', xml: 'xml', css: 'css',
  c: 'cpp', h: 'cpp', cpp: 'cpp', cc: 'cpp', hpp: 'cpp',
}

export function languageFromPath(path: string): string | undefined {
  const ext = path.split('.').pop()?.toLowerCase() ?? ''
  return EXT_LANG[ext]
}

export function highlightCode(code: string, lang?: string): string | null {
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
