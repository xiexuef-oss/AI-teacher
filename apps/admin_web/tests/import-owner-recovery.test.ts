import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../src/api/admin'
import { ApiError } from '../src/api/client'
import ImportView from '../src/views/ImportView.vue'
import { setSession, useSession } from '../src/session'
import { detail, ME } from './fixtures'
import { webcrypto } from 'node:crypto'

vi.mock('../src/api/admin', () => ({ importQuestion: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
beforeEach(() => {
  vi.resetAllMocks()
  localStorage.clear()
  sessionStorage.clear()
  vi.stubGlobal('crypto', webcrypto)
  const tails = new Map<string, Promise<unknown>>()
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async <T>(name: string, _options: unknown, action: () => Promise<T>) => {
    const next = (tails.get(name) ?? Promise.resolve()).catch(() => {}).then(action)
    tails.set(name, next)
    return next
  } } })
  setSession({ token: 'synthetic-A', userId: ME, role: 'reviewer' })
})
afterEach(() => wrappers.splice(0).forEach(w => w.unmount()))
const body = { subject: 'math', answer_mode: 'single_choice', source: {
  source_name: '自编恢复探针', source_license: '本人自编',
}, question: { title: '自编恢复探针', content: { stem: '题干' } } }
async function page() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: ImportView },
    { path: '/questions/:id', name: 'question', component: { template: '<div />' } },
  ] })
  await router.push('/')
  await router.isReady()
  const w = mount(ImportView, { global: { plugins: [router] } })
  wrappers.push(w)
  await flushPromises()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  return w
}
it('A request 401 does not clear B session or show an old error', async () => {
  let reject!: (error: unknown) => void
  vi.mocked(api.importQuestion).mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
  const w = await page()
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(1))
  setSession({ token: 'synthetic-B', userId: 'B', role: 'reviewer' })
  reject(new ApiError(401, 'unauthorized', 'A expired'))
  await flushPromises()
  expect(useSession().session?.userId).toBe('B')
  expect(w.text()).not.toContain('A expired')
})
it('A success cannot display a foreign draft in B session', async () => {
  let resolve!: (value: ReturnType<typeof detail>) => void
  vi.mocked(api.importQuestion).mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const w = await page()
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(1))
  setSession({ token: 'synthetic-B', userId: 'B', role: 'reviewer' })
  resolve(detail())
  await flushPromises()
  expect(w.text()).not.toContain('已保存为待审草稿')
  expect((w.get('textarea').element as HTMLTextAreaElement).value).toBe('')
})
