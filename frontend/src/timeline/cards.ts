import type { StreamToolCard, ToolEvent } from '../lib/types'

export const SUBAGENT_TOOL = 'spawn_agents'

const TOOL_LABELS: Record<string, string> = {
  run_code: '沙箱执行代码',
  read_file: '读取文件',
  list_files: '列出文件',
  read_uploaded_file: '读取附件',
  search_code: '检索代码',
  impact_analysis: '影响分析',
  diagnose_error: '解析报错',
  write_files: '写入文件',
  edit_file: '精确编辑文件',
  grep: '正则搜索',
  glob: '查找文件',
  install_deps: '安装依赖',
  json_tool: 'JSON/YAML 处理',
  sql_tool: 'SQL 审阅',
  fetch_url: '抓取网页',
  web_search: '网络搜索',
  spawn_agents: '子代理',
}

export function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name]
  if (name.startsWith('mcp__')) return `外部工具 ${name.split('__')[1] ?? name}`
  return name
}

export type ToolCardKind = 'terminal' | 'file' | 'search' | 'web' | 'generic'

const TERMINAL_TOOLS = new Set(['run_code', 'run_command', 'install_deps'])
const FILE_TOOLS = new Set(['read_file', 'write_files', 'edit_file', 'read_uploaded_file'])
const SEARCH_TOOLS = new Set(['search_code', 'grep', 'glob', 'impact_analysis', 'diagnose_error'])

/** 按工具名把结果分发到终端卡 / 文件卡 / 检索卡 / 网页搜索卡 / 通用卡。 */
export function toolCardKind(name: string): ToolCardKind {
  if (TERMINAL_TOOLS.has(name)) return 'terminal'
  if (FILE_TOOLS.has(name)) return 'file'
  if (SEARCH_TOOLS.has(name)) return 'search'
  if (name === 'web_search') return 'web'
  return 'generic'
}

export const TOOL_CARD_CLASS =
  'overflow-hidden rounded-md border border-edge bg-panel/60 transition-colors duration-150 hover:border-faint/70'

export function argString(card: StreamToolCard, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = card.call.args?.[key]
    if (typeof value === 'string' && value.trim()) return value
  }
  return null
}

export function toolCommand(card: StreamToolCard): string | null {
  return card.command ?? argString(card, 'command')
}

/** 文件类工具的展示路径：显式 path → 写入文件首项 → 结果里的 filename/path。 */
export function toolFilePath(card: StreamToolCard): string | null {
  const direct = argString(card, 'path', 'filename')
  if (direct) return direct
  const files = card.call.args?.files
  if (Array.isArray(files) && typeof files[0] === 'string') return files[0]
  if (files && typeof files === 'object') {
    const first = Object.keys(files)[0]
    if (first) return first
  }
  const parsed = parsePreviewJson(card.result?.preview)
  if (parsed) {
    if (typeof parsed.filename === 'string') return parsed.filename
    if (typeof parsed.path === 'string') return parsed.path
  }
  return null
}

/** 检索类工具的展示查询：query/pattern/symbol，报错解析取堆栈首行。 */
export function toolQuery(card: StreamToolCard): string | null {
  const direct = argString(card, 'query', 'pattern', 'symbol', 'error')
  if (direct) return direct
  const stack = argString(card, 'stack')
  if (stack) return stack.split('\n')[0]?.trim() || stack
  const parsed = parsePreviewJson(card.result?.preview)
  if (parsed) {
    if (typeof parsed.query === 'string') return parsed.query
    if (typeof parsed.symbol === 'string') return parsed.symbol
  }
  return null
}

/** build_preview 的 JSON 可能被截断；只有在可解析时才返回对象。 */
export function parsePreviewJson(preview: string | null | undefined): Record<string, unknown> | null {
  if (!preview) return null
  const text = preview.trim()
  if (!text.startsWith('{') && !text.startsWith('[')) return null
  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** 从检索结果里尽力提取命中数（不同工具字段不同）。 */
export function searchHitCount(result: Record<string, unknown> | null): number | null {
  if (!result) return null
  for (const key of ['match_count', 'file_count', 'total', 'count']) {
    if (typeof result[key] === 'number') return result[key] as number
  }
  for (const key of ['matches', 'files', 'counts', 'symbols', 'snippets', 'references', 'frames', 'repo_locations']) {
    const list = asArray(result[key])
    if (list.length > 0) return list.length
  }
  return null
}

export type WebResult = { title: string; url: string; snippet: string }

/** 网络搜索结果；只放行 http(s) 链接，其余条目忽略。 */
export function webResults(card: StreamToolCard): WebResult[] {
  const parsed = parsePreviewJson(card.result?.preview)
  const results: WebResult[] = []
  for (const item of asArray(parsed?.results)) {
    if (!item || typeof item !== 'object') continue
    const record = item as Record<string, unknown>
    const url = typeof record.url === 'string' ? record.url.trim() : ''
    if (!/^https?:\/\//i.test(url)) continue
    const title = typeof record.title === 'string' ? record.title.trim() : ''
    results.push({
      title: title || url,
      url,
      snippet: typeof record.snippet === 'string' ? record.snippet.trim() : '',
    })
  }
  return results
}

/** 命中路径：优先结构化字段，其次从被截断的 JSON 文本里扫 "path"。 */
export function searchPaths(card: StreamToolCard): string[] {
  const parsed = parsePreviewJson(card.result?.preview)
  const found: string[] = []
  const push = (value: unknown) => {
    if (typeof value === 'string' && value && !found.includes(value)) found.push(value)
  }
  if (parsed) {
    for (const key of ['matches', 'files', 'counts', 'symbols', 'snippets', 'references', 'repo_locations', 'direct_dependents', 'transitive_dependents']) {
      for (const item of asArray(parsed[key])) {
        if (typeof item === 'string') push(item)
        else if (item && typeof item === 'object') push((item as Record<string, unknown>).path)
      }
    }
    push(parsed.path)
  }
  if (found.length === 0 && card.result?.preview) {
    const pattern = /"path"\s*:\s*"([^"]+)"/g
    for (const match of card.result.preview.matchAll(pattern)) push(match[1])
  }
  return found
}

/** +add/-del 估算：优先用流式入参里的完整文件/编辑内容，其次解析 diff 预览。 */
export function diffEstimate(card: StreamToolCard): { add: number; del: number } | null {
  const args = card.call.args ?? {}
  const files = args.files
  let add = 0
  let del = 0
  let measured = false

  if (files && typeof files === 'object' && !Array.isArray(files)) {
    for (const content of Object.values(files as Record<string, unknown>)) {
      if (typeof content !== 'string') continue
      add += content ? content.split('\n').length : 0
      measured = true
    }
  }

  const edits = asArray(args.edits)
  for (const item of edits) {
    if (!item || typeof item !== 'object') continue
    const edit = item as Record<string, unknown>
    if (typeof edit.old_string === 'string') del += edit.old_string ? edit.old_string.split('\n').length : 0
    if (typeof edit.new_string === 'string') add += edit.new_string ? edit.new_string.split('\n').length : 0
    measured = true
  }

  if (measured) return { add, del }

  const preview = card.result?.preview
  if (!preview) return null
  const parsed = parsePreviewJson(preview)
  const diff = typeof parsed?.diff_preview === 'string'
    ? parsed.diff_preview
    : preview.replace(/\\n/g, '\n')
  if (!diff.includes('+') && !diff.includes('-')) return null
  for (const line of diff.split('\n')) {
    if (line.startsWith('+++') || line.startsWith('---')) continue
    if (line.startsWith('+')) add += 1
    else if (line.startsWith('-')) del += 1
  }
  return { add, del }
}

/** 从 preview JSON 里兜底取正文时允许的最大长度，避免异常结果撑爆高亮渲染。 */
const PREVIEW_CONTENT_LIMIT = 20_000

/** 文件卡的预览体量：content_preview 优先，其次 preview JSON 里的正文，最后是流式入参。 */
export function filePreview(card: StreamToolCard): { text: string; lines: number; bytes: number } | null {
  const content = card.result?.content_preview
  if (content) {
    return {
      text: content,
      lines: content.split('\n').length,
      bytes: new TextEncoder().encode(content).length,
    }
  }
  // 旧事件或实时结果只有 build_preview 的 JSON（读文件时含 content 字段）。
  // 解析失败（截断的 JSON）或内容异常长时安静放弃，交给后面的入参兜底。
  const previewJson = parsePreviewJson(card.result?.preview)
  const previewContent = previewJson?.content
  if (typeof previewContent === 'string' && previewContent.length > 0
    && previewContent.length <= PREVIEW_CONTENT_LIMIT) {
    return {
      text: previewContent,
      lines: previewContent.split('\n').length,
      bytes: new TextEncoder().encode(previewContent).length,
    }
  }
  const files = card.call.args?.files
  if (files && typeof files === 'object' && !Array.isArray(files)) {
    const text = Object.values(files as Record<string, unknown>).find(
      (value): value is string => typeof value === 'string' && value.length > 0,
    )
    if (text) {
      return { text, lines: text.split('\n').length, bytes: new TextEncoder().encode(text).length }
    }
  }
  const edits = asArray(card.call.args?.edits)
  const newStrings = edits
    .map((item) => (item && typeof item === 'object' ? (item as Record<string, unknown>).new_string : null))
    .filter((value): value is string => typeof value === 'string')
  if (newStrings.length > 0) {
    const text = newStrings.join('\n')
    return { text, lines: text.split('\n').length, bytes: new TextEncoder().encode(text).length }
  }
  return null
}

/** Adapter that renders a persisted tool_event with the same card components. */
export function eventToCard(event: ToolEvent, index: number): StreamToolCard {
  return {
    call: {
      id: `event-${index}`,
      name: event.name,
      args: event.args ?? {},
      round: event.round ?? 0,
    },
    result: {
      id: `event-${index}`,
      name: event.name,
      ok: event.ok,
      ms: event.ms,
      preview: event.error ? `错误：${event.error}` : (event.preview ?? ''),
      stdout_tail: event.stdout_tail ?? null,
      stderr_tail: event.stderr_tail ?? null,
      content_preview: event.content_preview ?? null,
    },
    command: event.command ?? null,
    exit_code: event.exit_code ?? null,
    timedOut: Boolean(event.timed_out),
  }
}
