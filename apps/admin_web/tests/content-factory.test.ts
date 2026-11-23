import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { request } from '../src/api/client'
import { clearSession, setSession } from '../src/session'
import { router } from '../src/router'
import ContentFactoryView from '../src/views/ContentFactoryView.vue'

vi.mock('../src/api/client', () => ({ request: vi.fn() }))

afterEach(() => clearSession())

it('uploads the original only after the editor submits and shows its expiry', async () => {
  const api = vi.mocked(request)
  api.mockReset()
  const id = 'ad7112b5-b99d-4aac-a9fd-19d826f15bfa'
  api.mockResolvedValueOnce({ roles: ['editor'] }).mockResolvedValueOnce({ items: [] })
    .mockResolvedValueOnce({ source_id: id, region_code: 'CN-51', expires_at: '2026-11-24T00:00:00Z' })
  setSession({ token: 'editor-token', userId: 'editor-1', role: 'reviewer' })
  const wrapper = mount(ContentFactoryView, { global: { stubs: ['RouterLink'] } })
  await flushPromises()
  const form = wrapper.get('form[aria-label="上传题源原件"]')
  await form.get('input[name="source_id"]').setValue(id)
  const input = form.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [new File(['test'], 'source.pdf')] })
  await input.trigger('change')
  expect(api.mock.calls.filter(([method]) => method === 'POST')).toHaveLength(0)
  await form.trigger('submit')
  await vi.waitFor(() => expect(wrapper.text()).toContain('原件已暂存'))
  expect(api).toHaveBeenLastCalledWith('POST', `/admin/content-factory/sources/${id}/original`, {
    token: 'editor-token', idempotencyKey: expect.any(String),
    body: { filename: 'source.pdf', content_base64: 'dGVzdA==', region_code: 'CN-51' },
  })
  wrapper.unmount()
})

it('submits, refreshes and cancels a source analysis job', async () => {
  const api = vi.mocked(request)
  api.mockReset()
  const id = '112f1dbb-29f3-45f9-a7bd-813d23f3d843'
  const sourceId = 'ad7112b5-b99d-4aac-a9fd-19d826f15bfa'
  const queued = { id, kind: 'analyze_source', status: 'queued', attempts: 0 }
  api.mockResolvedValueOnce({ roles: ['editor'] }).mockResolvedValueOnce({ items: [] })
    .mockResolvedValueOnce(queued).mockResolvedValueOnce({ ...queued, status: 'running', attempts: 1 })
    .mockResolvedValueOnce({ ...queued, status: 'cancelled', attempts: 1 })
  setSession({ token: 'editor-token', userId: 'editor-1', role: 'reviewer' })
  const wrapper = mount(ContentFactoryView, { global: { stubs: ['RouterLink'] } })
  await flushPromises()
  const submit = wrapper.get('form[aria-label="提交题源分析"]')
  await submit.get('input').setValue(sourceId)
  await submit.trigger('submit')
  await flushPromises()
  expect(api).toHaveBeenLastCalledWith('POST', '/admin/content-factory/jobs', {
    token: 'editor-token', idempotencyKey: expect.any(String),
    body: { kind: 'analyze_source', source_id: sourceId, region_code: 'CN-51' },
  })
  expect(wrapper.text()).toContain('排队中')
  await wrapper.get('form[aria-label="查询教研任务"]').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('执行中')
  await wrapper.get('[data-testid="cancel-content-factory-job"]').trigger('click')
  await flushPromises()
  expect(api).toHaveBeenLastCalledWith('POST', `/admin/content-factory/jobs/${id}/cancel`, {
    token: 'editor-token', idempotencyKey: expect.any(String),
  })
  expect(wrapper.text()).toContain('已取消')
  expect(wrapper.find('[data-testid="cancel-content-factory-job"]').exists()).toBe(false)
  const completedId = '269d239e-b725-4148-b680-d4b1d5d35915'
  api.mockResolvedValueOnce({
    ...queued, id: completedId, status: 'review_required', attempts: 1,
    result: {
      level: 'metadata', source_id: sourceId, title: '工程样张',
      source_class: 'original', sha256: 'a'.repeat(64), region_code: 'CN-51',
      document: {
        pages: 1, text_chars: 80, needs_ocr_pages: 0,
        knowledge_suggestions: [{ knowledge_id: 'node-1', title: '二次函数', subject: 'math', matched_pages: [1] }],
      },
    },
  })
  const lookup = wrapper.get('form[aria-label="查询教研任务"]')
  await lookup.get('input').setValue(completedId)
  await lookup.trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('元数据检查结果')
  expect(wrapper.text()).toContain('工程样张')
  expect(wrapper.text()).toContain('二次函数 · 页码 1')
  wrapper.unmount()
})

it('selects existing knowledge nodes when creating a question type draft', async () => {
  const api = vi.mocked(request)
  api.mockReset()
  api.mockResolvedValueOnce({ roles: ['editor'] })
    .mockResolvedValueOnce({ items: [{ id: 'node-1', code: 'math.algebra', title: '代数' }] })
    .mockResolvedValueOnce({ id: 'type-1', status: 'draft' })
  setSession({ token: 'editor-token', userId: 'editor-1', role: 'reviewer' })
  const wrapper = mount(ContentFactoryView, { global: { stubs: ['RouterLink'] } })
  await flushPromises()
  const form = wrapper.get('form[aria-label="题型草稿"]')
  await form.get('[name="code"]').setValue('math.algebra.practice')
  await form.get('[name="title"]').setValue('代数练习')
  await form.get('[aria-label="代数的关联"]').setValue('primary')
  await form.trigger('submit')
  await flushPromises()
  expect(api).toHaveBeenLastCalledWith('POST', '/admin/content-factory/question-types', {
    token: 'editor-token', idempotencyKey: expect.any(String),
    body: {
      code: 'math.algebra.practice', title: '代数练习', subject: 'math', specification: {},
      knowledge: [{ knowledge_id: 'node-1', relation: 'primary' }],
    },
  })
  expect(form.text()).toContain('type-1')
  api.mockResolvedValueOnce({
    id: 'type-1',
    status: 'draft',
    definition: {
      code: 'math.algebra.practice', title: '代数练习', subject: 'math', specification: {},
      knowledge: [{ knowledge_id: 'node-1', relation: 'primary' }],
    },
  })
  const lookup = wrapper.get('form[aria-label="查询题型"]')
  await lookup.get('input').setValue('type-1')
  await lookup.trigger('submit')
  await flushPromises()
  expect(api).toHaveBeenLastCalledWith('GET', '/admin/content-factory/question-types/type-1', {
    token: 'editor-token',
  })
  expect(wrapper.text()).toContain('代数练习 · 草稿')
  expect(wrapper.text()).toContain('主要 · node-1')
  expect(wrapper.find('form[aria-label="审校题型"]').exists()).toBe(false)
  wrapper.unmount()
})

it('lets reviewers approve and then deprecate a loaded question type', async () => {
  const api = vi.mocked(request)
  api.mockReset()
  const item = {
    id: 'type-1', status: 'draft',
    definition: {
      code: 'math.algebra.practice', title: '代数练习', subject: 'math', specification: {},
      knowledge: [{ knowledge_id: 'node-1', relation: 'primary' }],
    },
  }
  api.mockResolvedValueOnce({ roles: ['reviewer'] }).mockResolvedValueOnce(item)
    .mockResolvedValueOnce({ ...item, status: 'approved' })
    .mockResolvedValueOnce({ ...item, status: 'deprecated' })
  setSession({ token: 'reviewer-token', userId: 'reviewer-1', role: 'reviewer' })
  const wrapper = mount(ContentFactoryView, { global: { stubs: ['RouterLink'] } })
  await flushPromises()
  const lookup = wrapper.get('form[aria-label="查询题型"]')
  await lookup.get('input').setValue(item.id)
  await lookup.trigger('submit')
  await flushPromises()
  const form = wrapper.get('form[aria-label="审校题型"]')
  for (const [decision, notes] of [['approve', '已核对范围'], ['deprecate', '题型已过时']]) {
    await form.get('textarea').setValue(notes)
    await form.trigger('submit')
    await flushPromises()
    expect(api).toHaveBeenLastCalledWith('POST', '/admin/content-factory/question-types/type-1/review', {
      token: 'reviewer-token', idempotencyKey: expect.any(String), body: { decision, notes },
    })
  }
  expect(wrapper.text()).toContain('代数练习 · 已停用')
  expect(wrapper.find('form[aria-label="审校题型"]').exists()).toBe(false)
  wrapper.unmount()
})

it('requires a back-office session and resolves the existing import and review pages', async () => {
  await router.push('/content-factory')
  expect(router.currentRoute.value.name).toBe('login')

  setSession({ token: 'test-token', userId: 'reviewer-1', role: 'reviewer' })
  await router.push('/content-factory')
  expect(router.currentRoute.value.name).toBe('content-factory')
  expect(router.resolve({ name: 'document-import' }).path).toBe('/document-import')
  expect(router.resolve({ name: 'queue' }).path).toBe('/')
})

it('allows only platform admins to submit a role change and retries with the same key', async () => {
  const api = vi.mocked(request)
  api.mockReset()
  api.mockResolvedValueOnce({ roles: [] })
  setSession({ token: 'reviewer-token', userId: 'reviewer-1', role: 'reviewer' })
  const wrapper = mount(ContentFactoryView, { global: { stubs: ['RouterLink'] } })
  expect(wrapper.find('form').exists()).toBe(false)
  api.mockResolvedValueOnce({ roles: [] })
  setSession({ token: 'admin-token', userId: 'admin-1', role: 'admin' })
  await flushPromises()
  await wrapper.get('input').setValue('ad7112b5-b99d-4aac-a9fd-19d826f15bfa')

  api.mockRejectedValueOnce(new Error('连接中断')).mockResolvedValueOnce({ roles: ['editor'] })
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(wrapper.text()).toContain('连接中断')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  const writes = api.mock.calls.filter(([method]) => method === 'POST')
  expect(writes).toHaveLength(2)
  expect(writes[0]).toEqual(writes[1])
  expect(writes[0]?.[2]?.idempotencyKey).toBeTruthy()
  expect(wrapper.text()).toContain('保存成功')
  wrapper.unmount()
})

it('lets editors register source metadata without sending a file or granting permission', async () => {
  const api = vi.mocked(request)
  api.mockReset()
  api.mockResolvedValueOnce({ roles: ['editor'] }).mockResolvedValueOnce({ items: [] })
    .mockResolvedValueOnce({ id: 'source-123' })
  setSession({ token: 'editor-token', userId: 'editor-1', role: 'reviewer' })
  const wrapper = mount(ContentFactoryView, { global: { stubs: ['RouterLink'] } })
  await flushPromises()
  await wrapper.get('input[name="title"]').setValue('自编样张')
  await wrapper.get('input[name="sha256"]').setValue('a'.repeat(64))
  await wrapper.get('form').trigger('submit')
  await flushPromises()
  expect(api).toHaveBeenCalledWith('POST', '/admin/content-factory/sources', {
    token: 'editor-token',
    body: { title: '自编样张', source_class: 'original', sha256: 'a'.repeat(64) },
    idempotencyKey: expect.any(String),
  })
  expect(wrapper.text()).toContain('source-123')
  wrapper.unmount()
})

it('submits a scoped permission grant and revocation from the reviewer workspace', async () => {
  const api = vi.mocked(request)
  api.mockReset()
  const id = 'ad7112b5-b99d-4aac-a9fd-19d826f15bfa'
  api.mockResolvedValueOnce({ roles: ['reviewer'] }).mockResolvedValue({ id })
  setSession({ token: 'reviewer-token', userId: 'reviewer-1', role: 'reviewer' })
  const wrapper = mount(ContentFactoryView, { global: { stubs: ['RouterLink'] } })
  await flushPromises()
  const form = wrapper.get('form')
  await form.get('[name="source_id"]').setValue(id)
  api.mockResolvedValueOnce({
    items: [{
      operation: 'print_pdf', region_code: 'CN-50', status: 'expired', evidence_ref: 'old-license',
      valid_from: '2025-01-01T00:00:00Z', valid_until: '2026-01-01T00:00:00Z',
    }],
  })
  await form.get('button[type="button"]').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('重庆 · 打印 PDF · 已过期')
  expect(wrapper.text()).toContain('old-license')
  await form.get('[name="operation"]').setValue('print_pdf')
  await form.get('[name="evidence_ref"]').setValue('license-1')
  await form.get('[name="valid_from"]').setValue('2026-11-23T10:00')
  await form.get('[name="valid_until"]').setValue('2027-11-23T10:00')
  await form.trigger('submit')
  await flushPromises()
  const scope = { source_id: id, region_code: 'CN-51', operation: 'print_pdf' }
  expect(api).toHaveBeenLastCalledWith('POST', '/admin/content-factory/source-permissions', {
    token: 'reviewer-token', idempotencyKey: expect.any(String),
    body: {
      ...scope, decision: 'grant', evidence_ref: 'license-1',
      valid_from: new Date('2026-11-23T10:00').toISOString(),
      valid_until: new Date('2027-11-23T10:00').toISOString(),
    },
  })
  await form.get('[name="decision"]').setValue('revoke')
  expect(form.find('[name="evidence_ref"]').exists()).toBe(false)
  await form.trigger('submit')
  await flushPromises()
  expect(api).toHaveBeenLastCalledWith('POST', '/admin/content-factory/source-permissions', {
    token: 'reviewer-token', idempotencyKey: expect.any(String), body: { ...scope, decision: 'revoke' },
  })
  expect(wrapper.text()).toContain('许可已撤回')
  wrapper.unmount()
})
