import {installBrowserStorage,flushRecovery as flushPromises} from './support/browser-storage'
import { mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../src/api/document-import'
import DocumentImportView from '../src/views/DocumentImportView.vue'
import { clearSession, setSession } from '../src/session'
import { ME } from './fixtures'

vi.mock('../src/api/document-import', () => ({
  importOptions: vi.fn(), listImportJobs: vi.fn(), getImportJob: vi.fn(),
  createImportJob: vi.fn(), uploadImportFile: vi.fn(), processImportJob: vi.fn(),
  cancelImportJob: vi.fn(), saveImportCandidates: vi.fn(), submitImportCandidates: vi.fn(),
  getImportPreview: vi.fn(), getImportOriginal: vi.fn(),
}))

beforeEach(() => {
  installBrowserStorage()
  vi.resetAllMocks()
  setSession({ token: 'tok', userId: ME, role: 'reviewer' })
  vi.mocked(api.importOptions).mockResolvedValue({ server_time:new Date().toISOString(),creation_deadline:new Date(Date.now()+7200000).toISOString(),max_file_bytes: 10485760, max_job_bytes: 52428800,
    max_files: 10, max_pages: 80, max_candidates: 200, temporary_ttl_minutes: 120,
    file_kinds: ['pdf', 'docx', 'doc', 'png', 'jpeg', 'json'], ocr_mode: 'disabled', doc_converter_available: false })
  vi.mocked(api.listImportJobs).mockResolvedValue({ items: [], next_cursor: null })
})

function documentRaw(jobId:string){const key=Object.keys(localStorage).find(k=>k.startsWith('admin-document-state/v1/')&&JSON.parse(localStorage.getItem(k)!).jobId===jobId);return key?localStorage.getItem(key):null}
async function page() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/', component: DocumentImportView },
    { path: '/questions/:id', name: 'question', component: { template: '<div />' } },
  ] })
  await router.push('/')
  await router.isReady()
  const wrapper = mount(DocumentImportView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

it('明确显示 OCR 和 DOC 不可用；没有来源依据不能建立任务', async () => {
  const wrapper = await page()
  expect(wrapper.text()).toContain('OCR 当前禁用')
  expect(wrapper.text()).toContain('另存为 DOCX')
  await wrapper.get('[data-testid="create-job"]').trigger('click')
  expect(api.createImportJob).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('来源')
  wrapper.unmount()
})

it('刷新后重试未返回的批次，复用原请求修订号、候选和幂等键', async () => {
  const job = { id: 'job-1', title: '恢复任务', status: 'needs_review' as const, revision: 9,
    file_count: 0, processed_files: 0, candidate_count: 0, confirmed_count: 0,
    imported_count: 0, failed_count: 0, message: null, created_at: '', updated_at: '', expires_at: new Date(Date.now()+60000).toISOString() }
  vi.mocked(api.getImportJob).mockResolvedValue({ job, files: [], candidates: [], defaults: {
    subject: 'math', answer_mode: 'single_choice', source: { source_type: 'self_authored',
      source_category: 'foundation', source_name: '自编', source_license: '自编测试', source_year: null, source_url: null } } })
  const body = { expected_revision: 3, candidate_ids: ['candidate-1'] }
  localStorage.setItem(`document-import:${ME}:expires`, String(Date.now() + 60000))
  localStorage.setItem(`document-import:${ME}:job`, job.id)
  localStorage.setItem(`document-import:${ME}:requests`, JSON.stringify({
    'job-1:submit': { key: 'stable-batch-key', body },
  }))
  vi.mocked(api.submitImportCandidates).mockRejectedValue(new Error('网络中断'))
  const wrapper = await page()
  const button = wrapper.get('[data-testid=doc-retry]')
  await button.trigger('click'); await flushPromises()
  await button.trigger('click'); await flushPromises()
  expect(api.submitImportCandidates).toHaveBeenCalledTimes(2)
  expect(api.submitImportCandidates).toHaveBeenLastCalledWith('tok', job.id, body, 'stable-batch-key')
  wrapper.unmount()
  localStorage.clear()
})


it('过期内容仅清除当前用户，退出保留未知命令证据且不影响其他用户', async () => {
  localStorage.setItem(`document-import:${ME}:expires`, '1')
  localStorage.setItem(`document-import:${ME}:job`, 'expired-job')
  localStorage.setItem(`document-import:${ME}:edits:expired-job`, 'private text')
  localStorage.setItem('document-import:other:job', 'other-job')
  const wrapper = await page()
  expect(api.getImportJob).not.toHaveBeenCalled()
  expect(localStorage.getItem(`document-import:${ME}:edits:expired-job`)).toBeNull()
  expect(localStorage.getItem('document-import:other:job')).toBe('other-job')
  localStorage.setItem(`document-import:${ME}:requests`, 'private')
  clearSession()
  expect(localStorage.getItem(`document-import:${ME}:requests`)).toBe('private')
  expect(localStorage.getItem('document-import:other:job')).toBe('other-job')
  wrapper.unmount()
  localStorage.clear()
})


import type { components } from '../src/api/schema'
function workspace(count = 1): components['schemas']['DocImportJobDetail'] {
  return { job: { id: 'work', title: '工作区', status: 'needs_review', revision: 1, file_count: 0,
    processed_files: 0, candidate_count: count, confirmed_count: count, imported_count: 0, failed_count: 0,
    message: null, created_at: '', updated_at: '', expires_at: new Date(Date.now() + 60000).toISOString() },
    defaults: { subject: 'physics', answer_mode: 'written', source: { source_type: 'self_authored',
      source_category: 'foundation', source_name: '来源继承', source_license: '授权依据', source_year: null, source_url: null } },
    files: [], candidates: Array.from({length: count}, (_, i) => ({ id: 'c' + i, title: '标题' + i,
      text: '校对题文', locations: [], warnings: [], payload: null, confirmed: true,
      confirmed_by: ME, question_id: null, error: null })) }
}
async function restored(value: components['schemas']['DocImportJobDetail']) {
  localStorage.clear()
  // Fixture reset must restore the real persisted identity used by binding guards.
  setSession({ token: 'tok', userId: ME, role: 'reviewer' })
  localStorage.setItem(`document-import:${ME}:expires`, String(Date.now() + 60000))
  localStorage.setItem(`document-import:${ME}:job`, value.job.id)
  vi.mocked(api.getImportJob).mockResolvedValue(value)
  return page()
}
it('51题每批最多提交50题，提示继续下一批', async () => {
  vi.mocked(api.submitImportCandidates).mockRejectedValue(new Error('故意暂停'))
  const wrapper = await restored(workspace(51))
  await wrapper.findAll('button').find(b => b.text().startsWith('批量创建'))!.trigger('click')
  await flushPromises()
  expect(vi.mocked(api.submitImportCandidates).mock.calls[0]![2].candidate_ids).toHaveLength(50)
  expect(wrapper.text()).toContain('每次最多50题')
  wrapper.unmount(); localStorage.clear()
})
it('骨架继承来源学科与校对题文，答案教学留空且不自动确认', async () => {
  const wrapper = await restored(workspace())
  await wrapper.findAll('button').find(b => b.text().includes('生成可编辑题目骨架'))!.trigger('click')
  const body = JSON.parse(wrapper.findAll('textarea')[1]!.element.value)
  expect(body.subject).toBe('physics')
  expect(body.answer_mode).toBe('written')
  expect(body.source.source_name).toBe('来源继承')
  expect(body.question.content.stem).toBe('校对题文')
  expect(body.question.answer.value).toBeNull()
  expect(body.question.teaching.hints).toEqual([])
  expect(body.question.solutions).toEqual([])
  expect(wrapper.find<HTMLInputElement>('input[type=checkbox]').element.checked).toBe(false)
  wrapper.unmount(); localStorage.clear()
})
it('多图逐索引预览，原文件经授权下载后释放objectURL', async () => {
  const value = workspace(0)
  value.files = [{id:'f',filename:'原文.docx',kind:'docx',media_type:'application/octet-stream',size_bytes:10,
    sha256:'hash',status:'ready',problems:[],original_available:true,pages:[{number:1,text:'原文',method:'docx_text',warnings:[],confidence:null,media_refs:['a','b']}]}]
  vi.mocked(api.getImportPreview).mockResolvedValue({filename:'p.png',media_type:'image/png',content_base64:'aA=='})
  vi.mocked(api.getImportOriginal).mockResolvedValue({filename:'原文.docx',media_type:'application/octet-stream',content_base64:'aA=='})
  Object.defineProperty(URL, 'createObjectURL', { configurable:true,value:vi.fn(() => 'blob:test') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable:true,value:vi.fn() })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  const wrapper = await restored(value)
  await wrapper.findAll('button').find(b => b.text().includes('图片 2'))!.trigger('click'); await flushPromises()
  expect(api.getImportPreview).toHaveBeenCalledWith('tok','work','f',1,1)
  await wrapper.findAll('button').find(b => b.text().includes('下载原文件'))!.trigger('click'); await flushPromises()
  expect(api.getImportOriginal).toHaveBeenCalledWith('tok','work','f')
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
  expect(click).toHaveBeenCalled()
  click.mockRestore(); wrapper.unmount(); localStorage.clear()
})


it('逐题学科题型来源表单与JSON双向同步，任何修改取消确认并保存本机草稿', async () => {
  const wrapper = await restored(workspace())
  await wrapper.findAll('button').find(b => b.text().includes('生成可编辑题目骨架'))!.trigger('click')
  const form = wrapper.get('[data-testid="candidate-metadata"]')
  await form.get('[data-testid="candidate-subject"]').setValue('chemistry')
  await form.get('[data-testid="candidate-mode"]').setValue('experiment')
  await form.get('[data-testid="candidate-source-name"]').setValue('逐题来源')
  await form.get('[data-testid="candidate-license"]').setValue('逐题授权')
  await form.get('[data-testid="candidate-source-type"]').setValue('public_license')
  await form.get('[data-testid="candidate-category"]').setValue('mock_exam')
  await form.get('[data-testid="candidate-year"]').setValue('2026')
  await form.get('[data-testid="candidate-url"]').setValue('https://example.org/authorized')
  let body = JSON.parse(wrapper.findAll('textarea')[1]!.element.value)
  expect(body.subject).toBe('chemistry'); expect(body.answer_mode).toBe('experiment')
  expect(body.source).toMatchObject({source_name:'逐题来源',source_license:'逐题授权',source_type:'public_license',source_category:'mock_exam',source_year:2026,source_url:'https://example.org/authorized'})
  await wrapper.find('input[type=checkbox]').setValue(true)
  body.subject = 'math'; body.source.source_name = 'JSON修改来源'
  await wrapper.findAll('textarea')[1]!.setValue(JSON.stringify(body))
  expect(wrapper.get<HTMLSelectElement>('[data-testid="candidate-subject"]').element.value).toBe('math')
  expect(wrapper.get<HTMLInputElement>('[data-testid="candidate-source-name"]').element.value).toBe('JSON修改来源')
  expect(wrapper.find<HTMLInputElement>('input[type=checkbox]').element.checked).toBe(false)
  await flushPromises()
  expect(documentRaw('work')).toContain('JSON修改来源')
  expect(Number(localStorage.getItem(`document-import:${ME}:expires`))).toBeLessThanOrEqual(Date.now() + 60000)
  wrapper.unmount(); localStorage.clear()
})


it('人工配对仅添加答案原文位置，清除确认但不向题干或答案填值', async () => {
  const value = workspace()
  value.files = [{id:'answers',filename:'答案.pdf',kind:'pdf',media_type:'application/pdf',size_bytes:10,
    sha256:'hash',status:'ready',problems:[],original_available:true,pages:[{number:2,text:'1. secret',method:'pdf_text',warnings:[],confidence:null,media_refs:[]}]}]
  const wrapper = await restored(value)
  await wrapper.get('[data-testid="answer-location"]').setValue('answers:2')
  await wrapper.get('[data-testid="pair-answer"]').trigger('click')
  expect(wrapper.text()).toContain('answers / 2')
  expect(wrapper.findAll('textarea')[0]!.element.value).toBe('校对题文')
  expect(wrapper.findAll('textarea')[1]!.element.value).toBe('')
  expect(wrapper.find<HTMLInputElement>('input[type=checkbox]').element.checked).toBe(false)
  wrapper.unmount(); localStorage.clear()
})


it('候选可视化编辑复用题目表单，双向同步并撤销确认、本机保留未完成输入', async () => {
  const wrapper = await restored(workspace())
  await wrapper.findAll('button').find(b => b.text().includes('生成可编辑题目骨架'))!.trigger('click')
  await wrapper.get('[data-testid="open-structured-editor"]').trigger('click')
  await wrapper.get('[data-testid="editor"] [data-testid="stem"]').setValue('可视化题干')
  await flushPromises()
  const json = wrapper.get<HTMLTextAreaElement>('[data-testid="candidate-json"]')
  expect(JSON.parse(json.element.value).question.content.stem).toBe('可视化题干')
  expect(wrapper.find<HTMLInputElement>('input[type=checkbox]').element.checked).toBe(false)
  await wrapper.get('[data-testid="editor"] [data-testid="title"]').setValue('')
  await flushPromises()
  expect(documentRaw('work')).toContain('structuredDraft')
  expect(wrapper.get('[data-testid="editor-errors"]').text()).toContain('标题不能为空')
  await wrapper.get('[data-testid="open-structured-editor"]').trigger('click')
  await wrapper.get('[data-testid="open-structured-editor"]').trigger('click')
  expect(wrapper.get<HTMLInputElement>('[data-testid="editor"] [data-testid="title"]').element.value).toBe('')
  const body = JSON.parse(json.element.value); body.question.title = 'JSON改题目'
  await json.setValue(JSON.stringify(body))
  expect(wrapper.get<HTMLInputElement>('[data-testid="editor"] [data-testid="title"]').element.value).toBe('JSON改题目')
  wrapper.unmount(); localStorage.clear()
})

