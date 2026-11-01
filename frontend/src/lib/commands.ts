export type CommandName = 'fix' | 'plan' | 'review' | 'commit' | 'init' | 'help'
export type ParsedCommand = { name: CommandName; args: string } | { name: 'unknown'; raw: string }

export const COMMANDS: { name: CommandName; label: string; hint: string; needsRepo?: boolean; needsArgs?: boolean }[] = [
  { name: 'fix', label: '修复问题', hint: '/fix 描述问题 — 启动红-绿修复任务', needsRepo: true, needsArgs: true },
  { name: 'plan', label: '只出计划', hint: '/plan 目标 — 先给实施计划，不改文件', needsArgs: true },
  { name: 'review', label: '审查改动', hint: '/review — 审查当前仓库未提交的 diff', needsRepo: true },
  { name: 'commit', label: '提交 Git', hint: '/commit 消息 — 提交当前仓库改动', needsRepo: true },
  { name: 'init', label: '初始化 Git', hint: '/init — 为当前仓库初始化 Git', needsRepo: true },
  { name: 'help', label: '命令帮助', hint: '/help — 查看全部命令' },
]

export function parseCommand(input: string): ParsedCommand | null {
  const text = input.trim()
  if (!text.startsWith('/')) return null
  const match = /^\/([a-z]+)(?:\s+([\s\S]*))?$/.exec(text)
  if (!match) return { name: 'unknown', raw: text }
  const name = match[1] as CommandName
  if (!COMMANDS.some((item) => item.name === name)) return { name: 'unknown', raw: text }
  return { name, args: (match[2] ?? '').trim() }
}

/** 按命令名/说明过滤，供斜杠菜单与键盘选择共用同一份结果。 */
export function filterCommands(query: string): typeof COMMANDS {
  const needle = query.trim().toLowerCase()
  if (!needle) return COMMANDS
  return COMMANDS.filter(
    (item) => item.hint.toLowerCase().includes(needle) || item.label.toLowerCase().includes(needle),
  )
}
