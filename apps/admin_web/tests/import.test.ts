import { webcrypto } from 'node:crypto'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../src/api/admin'
import { ApiError } from '../src/api/client'
import ImportView from '../src/views/ImportView.vue'
import { setSession } from '../src/session'
import { detail, ME } from './fixtures'

enableAutoUnmount(afterEach)

vi.mock('../src/api/admin', () => ({ importQuestion: vi.fn() }))

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('crypto', webcrypto)
  const tails = new Map<string, Promise<unknown>>()
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: async <T>(name: string, _options: unknown, action: () => Promise<T>) => {
    const next = (tails.get(name) ?? Promise.resolve()).catch(() => {}).then(action)
    tails.set(name, next)
    return next
  } } })
  vi.resetAllMocks()
  setSession({ token: 'tok', userId: ME, role: 'reviewer' })
})

async function page() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: ImportView },
    { path: '/questions/:id', name: 'question', component: { template: '<div />' } },
  ] })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(ImportView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

const body = { subject: 'math', answer_mode: 'single_choice', source: {
  source_name: '自编练习', source_license: '本人自编',
}, question: { title: '导入题目', content: { stem: '题干' } } }

it('无效 JSON 显示错误，不能发送请求', async () => {
  const w = await page()
  await w.get('textarea').setValue('{bad')
  expect(w.get('[data-testid="import-submit"]').attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('JSON')
  expect(api.importQuestion).not.toHaveBeenCalled()
})

it('选择文件后读取并预览，超大文件不读取', async () => {
  const w = await page()
  const file = new File([], 'question.json', { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => JSON.stringify(body) })
  const input = w.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await flushPromises()
  expect(w.text()).toContain('导入题目')
  expect(w.text()).toContain('本人自编')
  Object.defineProperty(file, 'size', { value: 1024 * 1024 + 1 })
  await input.trigger('change')
  expect(w.text()).toContain('不超过 1 MB')
  expect(w.get('[data-testid="import-submit"]').attributes('disabled')).toBeDefined()
})

it('预览来源，明确确认后提交；网络失败重试复用键，成功后禁止重复导入', async () => {
  const w = await page()
  vi.mocked(api.importQuestion).mockRejectedValueOnce(new ApiError(0, 'network_error', '断网'))
    .mockResolvedValueOnce(detail())
  await w.get('textarea').setValue(JSON.stringify(body))
  expect(w.text()).toContain('本人自编')
  expect(w.get('[data-testid="import-submit"]').attributes('disabled')).toBeDefined()
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await flushPromises()
  await vi.waitFor(() => expect(w.text()).toContain('断网'))
  await w.get('[data-testid="import-retry"]').trigger('click')
  await flushPromises()
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(2))
  const calls = vi.mocked(api.importQuestion).mock.calls
  expect(calls[0]?.[1]).toEqual(body)
  expect(calls[0]?.[2]).toBe(calls[1]?.[2])
  await vi.waitFor(() => expect(w.text()).toContain('已保存为待审草稿'))
  expect(w.get('[data-testid="import-submit"]').attributes('disabled')).toBeDefined()
})



