import { webcrypto } from 'node:crypto'
import { defineComponent, h, ref, watch } from 'vue'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { QuestionWriteRecovery, useQuestionCommands } from '../src/question-write-recovery'
import { setSession } from '../src/session'

enableAutoUnmount(afterEach)
afterEach(() => vi.unstubAllGlobals())

const owner = 'head-preview-owner'
const source = { id: 'head-preview-question', version: 1, reviewRevision: 1 }
const envelope = (title: string) => JSON.stringify({ source, form: { title } })

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.stubGlobal('crypto', webcrypto)
  const tails = new Map<string, Promise<unknown>>()
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: <T>(name: string, _options: unknown, action: () => Promise<T>) => {
        const next = (tails.get(name) ?? Promise.resolve()).catch(() => {}).then(action)
        tails.set(name, next)
        return next
      },
    },
  })
  setSession({ token: 'synthetic-head-preview', userId: owner, role: 'reviewer' })
})

async function scenario() {
  const disk = new QuestionWriteRecovery(owner, source.id, 'edit')
  const head = await disk.save(envelope('A'), 0)
  const conflict = await disk.save(envelope('B'), 0)
  const branch = conflict.branches.find(b => b.raw === envelope('B'))!
  let recovery!: ReturnType<typeof useQuestionCommands>
  const form = ref({ title: 'initial' })
  const wrapper = mount(defineComponent({
    setup() {
      recovery = useQuestionCommands('edit', source, () => ({ ...form.value }), value => {
        form.value = value as { title: string }
      })
      watch(form, () => recovery.changed(), { deep: true })
      return () => h('section', [
        h('pre', { 'data-testid': 'head' }, recovery.headRaw.value),
        h('span', { 'data-testid': 'form' }, form.value.title),
      ])
    },
  }))
  await vi.waitFor(() => expect(recovery.loaded.value).toBe(true))
  expect(wrapper.get('[data-testid=head]').text()).toBe(envelope('A'))
  const otherTab = new QuestionWriteRecovery(owner, source.id, 'edit')
  await otherTab.save(envelope('C'), head.generation)
  await recovery.loadBranch(branch.id)
  expect(form.value.title).toBe('B')
  expect((await disk.load()).raw).toBe(envelope('C'))
  return { disk, wrapper, recovery }
}

it('loading branch B previews the freshly read head C used by its selection CAS', async () => {
  const { wrapper } = await scenario()
  expect(wrapper.get('[data-testid=head]').text()).toBe(envelope('C'))
})

it('adopting B updates the current-head preview and preserves previous head C', async () => {
  const { disk, wrapper, recovery } = await scenario()
  await recovery.adopt()
  const persisted = await disk.load()
  expect(persisted.raw).toBe(envelope('B'))
  expect(persisted.branches.some(b => b.raw === envelope('C'))).toBe(true)
  expect(wrapper.get('[data-testid=head]').text()).toBe(envelope('B'))
})
