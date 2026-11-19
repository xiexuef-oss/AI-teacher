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

it('重载后保留未知原导入body和key且不自动POST', async () => {
  const first = await page()
  vi.mocked(api.importQuestion).mockRejectedValue(new ApiError(0, 'network_error', '断网'))
  await first.get('textarea').setValue(JSON.stringify(body))
  await first.get('input[type="checkbox"]').setValue(true)
  await first.get('[data-testid="import-submit"]').trigger('click')
  await flushPromises()
  await vi.waitFor(() => expect(first.text()).toContain('断网'))
  const originalKey = vi.mocked(api.importQuestion).mock.calls[0]?.[2]
  first.unmount()
  const restored = await page()
  await flushPromises()
  expect(vi.mocked(api.importQuestion)).toHaveBeenCalledTimes(1)
  await vi.waitFor(() => expect(restored.get('textarea').element.value).toBe(JSON.stringify(body)))
  await restored.get('[data-testid="import-retry"]').trigger('click')
  await flushPromises()
  await vi.waitFor(() => expect(vi.mocked(api.importQuestion).mock.calls[1]?.[1]).toEqual(body))
  expect(vi.mocked(api.importQuestion).mock.calls[1]?.[2]).toBe(originalKey)
})




it('配额失败保留编辑且零HTTP', async () => {
  const w = await page()
  const original = Storage.prototype.setItem
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key, value) {
    if (key.startsWith('admin-import-draft/') || key.startsWith('admin-write/')) throw new DOMException('quota', 'QuotaExceededError')
    return original.call(this, key, value)
  })
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(w.text()).toContain('输入'))
  expect(w.get('textarea').element.value).toBe(JSON.stringify(body))
  expect(api.importQuestion).not.toHaveBeenCalled()
  vi.restoreAllMocks()
})

it('A在途续改B，旧成功不清B且重载保留B', async () => {
  let release!: (value: ReturnType<typeof detail>) => void
  vi.mocked(api.importQuestion).mockImplementation(() => new Promise(resolve => { release = resolve }))
  const w = await page()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(1))
  const b = { ...body, question: { ...body.question, title: '续改B' } }
  await w.get('textarea').setValue(JSON.stringify(b))
  release(detail())
  await vi.waitFor(() => expect(w.text()).toContain('续改内容保留'))
  expect(w.get('textarea').element.value).toBe(JSON.stringify(b))
  expect(w.find('a[href^="/questions/"]').exists()).toBe(false)
  w.unmount()
  const restored = await page()
  await vi.waitFor(() => expect(restored.get('textarea').element.value).toBe(JSON.stringify(b)))
  expect(api.importQuestion).toHaveBeenCalledTimes(1)
})

it('A未知续改B重启，恢复只发A原body和key', async () => {
  vi.mocked(api.importQuestion).mockRejectedValue(new ApiError(0, 'network_error', '断网'))
  const w = await page()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(w.text()).toContain('断网'))
  const key = vi.mocked(api.importQuestion).mock.calls[0]?.[2]
  const b = { ...body, question: { ...body.question, title: '续改B' } }
  await w.get('textarea').setValue(JSON.stringify(b))
  await flushPromises()
  w.unmount()
  const restored = await page()
  await vi.waitFor(() => expect(restored.get('textarea').element.value).toBe(JSON.stringify(b)))
  await restored.get('[data-testid="import-retry"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(2))
  expect(vi.mocked(api.importQuestion).mock.calls[1]?.slice(1)).toEqual([body, key])
})

it('result_known重载纯本机确认，无HTTP且不依赖文件', async () => {
  const { WriteCommandStore, browserLocks } = await import('../src/api/write-command-store')
  const store = new WriteCommandStore(localStorage, browserLocks(), ME)
  const command = await store.prepare({ key: 'known-import', method: 'POST', path: '/admin/question-imports', resource: 'single-question-import', body })
  await store.recordResult(command, detail() as never)
  const w = await page()
  await vi.waitFor(() => expect(w.find('[data-testid="import-ack"]').exists()).toBe(true))
  await w.get('[data-testid="import-ack"]').trigger('click')
  await vi.waitFor(() => expect(w.text()).toContain('历史命令结果'))
  expect(api.importQuestion).not.toHaveBeenCalled()
  expect((await store.list())[0]?.phase).toBe('acked')
})

it('卸载的迟到A只留历史，不污染同路由新组件', async () => {
  let release!: (value: ReturnType<typeof detail>) => void
  vi.mocked(api.importQuestion).mockImplementation(() => new Promise(resolve => { release = resolve }))
  const first = await page()
  await first.get('textarea').setValue(JSON.stringify(body))
  await first.get('input[type="checkbox"]').setValue(true)
  await first.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(1))
  first.unmount()
  const next = await page()
  const b = { ...body, question: { ...body.question, title: '新页面B' } }
  await next.get('textarea').setValue(JSON.stringify(b))
  release(detail())
  await new Promise(resolve => setTimeout(resolve, 30))
  expect(next.get('textarea').element.value).toBe(JSON.stringify(b))
  expect(next.text()).not.toContain('已保存为待审草稿。程序校验')
  const { WriteCommandStore, browserLocks } = await import('../src/api/write-command-store')
  expect((await new WriteCommandStore(localStorage, browserLocks(), ME).list())[0]?.phase).toBe('result_known')
})

it('同owner新登录epoch阻止旧A成功污染新页面状态', async () => {
  let release!: (value: ReturnType<typeof detail>) => void
  vi.mocked(api.importQuestion).mockImplementation(() => new Promise(resolve => { release = resolve }))
  const w = await page()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(1))
  setSession({ token: 'replacement-token', userId: ME, role: 'reviewer' })
  await flushPromises()
  const b = { ...body, question: { ...body.question, title: '新登录续改B' } }
  await w.get('textarea').setValue(JSON.stringify(b))
  release(detail())
  const { WriteCommandStore, browserLocks } = await import('../src/api/write-command-store')
  await vi.waitFor(async () => expect((await new WriteCommandStore(localStorage, browserLocks(), ME).list())[0]?.phase).toBe('result_known'))
  expect(w.get('textarea').element.value).toBe(JSON.stringify(b))
  expect(w.text()).not.toContain('已保存为待审草稿。程序校验')
  expect(api.importQuestion).toHaveBeenCalledTimes(1)
})

it('损坏草稿原文不被覆盖，也不发HTTP', async () => {
  const key = `admin-import-draft/v1/${encodeURIComponent(ME)}`
  const damaged = '{"v":99,"precious":"local only"}'
  localStorage.setItem(key, damaged)
  const w = await page()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(w.text()).toContain('保留'))
  expect(localStorage.getItem(key)).toBe(damaged)
  expect(w.get('textarea').element.value).toBe(JSON.stringify(body))
  expect(api.importQuestion).not.toHaveBeenCalled()
})

it('ACK落盘失败仍保留known结果，重载可纯本机确认', async () => {
  const original = Storage.prototype.setItem
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key, value) {
    if (key.startsWith('admin-write/') && value.includes('"phase":"acked"')) throw new DOMException('quota', 'QuotaExceededError')
    return original.call(this, key, value)
  })
  vi.mocked(api.importQuestion).mockResolvedValue(detail())
  const first = await page()
  await first.get('textarea').setValue(JSON.stringify(body))
  await first.get('input[type="checkbox"]').setValue(true)
  await first.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(first.find('[data-testid="import-ack"]').exists()).toBe(true))
  await vi.waitFor(() => expect(first.text()).toContain('输入与原命令保留'))
  first.unmount()
  spy.mockRestore()
  const next = await page()
  await vi.waitFor(() => expect(next.find('[data-testid="import-ack"]').exists()).toBe(true))
  await next.get('[data-testid="import-ack"]').trigger('click')
  await vi.waitFor(() => expect(next.text()).toContain('历史命令结果'))
  expect(api.importQuestion).toHaveBeenCalledTimes(1)
})

it('同路由query变更代际隔离旧成功', async () => {
  let release!: (value: ReturnType<typeof detail>) => void
  vi.mocked(api.importQuestion).mockImplementation(() => new Promise(resolve => { release = resolve }))
  const w = await page()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(1))
  await w.vm.$router.push('/?generation=next')
  await flushPromises()
  const b = { ...body, question: { ...body.question, title: '路由新代际B' } }
  await w.get('textarea').setValue(JSON.stringify(b))
  release(detail())
  const { WriteCommandStore, browserLocks } = await import('../src/api/write-command-store')
  await vi.waitFor(async () => expect((await new WriteCommandStore(localStorage, browserLocks(), ME).list())[0]?.phase).toBe('result_known'))
  expect(w.get('textarea').element.value).toBe(JSON.stringify(b))
  expect(w.text()).not.toContain('已保存为待审草稿。程序校验')
})

it('两实例同来源冲突分支B落盘且重建可读取，A不覆盖', async () => {
  const { ImportWriteRecovery } = await import('../src/import-write-recovery')
  const a = new ImportWriteRecovery(ME), b = new ImportWriteRecovery(ME)
  const sourceA = await a.load(), sourceB = await b.load()
  await a.save('A', sourceA.generation)
  try { await b.save('B', sourceB.generation) } catch { /* prior version throws */ }
  const restored = await new ImportWriteRecovery(ME).load() as unknown as { raw: string; branches: { raw: string }[] }
  expect(restored.raw).toBe('A')
  expect(restored.branches.some(branch => branch.raw === 'B')).toBe(true)
})

it('明确422后保留A为rejected，修正B明确提交使用新key', async () => {
  vi.mocked(api.importQuestion).mockRejectedValueOnce(new ApiError(422, 'validation_error', '题目不合规范')).mockResolvedValueOnce(detail())
  const w = await page()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(w.text()).toContain('题目不合规范'))
  const b = { ...body, question: { ...body.question, title: '修正B' } }
  await w.get('textarea').setValue(JSON.stringify(b))
  await w.get('input[type="checkbox"]').setValue(true)
  expect(w.get('[data-testid="import-submit"]').attributes('disabled')).toBeUndefined()
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(api.importQuestion).toHaveBeenCalledTimes(2))
  const calls = vi.mocked(api.importQuestion).mock.calls
  expect(calls[0]?.[2]).not.toBe(calls[1]?.[2])
  expect(calls[0]?.[1]).toEqual(body)
  expect(calls[1]?.[1]).toEqual(b)
})

it('分支配额失败原A保留，B未伪称持久；显式采用保留A且不自动导入', async () => {
  const { ImportWriteRecovery } = await import('../src/import-write-recovery')
  const a = new ImportWriteRecovery(ME), b = new ImportWriteRecovery(ME)
  const source = await b.load()
  const textA = JSON.stringify(body), textB = JSON.stringify({ ...body, question: { ...body.question, title: '持久分支B' } })
  await a.save(textA, source.generation)
  const original = Storage.prototype.setItem
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key, value) {
    if (key.startsWith('admin-import-draft/')) throw new DOMException('quota', 'QuotaExceededError')
    return original.call(this, key, value)
  })
  await expect(b.save(textB, source.generation)).rejects.toThrow('quota')
  spy.mockRestore()
  const noBranch = await a.load()
  expect(noBranch.raw).toBe(textA)
  expect(noBranch.branches).toHaveLength(0)
  await b.save(textB, source.generation)
  const w = await page()
  await vi.waitFor(() => expect(w.findAll('[data-testid^="import-branch-"]')).toHaveLength(1))
  await w.get('[data-testid^="import-branch-"]').trigger('click')
  await vi.waitFor(() => expect(w.get('textarea').element.value).toBe(textB))
  await w.get('input[type="checkbox"]').setValue(true)
  expect(w.get('[data-testid="import-submit"]').attributes('disabled')).toBeDefined()
  expect(api.importQuestion).not.toHaveBeenCalled()
  await w.get('[data-testid="import-promote-branch"]').trigger('click')
  await vi.waitFor(async () => expect((await a.load()).raw).toBe(textB))
  expect((await a.load()).branches.some(branch => branch.raw === textA)).toBe(true)
  expect(api.importQuestion).not.toHaveBeenCalled()
})

it('rejected写失败时原422命令仍未知，不放行修正B', async () => {
  const original = Storage.prototype.setItem
  const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function(this: Storage, key, value) {
    if (key.startsWith('admin-write/') && value.includes('"phase":"rejected"')) throw new DOMException('quota', 'QuotaExceededError')
    return original.call(this, key, value)
  })
  vi.mocked(api.importQuestion).mockRejectedValue(new ApiError(422, 'validation_error', '未执行校验失败'))
  const w = await page()
  await w.get('textarea').setValue(JSON.stringify(body))
  await w.get('input[type="checkbox"]').setValue(true)
  await w.get('[data-testid="import-submit"]').trigger('click')
  await vi.waitFor(() => expect(w.text()).toContain('输入与原命令保留'))
  await w.get('textarea').setValue(JSON.stringify({ ...body, question: { ...body.question, title: '修正B' } }))
  await w.get('input[type="checkbox"]').setValue(true)
  expect(w.get('[data-testid="import-submit"]').attributes('disabled')).toBeDefined()
  const { WriteCommandStore, browserLocks } = await import('../src/api/write-command-store')
  expect((await new WriteCommandStore(localStorage, browserLocks(), ME).list())[0]?.phase).toBe('prepared')
  expect(api.importQuestion).toHaveBeenCalledTimes(1)
  spy.mockRestore()
})

it('载入B后主稿变化不能隐式重基采用，双方原文均留存', async () => {
  const { ImportWriteRecovery } = await import('../src/import-write-recovery')
  const a = new ImportWriteRecovery(ME), b = new ImportWriteRecovery(ME)
  await a.save('A', 0)
  const conflict = await b.save('B', 0)
  const branch = conflict.branches.find(item => item.raw === 'B')!
  const choosingGeneration = conflict.generation
  await a.save('C', choosingGeneration)
  await expect(b.promoteBranch(branch.id, choosingGeneration)).rejects.toThrow('变化')
  const restored = await b.load()
  expect(restored.raw).toBe('C')
  expect(restored.branches.find(item => item.id === branch.id)?.raw).toBe('B')
})
