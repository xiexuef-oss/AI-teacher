import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../src/api/admin'
import { ApiError } from '../src/api/client'
import { clearSession, setSession } from '../src/session'
import QuestionView from '../src/views/QuestionView.vue'
import { AUTHOR, detail, ME, QUESTION_ID, writtenDetail } from './fixtures'

vi.mock('../src/api/admin', () => ({
  getHealth: vi.fn(),
  createLocalIdentity: vi.fn(),
  listQuestions: vi.fn(),
  getQuestion: vi.fn(),
  reviewQuestion: vi.fn(),
  createQuestionVersion: vi.fn(),
}))

const mocked = vi.mocked(api)

async function openPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'queue', component: { template: '<div />' } },
      { path: '/questions/:id', name: 'question', component: QuestionView },
      { path: '/questions/:id/compare', name: 'compare', component: { template: '<div />' } },
    ],
  })
  await router.push(`/questions/${QUESTION_ID}`)
  await router.isReady()
  const wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.resetAllMocks()
  clearSession()
  setSession({ token: 'tok', userId: ME, role: 'reviewer' })
})

describe('编辑题目', () => {
  it('待审的题有"编辑题目"按钮；点了出现编辑器，决策面板先收起来', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    const wrapper = await openPage()

    expect(wrapper.find('[data-testid="decision-panel"]').exists()).toBe(true)
    await wrapper.get('[data-testid="edit"]').trigger('click')

    expect(wrapper.find('[data-testid="editor"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="decision-panel"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="title"]').element).toHaveProperty('value', '绝对值函数的单调递减区间')
    expect(wrapper.text()).toContain('保存后是第 2 版')
  })

  it('已上线的题不能直接改：按钮不可用，说明先下线', async () => {
    mocked.getQuestion.mockResolvedValue(detail({ status: 'published' }))
    const wrapper = await openPage()

    expect(wrapper.get('[data-testid="edit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('先下线')
  })

  it('没改动时不能保存；改了标题之后可以，请求里带着当前版本、全部内容和幂等键', async () => {
    const saved = detail({ version: 2, title: '新的标题', created_by: ME })
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.createQuestionVersion.mockResolvedValue(saved)
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')

    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="unchanged"]').exists()).toBe(true)

    await wrapper.get('[data-testid="title"]').setValue('新的标题')
    await wrapper.get('[data-testid="comment"]').setValue('标题更具体')
    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    expect(mocked.createQuestionVersion).toHaveBeenCalledTimes(1)
    const [token, id, body, key] = mocked.createQuestionVersion.mock.calls[0]!
    expect([token, id]).toEqual(['tok', QUESTION_ID])
    expect(body.expected_version).toBe(1)
    expect(body.title).toBe('新的标题')
    expect(body.comment).toBe('标题更具体')
    expect(body.content.stem).toContain('|x-1|')
    expect(body.solutions.map((item) => item.kind)).toEqual(['standard'])
    expect(key.length).toBeGreaterThanOrEqual(8)

    // 保存成功：编辑器收起，显示新版本，提示要另一位审校员二审；改的人自己不能二审
    expect(wrapper.find('[data-testid="editor"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="done"]').text()).toContain('第 2 版')
    expect(wrapper.text()).toContain('新的标题')
    expect(wrapper.get('[data-testid="blocked"]').text()).toContain('提交者')
  })

  it('改选项的正确答案：请求里的答案跟着变', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.createQuestionVersion.mockResolvedValue(detail({ version: 2 }))
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')

    await wrapper.get('[data-testid="option-correct-0"]').setValue(false)
    await wrapper.get('[data-testid="option-correct-1"]').setValue(true)
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    expect(mocked.createQuestionVersion.mock.calls[0]![2].answer.value).toEqual(['B'])
  })

  it('填了不合法的 JSON：列出原因，不能保存', async () => {
    mocked.getQuestion.mockResolvedValue(
      detail({ answer_mode: 'fill', type: 'fill_blank', content: { stem: '填空 ____', options: [], blanks: [{ key: 'b1', label: null, unit_hint: null, placeholder: null }], subquestions: [], attachments: [] }, answer: { value: { b1: '5' }, equivalence_rules: {}, units: {} } }),
    )
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')

    await wrapper.get('[data-testid="rules"]').setValue('{坏了')

    expect(wrapper.get('[data-testid="editor-errors"]').text()).toContain('判定规则不是合法的 JSON')
    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeDefined()
  })

  it('服务端拒绝：显示原因；字段级的问题逐条列出', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.createQuestionVersion.mockRejectedValue(
      new ApiError(422, 'validation_error', '请求字段不合法', {
        errors: [{ field: 'knowledge', message: '知识点不存在，或不属于这道题的学科：math.no.such', type: 'value_error' }],
      }),
    )
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await wrapper.get('[data-testid="knowledge"]').setValue('math.no.such')

    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const shown = wrapper.get('[data-testid="save-error"]').text()
    expect(shown).toContain('请求字段不合法')
    expect(shown).toContain('knowledge：知识点不存在')
    expect(wrapper.find('[data-testid="editor"]').exists()).toBe(true) // 输入的内容还在，不丢
  })

  it('别人刚改过（409）：提示刷新，点了重新加载题目', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.createQuestionVersion.mockRejectedValue(
      new ApiError(409, 'version_conflict', '题目已经是第 2 版', { current_version: 2 }),
    )
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await wrapper.get('[data-testid="title"]').setValue('我的修改')

    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="save-error"]').text()).toContain('版本已经变了')

    await wrapper.get('[data-testid="save-error"] button.link').trigger('click')
    await flushPromises()
    expect(mocked.getQuestion).toHaveBeenCalledTimes(2)
  })

  it('网络失败后重试同一份内容：复用幂等键；内容变了就换一个', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.createQuestionVersion.mockRejectedValue(new ApiError(0, 'network_error', '连不上服务器'))
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await wrapper.get('[data-testid="title"]').setValue('第一版内容')

    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="title"]').setValue('改了主意')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const keys = mocked.createQuestionVersion.mock.calls.map((call) => call[3])
    expect(keys[0]).toBe(keys[1])
    expect(keys[2]).not.toBe(keys[0])
  })

  it('放弃修改：回到原来的页面，不调用接口', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await wrapper.get('[data-testid="title"]').setValue('不要了')

    await wrapper.get('[data-testid="cancel"]').trigger('click')

    expect(wrapper.find('[data-testid="editor"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="decision-panel"]').exists()).toBe(true)
    expect(mocked.createQuestionVersion).not.toHaveBeenCalled()
  })

  it('审核历史里的"修改"：显示改动了哪些部分和修改说明', async () => {
    mocked.getQuestion.mockResolvedValue(
      detail({
        version: 2,
        history: [
          {
            id: 'e1',
            action: 'edit',
            actor_id: AUTHOR,
            from_status: 'draft',
            to_status: 'draft',
            version: 2,
            comment: '标题更具体',
            changes: ['title', 'content'],
            created_at: '2026-11-11T09:00:00Z',
          },
        ],
      }),
    )
    const wrapper = await openPage()

    const history = wrapper.get('[data-testid="history"]').text()
    expect(history).toContain('修改（新版本）')
    expect(history).toContain('改动了：标题、题面')
    expect(history).toContain('标题更具体')
  })
})

describe('编辑解答题', () => {
  async function openEditor(source = writtenDetail()) {
    mocked.getQuestion.mockResolvedValue(source)
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    return wrapper
  }

  it('编辑器里是小问、参考答案和自查要点；没有选项、空位，也没有评分细则的 JSON', async () => {
    const wrapper = await openEditor()

    expect(wrapper.find('[data-testid="subquestions"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="points"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="options"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blanks"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rubric-json"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="subquestion-answer-1"]').element).toHaveProperty(
      'value',
      '最大值 $3$，最小值 $-1$',
    )
    expect(wrapper.get('[data-testid="point-part-3"]').element).toHaveProperty('value', '')
    expect(wrapper.get('[data-testid="points"]').text()).toContain('不是评分')
  })

  it('选择题和填空题的编辑器里没有小问和自查要点', async () => {
    const wrapper = await openEditor(detail())

    expect(wrapper.find('[data-testid="subquestions"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="points"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rubric-json"]').exists()).toBe(true)
  })

  it('每条要点的"所属小问"下拉里有每个小问和"整份解答"', async () => {
    const wrapper = await openEditor()

    const options = wrapper.get('[data-testid="point-part-0"]').findAll('option')
    expect(options.map((option) => option.element.value)).toEqual(['', '1', '2'])
    expect(options[0]!.text()).toBe('整份解答')
  })

  it('改一个小问的参考答案再保存：请求里的小问、参考答案、自查要点都在，要点不带分值', async () => {
    mocked.createQuestionVersion.mockResolvedValue(writtenDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="subquestion-answer-0"]').setValue('$a \\le 1$')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const [token, id, body, key] = mocked.createQuestionVersion.mock.calls[0]!
    expect([token, id]).toEqual(['tok', QUESTION_ID])
    expect(key).toMatch(/\S{8,}/)
    expect(body.answer.value).toEqual({ '1': '$a \\le 1$', '2': '最大值 $3$，最小值 $-1$' })
    expect(body.content.subquestions.map((sub) => [sub.key, sub.answer_mode])).toEqual([
      ['1', 'written'],
      ['2', 'written'],
    ])
    const points = (body.rubric as unknown as { points: object[] }).points
    expect(points).toHaveLength(4)
    for (const point of points) expect(Object.keys(point).sort()).toEqual(['key', 'part', 'text'])
  })

  it('加一个小问，再加一条归到它名下的自查要点', async () => {
    mocked.createQuestionVersion.mockResolvedValue(writtenDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="add-subquestion"]').trigger('click')
    await wrapper.get('[data-testid="subquestion-key-2"]').setValue('3')
    await wrapper.get('[data-testid="subquestion-stem-2"]').setValue('再求……')
    await wrapper.get('[data-testid="subquestion-answer-2"]').setValue('略')
    await wrapper.get('[data-testid="add-point"]').trigger('click')
    await wrapper.get('[data-testid="point-key-4"]').setValue('p5')
    await wrapper.get('[data-testid="point-part-4"]').setValue('3')
    await wrapper.get('[data-testid="point-text-4"]').setValue('第 (3) 问的结论')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const body = mocked.createQuestionVersion.mock.calls[0]![2]
    expect(body.content.subquestions.map((sub) => sub.key)).toEqual(['1', '2', '3'])
    expect(body.answer.value).toMatchObject({ '3': '略' })
    const points = (body.rubric as unknown as { points: { key: string; part: string | null }[] }).points
    expect(points.at(-1)).toEqual({ key: 'p5', part: '3', text: '第 (3) 问的结论' })
  })

  it('删掉一条自查要点：请求里就少一条', async () => {
    mocked.createQuestionVersion.mockResolvedValue(writtenDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="point-delete-1"]').trigger('click')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const body = mocked.createQuestionVersion.mock.calls[0]![2]
    const points = (body.rubric as unknown as { points: { key: string }[] }).points
    expect(points.map((point) => point.key)).toEqual(['p1', 'p3', 'p4'])
  })
})
