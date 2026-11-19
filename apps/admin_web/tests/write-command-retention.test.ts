// @vitest-environment node
import { expect, test } from 'vitest'
import { WriteCommandStore, type ExclusiveLock } from '../src/api/write-command-store'

class Memory {
  values = new Map<string, string>()
  fail = false
  getItem(key: string) { return this.values.get(key) ?? null }
  setItem(key: string, value: string) { if (this.fail) throw Error('quota'); this.values.set(key, value) }
}
class Locks implements ExclusiveLock {
  tails = new Map<string, Promise<unknown>>()
  run<T>(key: string, action: () => Promise<T>): Promise<T> {
    const next = (this.tails.get(key) ?? Promise.resolve()).catch(() => {}).then(action)
    this.tails.set(key, next)
    return next
  }
}
const spec = (key: string) => ({ key, method: 'POST' as const, path: '/admin/import-jobs/job-a/candidates', resource: 'document:test', body: { text: 'temporary private text' } })

test('validated discard removes only selected commands, preserves epoch, and retries safely', async () => {
  const disk = new Memory(), locks = new Locks(), store = new WriteCommandStore(disk, locks, 'owner-a')
  const a = await store.prepare(spec('intent-a')), b = await store.prepare(spec('intent-b'))
  await store.discardValidated([a])
  expect(await store.list()).toEqual([b])
  await store.discardValidated([a])
  const c = await store.prepare(spec('intent-c'))
  expect(c.epoch).toBe(b.epoch + 1)
  expect((await store.list()).map(x => x.key)).toEqual(['intent-b', 'intent-c'])
})
test('one stale ticket prevents the whole discard, including otherwise valid tickets', async () => {
  const disk = new Memory(), store = new WriteCommandStore(disk, new Locks(), 'owner-a')
  const a = await store.prepare(spec('intent-a')), b = await store.prepare(spec('intent-b'))
  const raw = disk.getItem(store.storageKey)
  await expect(store.discardValidated([a, { ...b, snapshot: '0'.repeat(64) }])).rejects.toThrow()
  expect(disk.getItem(store.storageKey)).toBe(raw)
})
test('quota, corrupt raw, missing locks and foreign-owner tickets cannot discard history', async () => {
  const disk = new Memory(), locks = new Locks(), a = new WriteCommandStore(disk, locks, 'owner-a'), b = new WriteCommandStore(disk, locks, 'owner-b')
  const ca = await a.prepare(spec('intent-a')), cb = await b.prepare(spec('intent-a')), raw = disk.getItem(a.storageKey)
  await expect(a.discardValidated([cb])).rejects.toThrow()
  disk.fail = true
  await expect(a.discardValidated([ca])).rejects.toThrow('quota')
  expect(disk.getItem(a.storageKey)).toBe(raw)
  disk.fail = false
  await expect(new WriteCommandStore(disk, undefined, 'owner-a').discardValidated([ca])).rejects.toThrow()
  disk.values.set(a.storageKey, '{unknown raw')
  await expect(a.discardValidated([ca])).rejects.toThrow()
  expect(disk.getItem(a.storageKey)).toBe('{unknown raw')
})
