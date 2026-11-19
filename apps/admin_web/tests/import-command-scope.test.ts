// @vitest-environment node
import { webcrypto } from 'node:crypto'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ImportWriteRecovery } from '../src/import-write-recovery'

beforeEach(() => {
  const entries = new Map<string, string>()
  vi.stubGlobal('localStorage', { getItem: (key: string) => entries.get(key) ?? null, setItem: (key: string, value: string) => entries.set(key, value) })
  vi.stubGlobal('crypto', webcrypto)
})
afterEach(() => vi.unstubAllGlobals())
const locks = { async run<T>(_name: string, action: () => Promise<T>): Promise<T> { return action() } }

it('import recovery never selects a later pending review of the same owner', async () => {
  const recovery = new ImportWriteRecovery('reviewer-test', locks)
  await recovery.commands.prepare({ key: 'import-intent-A', method: 'POST', path: '/admin/question-imports', resource: 'single-question-import', body: { question: { title: '自编A' } } })
  await recovery.commands.prepare({ key: 'review-intent-B', method: 'POST', path: '/admin/questions/q/review', resource: 'question-review:q', body: { decision: 'approve', expected_version: 1, expected_review_revision: 1 } })
  expect((await recovery.pending())?.key).toBe('import-intent-A')
})
it('another resource cannot create a recovery action on an empty import page', async () => {
  const recovery = new ImportWriteRecovery('reviewer-test', locks)
  await recovery.commands.prepare({ key: 'edit-intent-A', method: 'POST', path: '/admin/questions/q/versions', resource: 'question-edit:q', body: { title: '自编编辑' } })
  expect(await recovery.pending()).toBeUndefined()
})
