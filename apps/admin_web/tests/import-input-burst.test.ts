// @vitest-environment node
import { webcrypto } from 'node:crypto'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { ImportWriteRecovery } from '../src/import-write-recovery'

let writes: number
beforeEach(() => {
  const entries = new Map<string, string>()
  writes = 0
  vi.stubGlobal('localStorage', { getItem: (key: string) => entries.get(key) ?? null, setItem: (key: string, value: string) => { writes++; entries.set(key, value) } })
  vi.stubGlobal('crypto', webcrypto)
})
afterEach(() => vi.unstubAllGlobals())
const locks = { async run<T>(_name: string, action: () => Promise<T>): Promise<T> { return action() } }

it('one multiline paste with repeated identical input snapshots performs one durable write', async () => {
  const store = new ImportWriteRecovery('same-owner', locks)
  let cursor = 0
  for (let event = 0; event < 223; event++) {
    cursor = (await store.save('self-authored\nmultiline\ntext', cursor)).generation
  }
  expect(writes).toBe(1)
  expect((await store.load()).generation).toBe(1)
  // Returning to earlier text after a real change must still be a new edit.
  cursor = (await store.save('changed text', cursor)).generation
  expect((await store.save('self-authored\nmultiline\ntext', cursor)).generation).toBe(3)
})
it('a repeated stale snapshot preserves one B branch while keeping A and its source', async () => {
  const store = new ImportWriteRecovery('same-owner', locks)
  await store.save('A', 0)
  for (let event = 0; event < 223; event++) await store.save('B', 0)
  const durable = await new ImportWriteRecovery('same-owner', locks).load()
  expect(durable.raw).toBe('A')
  expect(durable.generation).toBe(1)
  expect(durable.branches).toHaveLength(1)
  expect(durable.branches[0]).toMatchObject({ raw: 'B', sourceGeneration: 0 })
  expect(writes).toBe(2)
})
