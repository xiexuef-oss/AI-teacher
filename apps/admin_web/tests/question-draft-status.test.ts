import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import QuestionEditor from '../src/components/QuestionEditor.vue'
import DecisionPanel from '../src/components/DecisionPanel.vue'
import { setSession } from '../src/session'
import { detail, ME } from './fixtures'
import { flushRecovery, installBrowserStorage } from './support/browser-storage'

enableAutoUnmount(afterEach)
vi.mock('../src/api/admin', () => ({ createQuestionVersion: vi.fn(), reviewQuestion: vi.fn() }))
beforeEach(() => {
  localStorage.clear()
  installBrowserStorage()
  setSession({ token: 'synthetic-save-state', userId: ME, role: 'reviewer' })
})
it('editor reports durable local edits separately from untouched server content', async () => {
  const w = mount(QuestionEditor, { props: { detail: detail() } })
  await flushRecovery()
  expect(w.get('[data-testid=edit-draft-state]').text()).toContain('尚未编辑')
  await w.get('[data-testid=title]').setValue('已落本机的自编修改')
  await flushRecovery()
  expect(w.get('[data-testid=edit-draft-state]').text()).toContain('本机草稿已保存')
})
it('reviewer can observe when an opinion is saved locally before submitting', async () => {
  const w = mount(DecisionPanel, { props: { detail: detail() } })
  await flushRecovery()
  expect(w.get('[data-testid=review-draft-state]').text()).toContain('尚未编辑')
  await w.get('[data-testid=comment]').setValue('已落本机的自查意见')
  await flushRecovery()
  expect(w.get('[data-testid=review-draft-state]').text()).toContain('本机草稿已保存')
})
