import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { components } from '../src/api/schema'
import QuestionProvenance from '../src/components/QuestionProvenance.vue'
import QuestionCompareView from '../src/views/QuestionCompareView.vue'
import QuestionView from '../src/views/QuestionView.vue'
import * as api from '../src/api/admin'
import { clearSession, setSession } from '../src/session'
import { detail, snapshot, ME, QUESTION_ID } from './fixtures'
import { installBrowserStorage } from './support/browser-storage'

type Provenance = components['schemas']['QuestionProvenance']
function provenance(overrides: Partial<Provenance> = {}): Provenance {
  return { source_snapshot: { ...detail().source, source_name: '固定来源' }, origins: [
    { file_sha256: 'a'.repeat(64), file_kind: 'pdf', locator_kind: 'pdf_page', index: 2, declared_block: 3 },
  ], relation: 'declared', parent_version: null, access: 'metadata_only', ...overrides }
}
enableAutoUnmount(afterEach)
vi.mock('../src/api/admin', () => ({ getQuestion: vi.fn(), getQuestionVersion: vi.fn() }))
beforeEach(() => { installBrowserStorage(); vi.resetAllMocks(); clearSession(); setSession({ token: 'tok', userId: ME, role: 'reviewer' }) })
it('shows fixed source and metadata with declared uncertainty, without links', () => {
  const wrapper = mount(QuestionProvenance, { props: { provenance: provenance() } })
  expect(wrapper.text()).toContain('固定来源')
  expect(wrapper.text()).toContain('PDF 物理页 2')
  expect(wrapper.text()).toContain('声明块序 3')
  expect(wrapper.text()).toContain('未精确验证')
  expect(wrapper.text()).toContain('仅元数据')
  expect(wrapper.text()).toContain('a'.repeat(64))
  expect(wrapper.find('a, button, iframe, img').exists()).toBe(false)
})
it('names Word ordered fragments separately from physical pages', () => {
  const value = provenance({ origins: [{ file_sha256: 'b'.repeat(64), file_kind: 'docx', locator_kind: 'word_fragment', index: 4, declared_block: null }] })
  const wrapper = mount(QuestionProvenance, { props: { provenance: value } })
  expect(wrapper.text()).toContain('Word 有序片段 4')
  expect(wrapper.text()).not.toContain('物理页')
})
it.each([undefined, null])('old absent metadata stays absent (%s)', (value) => {
  const wrapper = mount(QuestionProvenance, { props: { provenance: value } })
  expect(wrapper.text()).toContain('暂无导入定位记录')
  expect(wrapper.text()).not.toContain('固定来源')
})
it('shows derived relation with parent and distinguishes image and JSON', () => {
  const value = provenance({ relation: 'derived_unverified', parent_version: 1, origins: [
    { file_sha256: 'c'.repeat(64), file_kind: 'png', locator_kind: 'image_page', index: 1, declared_block: null },
    { file_sha256: 'd'.repeat(64), file_kind: 'json', locator_kind: 'json_fragment', index: 2, declared_block: null },
  ] })
  const wrapper = mount(QuestionProvenance, { props: { provenance: value } })
  expect(wrapper.text()).toContain('编辑派生，未重新验证')
  expect(wrapper.text()).toContain('父版本：1')
  expect(wrapper.text()).toContain('图片页 1')
  expect(wrapper.text()).toContain('JSON 片段 2')
})
async function mountView(compare: boolean) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/questions/:id', name: 'question', component: QuestionView },
    { path: '/questions/:id/compare', name: 'compare', component: QuestionCompareView },
    { path: '/', name: 'queue', component: { template: '<div />' } },
  ] })
  await router.push(`/questions/${QUESTION_ID}${compare ? '/compare?from=1&to=2' : ''}`)
  await router.isReady()
  const wrapper = mount(compare ? QuestionCompareView : QuestionView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}
it('question page displays only its own fixed provenance', async () => {
  vi.mocked(api.getQuestion).mockResolvedValue(detail({ provenance: provenance() }))
  const wrapper = await mountView(false)
  expect(wrapper.findComponent(QuestionProvenance).text()).toContain('固定来源')
})
it('comparison uses each version snapshot, without borrowing current metadata for v1', async () => {
  vi.mocked(api.getQuestion).mockResolvedValue(detail({ version: 2, provenance: provenance() }))
  vi.mocked(api.getQuestionVersion).mockImplementation(async (_token, _id, version) => snapshot({ version, provenance: version === 1 ? null : provenance({ relation: 'derived_unverified', parent_version: 1 }) }))
  const wrapper = await mountView(true)
  const panels = wrapper.findAllComponents(QuestionProvenance)
  expect(panels).toHaveLength(2)
  expect(panels[0]!.text()).toContain('暂无导入定位记录')
  expect(panels[0]!.text()).not.toContain('固定来源')
  expect(panels[1]!.text()).toContain('固定来源')
  expect(panels[1]!.text()).toContain('父版本：1')
})

function deferredSnapshot() {
  let resolve!: (value: ReturnType<typeof snapshot>) => void
  const promise = new Promise<ReturnType<typeof snapshot>>((done) => { resolve = done })
  return { promise, resolve }
}
function setupDeferredComparison() {
  const pending3 = deferredSnapshot(), pending4 = deferredSnapshot()
  vi.mocked(api.getQuestion).mockResolvedValue(detail({ version: 4 }))
  vi.mocked(api.getQuestionVersion).mockImplementation(async (_token, _id, version) => {
    if (version === 3) return pending3.promise
    if (version === 4) return pending4.promise
    return snapshot({ version, provenance: provenance({ source_snapshot: { ...detail().source, source_name: `来源v${version}` } }) })
  })
  return { pending3, pending4 }
}
it('pending version selection keeps the retained provenance labelled by its actual snapshot', async () => {
  const { pending3 } = setupDeferredComparison()
  const wrapper = await mountView(true)
  await wrapper.vm.$router.push({ query: { from: '1', to: '3' } })
  await flushPromises()
  const column = wrapper.find('.provenance-columns > div:last-child')
  expect(column.find('h2').text()).toBe('第 2 版来源')
  expect(column.text()).toContain('来源v2')
  pending3.resolve(snapshot({ version: 3, provenance: provenance() }))
  await flushPromises()
  expect(wrapper.find('.provenance-columns > div:last-child > h2').text()).toBe('第 3 版来源')
})
it('a late earlier response cannot replace the latest requested provenance snapshot', async () => {
  const { pending3, pending4 } = setupDeferredComparison()
  const wrapper = await mountView(true)
  await wrapper.vm.$router.push({ query: { from: '1', to: '3' } })
  await flushPromises()
  await wrapper.vm.$router.push({ query: { from: '1', to: '4' } })
  await flushPromises()
  pending4.resolve(snapshot({ version: 4, provenance: provenance({ source_snapshot: { ...detail().source, source_name: '来源v4' } }) }))
  await flushPromises()
  pending3.resolve(snapshot({ version: 3, provenance: provenance({ source_snapshot: { ...detail().source, source_name: '来源v3' } }) }))
  await flushPromises()
  const column = wrapper.find('.provenance-columns > div:last-child')
  expect(column.find('h2').text()).toBe('第 4 版来源')
  expect(column.text()).toContain('来源v4')
  expect(column.text()).not.toContain('来源v3')
})
