#!/usr/bin/env node
/**
 * Copy check for user-visible strings.
 *
 * The word list lives in docs/COPY-GUIDELINES.md. This script deliberately
 * stays simple: strip comments, scan the remaining source text, and report
 * file:line. It is a reminder, not a grammar checker.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = resolve(fileURLToPath(new URL('.', import.meta.url)))
const ROOT = resolve(HERE, '..', '..')

const BANNED = [
  '让 AI 理解', 'AI 会思考', 'AI 帮你搞定',
  '智能', '全面', '轻松', '无缝', '一键', '极速', '强大',
  '降低 AI 率', '降 AIGC', '保证通过', 'ATS 友好', '查重率 0',
  '赋能', '闭环', '抓手', '心智', '范式',
]

// Internal code comments are not user-visible. This allowlist only covers
// phrases that contain a banned substring by accident.
const ALLOWLIST = [
  '撞唯一键时重换码',
]

const TARGETS = ['frontend/src', 'backend/app']
const EXTENSIONS = new Set(['.ts', '.tsx', '.py'])
const SKIP_DIRS = new Set(['__pycache__', 'node_modules', 'dist'])

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue
    const path = join(dir, name)
    const stat = statSync(path)
    if (stat.isDirectory()) walk(path, out)
    else if (EXTENSIONS.has(name.slice(name.lastIndexOf('.')))) out.push(path)
  }
  return out
}

function stripLineComment(line, marker) {
  let quote = ''
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i]
    if (quote) {
      if (char === '\\') i += 1
      else if (char === quote) quote = ''
      continue
    }
    if (char === '"' || char === "'" || char === '`') {
      quote = char
      continue
    }
    if (line.startsWith(marker, i)) return line.slice(0, i)
  }
  return line
}

function stripBlockComments(text) {
  let result = ''
  let i = 0
  let quote = ''
  while (i < text.length) {
    const char = text[i]
    if (quote) {
      result += char
      if (char === '\\') {
        result += text[i + 1] ?? ''
        i += 2
        continue
      }
      if (char === quote) quote = ''
      i += 1
      continue
    }
    if (char === '"' || char === "'" || char === '`') {
      quote = char
      result += char
      i += 1
      continue
    }
    if (text.startsWith('/*', i)) {
      const end = text.indexOf('*/', i + 2)
      if (end === -1) break
      result += '\n'.repeat(text.slice(i, end + 2).split('\n').length - 1)
      i = end + 2
      continue
    }
    result += char
    i += 1
  }
  return result
}

const findings = []
for (const target of TARGETS) {
  const base = join(ROOT, target)
  for (const file of walk(base)) {
    const raw = readFileSync(file, 'utf8')
    const cleaned = file.endsWith('.py')
      ? raw.split('\n').map((line) => stripLineComment(line, '#')).join('\n')
      : stripBlockComments(raw).split('\n').map((line) => stripLineComment(line, '//')).join('\n')
    cleaned.split('\n').forEach((line, index) => {
      if (ALLOWLIST.some((entry) => line.includes(entry))) return
      for (const phrase of BANNED) {
        if (line.includes(phrase)) {
          findings.push(`${relative(ROOT, file)}:${index + 1}: ${phrase}`)
        }
      }
    })
  }
}

if (findings.length > 0) {
  console.error('用户可见文案命中禁用词：')
  for (const finding of findings) console.error(`  ${finding}`)
  console.error('规范见 docs/COPY-GUIDELINES.md；确有必要时加入 ALLOWLIST 并说明原因。')
  process.exit(1)
}
console.log('copy check passed')
