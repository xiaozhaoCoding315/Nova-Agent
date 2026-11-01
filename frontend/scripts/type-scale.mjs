/**
 * 一次性字号 codemod：把源码里的 `text-[Npx]` 全部映射到 tailwind 的字号 token。
 * 保留在仓库中备查；运行方式（在 frontend/ 下）：
 *
 *   node scripts/type-scale.mjs
 *
 * 说明：字号 token 定义在 tailwind.config.ts 的 theme.extend.fontSize。
 * 白名单只允许 diff / 终端预览等必须保持像素等宽的尺寸；当前项目没有任何例外，
 * 因此集合为空。若将来确实需要例外，请连同原因一起写在这里。
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'

const MAP = {
  9: 'text-2xs', 9.5: 'text-2xs', 10: 'text-2xs',
  10.5: 'text-xs', 11: 'text-xs',
  11.5: 'text-sm', 12: 'text-sm',
  12.5: 'text-base', 13: 'text-base', 13.5: 'text-base',
  14: 'text-md', 14.5: 'text-md',
  15: 'text-lg', 16: 'text-lg',
  17: 'text-xl', 18: 'text-xl',
  20: 'text-2xl', 22: 'text-2xl',
  24: 'text-3xl', 28: 'text-3xl',
}

/** diff / 终端等需要像素等宽的例外，格式：`text-[11px]`。当前为空。 */
const WHITELIST = new Set()

const files = execFileSync(
  'git',
  // --cached/--others 同时覆盖已跟踪与新文件；`src/**/*.tsx` 这类 pathspec 会漏掉 src 根层文件。
  ['ls-files', '--cached', '--others', '--exclude-standard', 'src'],
  { encoding: 'utf8' },
).split('\n').filter((file) => /\.(tsx?|css)$/.test(file))

let changedFiles = 0
let replacements = 0
const unmapped = []

for (const file of files) {
  const before = readFileSync(file, 'utf8')
  let touched = false
  const after = before.replace(/text-\[([0-9.]+)px\]/g, (whole) => {
    if (WHITELIST.has(whole)) return whole
    const size = Number(whole.slice('text-['.length, -'px]'.length))
    const token = MAP[size]
    if (!token) {
      unmapped.push(`${whole} in ${file}`)
      console.warn(`unmapped ${whole} in ${file}`)
      return whole
    }
    replacements += 1
    touched = true
    return token
  })
  if (touched) {
    writeFileSync(file, after)
    changedFiles += 1
  }
}

console.log(`type-scale: ${replacements} replacements in ${changedFiles} files`)
if (unmapped.length > 0) {
  console.log(`type-scale: ${unmapped.length} unmapped values need manual handling`)
  process.exitCode = 1
}
