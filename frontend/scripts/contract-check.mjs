import { execFileSync } from 'node:child_process'
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repo = path.resolve(frontend, '..')
const contract = path.join(repo, 'contracts', 'openapi.json')
const target = path.join(frontend, 'src', 'lib', 'api-schema.d.ts')
const cli = path.join(frontend, 'node_modules', 'openapi-typescript', 'bin', 'cli.js')

const normalize = (value) => value.replace(/\r\n/g, '\n')

execFileSync(process.env.PYTHON || 'python', ['-m', 'scripts.export_openapi', '--check'], {
  cwd: path.join(repo, 'backend'),
  stdio: 'inherit',
})

const temp = mkdtempSync(path.join(tmpdir(), 'nova-contract-'))
const generated = path.join(temp, 'api-schema.d.ts')
try {
  execFileSync(process.execPath, [cli, contract, '-o', generated], { stdio: 'inherit' })
  const expected = normalize(readFileSync(generated, 'utf8'))
  const actual = normalize(existsSync(target) ? readFileSync(target, 'utf8') : '')
  if (expected !== actual) {
    const exp = expected.split('\n')
    const act = actual.split('\n')
    for (let i = 0; i < Math.max(exp.length, act.length); i += 1) {
      if (exp[i] !== act[i]) {
        console.error(`contract types are stale at line ${i + 1}`)
        console.error(`  expected: ${exp[i] ?? ''}`)
        console.error(`  actual:   ${act[i] ?? ''}`)
        break
      }
    }
    console.error('run npm run contract:generate')
    process.exitCode = 1
  } else {
    console.log('contract types up to date')
  }
} finally {
  rmSync(temp, { recursive: true, force: true })
}
