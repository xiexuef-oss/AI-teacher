// 检查 src/api/schema.d.ts 是不是由当前的 contracts/openapi.yaml 生成的。
// 契约改了而没有重新运行 `npm run gen:api` 时，这里会失败。
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const dir = mkdtempSync(join(tmpdir(), 'admin-api-'))
const fresh = join(dir, 'schema.d.ts')
try {
  execFileSync(
    process.execPath,
    ['node_modules/openapi-typescript/bin/cli.js', '../../contracts/openapi.yaml', '-o', fresh],
    { stdio: 'ignore' },
  )
  const same = readFileSync(fresh, 'utf8') === readFileSync('src/api/schema.d.ts', 'utf8')
  if (!same) {
    console.error('src/api/schema.d.ts 已过期：请运行 npm run gen:api')
    process.exitCode = 1
  } else {
    console.log('src/api/schema.d.ts 与契约一致')
  }
} finally {
  rmSync(dir, { recursive: true, force: true })
}
