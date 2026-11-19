import {installBrowserStorage,flushRecovery as flushPromises} from './support/browser-storage'
import { mount, enableAutoUnmount } from '@vue/test-utils'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import DecisionPanel from '../src/components/DecisionPanel.vue'
import QuestionEditor from '../src/components/QuestionEditor.vue'
import * as api from '../src/api/admin'
import { setSession } from '../src/session'
import { detail, ME, QUESTION_ID } from './fixtures'

vi.mock('../src/api/admin', () => ({ reviewQuestion: vi.fn(), createQuestionVersion: vi.fn() }))
enableAutoUnmount(afterEach)
beforeEach(() => {
  installBrowserStorage()
  vi.resetAllMocks()
  localStorage.clear()
  setSession({ token: 'test-cas-reviewer', userId: ME, role: 'reviewer' })
})
it('a review sends the revision explicitly observed and confirmed by the reviewer', async () => {
  vi.mocked(api.reviewQuestion).mockResolvedValue({ question_id: QUESTION_ID, version: 1, review_revision: 8, status: 'reviewed', reviewed_by: ME, updated_at: '2026-11-16T00:00:00Z' })
  const w = mount(DecisionPanel, { props: { detail: detail({ review_revision: 7 }) } })
  await flushPromises()
  await w.get('[data-testid="submit-decision"]').trigger('click')
  await flushPromises()
  expect(vi.mocked(api.reviewQuestion).mock.calls[0]?.[2]).toMatchObject({ expected_version: 1, expected_review_revision: 7 })
})
it('legacy review detail without an epoch cannot invent revision one and send', async () => {
  const old = detail()
  delete old.review_revision
  const w = mount(DecisionPanel, { props: { detail: old } })
  expect(w.get('[data-testid="submit-decision"]').attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('审核修订')
  expect(api.reviewQuestion).not.toHaveBeenCalled()
})
it('editing keeps the initial source epoch even if a GET supplies a later review round', async () => {
  vi.mocked(api.createQuestionVersion).mockResolvedValue(detail({ version: 2, review_revision: 10 }))
  const w = mount(QuestionEditor, { props: { detail: detail({ review_revision: 7 }) } })
  await flushPromises()
  await w.get('[data-testid="title"]').setValue('保留旧来源的修改')
  await w.setProps({ detail: detail({ review_revision: 9 }) })
  await w.get('[data-testid="save"]').trigger('click')
  await flushPromises()
  expect(vi.mocked(api.createQuestionVersion).mock.calls[0]?.[2]).toMatchObject({ expected_version: 1, expected_review_revision: 7, title: '保留旧来源的修改' })
})
it('legacy editor keeps local text while refusing a version write with an unknown epoch', async () => {
  const old = detail()
  delete old.review_revision
  const w = mount(QuestionEditor, { props: { detail: old } })
  await flushPromises()
  await w.get('[data-testid="title"]').setValue('本机编辑不得丢失')
  expect(w.get('[data-testid="save"]').attributes('disabled')).toBeDefined()
  expect(w.text()).toContain('审核修订')
  expect(api.createQuestionVersion).not.toHaveBeenCalled()
})


