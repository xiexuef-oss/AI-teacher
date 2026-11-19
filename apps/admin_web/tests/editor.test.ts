import {installBrowserStorage,flushRecovery as flushPromises} from './support/browser-storage'
import { mount,enableAutoUnmount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../src/api/admin'
import { ApiError } from '../src/api/client'
import { clearSession, setSession } from '../src/session'
import QuestionView from '../src/views/QuestionView.vue'
import { AUTHOR, detail, experimentDetail, ME, proofDetail, QUESTION_ID, writtenDetail } from './fixtures'

enableAutoUnmount(afterEach)

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
  installBrowserStorage()
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
    await flushPromises()

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
    mocked.getQuestion.mockResolvedValueOnce(detail()).mockResolvedValue(saved)
    mocked.createQuestionVersion.mockResolvedValue(saved)
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await flushPromises()

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
    await flushPromises()

    await wrapper.get('[data-testid="option-correct-0"]').setValue(false)
    await wrapper.get('[data-testid="option-correct-1"]').setValue(true)
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    expect(mocked.createQuestionVersion.mock.calls[0]![2].answer.value).toEqual(['B'])
  })

  it('填了不合法的 JSON：列出原因，不能保存', async () => {
    mocked.getQuestion.mockResolvedValue(
      detail({ answer_mode: 'fill', type: 'fill_blank', content: { stem: '填空 ____', options: [], blanks: [{ key: 'b1', label: null, unit_hint: null, placeholder: null }], subquestions: [], attachments: [], data_tables: [], safety: null, proof: null }, answer: { value: { b1: '5' }, equivalence_rules: {}, units: {} } }),
    )
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await flushPromises()

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
    await flushPromises()
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
    await flushPromises()
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
    await flushPromises()
    await wrapper.get('[data-testid="title"]').setValue('第一版内容')

    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="edit-retry"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="title"]').setValue('改了主意')
    await wrapper.get('[data-testid="edit-release"]').trigger('click')
    await flushPromises()
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
    await flushPromises()
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
    await flushPromises()
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

describe('编辑实验题', () => {
  async function openEditor(source = experimentDetail()) {
    mocked.getQuestion.mockResolvedValue(source)
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('编辑器里有安全提示、数据表、小问和自查要点；没有选项、空位，也没有评分细则的 JSON', async () => {
    const wrapper = await openEditor()

    for (const block of ['safety', 'data-tables', 'subquestions', 'points']) {
      expect(wrapper.find(`[data-testid="${block}"]`).exists(), block).toBe(true)
    }
    for (const block of ['options', 'blanks', 'rubric-json']) {
      expect(wrapper.find(`[data-testid="${block}"]`).exists(), block).toBe(false)
    }
    expect(wrapper.get('[data-testid="safety-level"]').element).toHaveProperty('value', 'low')
    expect(wrapper.get('[data-testid="safety"]').text()).toContain('不是操作指导')
    expect(wrapper.get('[data-testid="data-tables-json"]').element).toHaveProperty(
      'value',
      JSON.stringify(experimentDetail().content.data_tables, null, 2),
    )
  })

  it('其他题型的编辑器里没有安全提示和数据表', async () => {
    const wrapper = await openEditor(writtenDetail())

    expect(wrapper.find('[data-testid="safety"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="data-tables"]').exists()).toBe(false)
  })

  it('每条要点的"所属"下拉里有整份、每个小问和每张数据表', async () => {
    const wrapper = await openEditor()

    const options = wrapper.get('[data-testid="point-part-0"]').findAll('option')
    expect(options.map((option) => option.element.value)).toEqual(['', '1', 't1'])
    expect(options[2]!.text()).toContain('数据表 t1')
  })

  it('改一条安全提示再保存：请求里带着新的安全提示和原样的数据表', async () => {
    mocked.createQuestionVersion.mockResolvedValue(experimentDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="safety"] textarea').setValue('（改）本题只处理数据。')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const body = mocked.createQuestionVersion.mock.calls[0]![2]
    expect(body.content.safety!.notes[0]).toBe('（改）本题只处理数据。')
    expect(body.content.data_tables).toEqual(experimentDetail().content.data_tables)
    expect(body.answer.value).toEqual(experimentDetail().answer.value)
  })

  it('数据表的 JSON 写坏了：列出原因，不能保存', async () => {
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="data-tables-json"]').setValue('[{坏了')

    expect(wrapper.get('[data-testid="editor-errors"]').text()).toContain('数据表不是合法的 JSON')
    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeDefined()
  })
})

describe('编辑证明题', () => {
  async function openEditor(source = proofDetail()) {
    mocked.getQuestion.mockResolvedValue(source)
    const wrapper = await openPage()
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('编辑器里有已知与求证、参考证明和自查要点；没有选项、空位、小问、安全提示、数据表，也没有评分细则的 JSON', async () => {
    const wrapper = await openEditor()

    for (const block of ['proof-statement', 'proof-steps', 'points']) {
      expect(wrapper.find(`[data-testid="${block}"]`).exists(), block).toBe(true)
    }
    for (const block of ['options', 'blanks', 'subquestions', 'safety', 'data-tables', 'rubric-json']) {
      expect(wrapper.find(`[data-testid="${block}"]`).exists(), block).toBe(false)
    }
    expect(wrapper.get('[data-testid="claim"]').element).toHaveProperty('value', '$ac>bd$。')
    expect(wrapper.get('[data-testid="proof-statement"]').text()).toContain('只在学生提交之后给出')
    expect(wrapper.get('[data-testid="proof-steps"]').text()).toContain('最后一步必须是“结论”')
    expect(wrapper.get('[data-testid="points"]').text()).toContain('不是评分')
  })

  it('参考证明一行一步：阶段、文字、依据都在；阶段下拉里是前提、构造、推理、结论', async () => {
    const wrapper = await openEditor()

    expect(wrapper.get('[data-testid="step-stage-1"]').element).toHaveProperty('value', 'construction')
    expect(wrapper.get('[data-testid="step-text-3"]').element).toHaveProperty('value', '由 $ac>bc$ 和 $bc>bd$，得 $ac>bd$。')
    expect(wrapper.get('[data-testid="step-reason-3"]').element).toHaveProperty('value', '不等式的传递性')
    const options = wrapper.get('[data-testid="step-stage-0"]').findAll('option')
    expect(options.map((option) => option.element.value)).toEqual(['premise', 'construction', 'reasoning', 'conclusion'])
    expect(options.map((option) => option.text())).toEqual(['前提', '构造', '推理', '结论'])
  })

  it('每条要点的"所属"下拉里是四个证明阶段和"整份证明"', async () => {
    const wrapper = await openEditor()

    const options = wrapper.get('[data-testid="point-part-0"]').findAll('option')
    expect(options.map((option) => option.element.value)).toEqual(['', 'premise', 'construction', 'reasoning', 'conclusion'])
    expect(options[0]!.text()).toBe('整份证明')
    expect(wrapper.get('[data-testid="point-part-1"]').element).toHaveProperty('value', 'construction')
    expect(wrapper.get('[data-testid="point-part-4"]').element).toHaveProperty('value', '')
  })

  it('其他题型的编辑器里没有已知与求证和参考证明', async () => {
    for (const source of [writtenDetail(), experimentDetail(), detail()]) {
      const wrapper = await openEditor(source)
      expect(wrapper.find('[data-testid="proof-statement"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="proof-steps"]').exists()).toBe(false)
    }
  })

  it('没改动时不能保存', async () => {
    const wrapper = await openEditor()

    expect(wrapper.find('[data-testid="unchanged"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="save"]').attributes('disabled')).toBeDefined()
  })

  it('改一步的依据再保存：请求里带着新的参考证明，已知和求证原样', async () => {
    mocked.createQuestionVersion.mockResolvedValue(proofDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="step-reason-2"]').setValue('（改）依据')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const body = mocked.createQuestionVersion.mock.calls[0]![2]
    const steps = (body.answer.value as { steps: { reason: string }[] }).steps
    expect(steps[2]!.reason).toBe('（改）依据')
    expect(steps).toHaveLength(4)
    expect(body.content.proof).toEqual(proofDetail().content.proof)
  })

  it('改求证、加一条已知再保存', async () => {
    mocked.createQuestionVersion.mockResolvedValue(proofDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="claim"]').setValue('（改）$ac>bd$')
    const given = wrapper.get('[data-testid="proof-statement"]')
    await given.findAll('button').find((button) => button.text() === '添加一条')!.trigger('click')
    await given.findAll('textarea').at(-2)!.setValue('$a,b,c,d$ 都是实数')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const body = mocked.createQuestionVersion.mock.calls[0]![2]
    expect(body.content.proof!.claim).toBe('（改）$ac>bd$')
    expect(body.content.proof!.givens).toEqual(['$a>b>0$', '$c>d>0$', '$a,b,c,d$ 都是实数'])
  })

  it('添加一步、上移、下移、删除：参考证明跟着变', async () => {
    mocked.createQuestionVersion.mockResolvedValue(proofDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()
    const original = (proofDetail().answer.value as { steps: { text: string }[] }).steps.map((step) => step.text)

    await wrapper.get('[data-testid="add-step"]').trigger('click')
    await wrapper.get('[data-testid="step-text-4"]').setValue('补充的一步')
    await wrapper.get('[data-testid="step-reason-4"]').setValue('补充的依据')
    await wrapper.get('[data-testid="step-up-4"]').trigger('click') // 补充的一步 ↔ 原来的第 4 步
    await wrapper.get('[data-testid="step-down-0"]').trigger('click') // 原来的第 1、2 步对调
    await wrapper.get('[data-testid="step-delete-0"]').trigger('click') // 删掉现在的第一步（原来的第 2 步）
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const steps = (mocked.createQuestionVersion.mock.calls[0]![2].answer.value as { steps: { text: string }[] }).steps
    expect(steps.map((step) => step.text)).toEqual([original[0], original[2], '补充的一步', original[3]])
  })

  it('第一步不能上移，最后一步不能下移', async () => {
    const wrapper = await openEditor()

    expect(wrapper.get('[data-testid="step-up-0"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="step-down-3"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid="step-up-1"]').attributes('disabled')).toBeUndefined()
  })

  it('把一条要点改成针对另一个阶段', async () => {
    mocked.createQuestionVersion.mockResolvedValue(proofDetail({ version: 2, created_by: ME }))
    const wrapper = await openEditor()

    await wrapper.get('[data-testid="point-part-0"]').setValue('conclusion')
    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const points = (mocked.createQuestionVersion.mock.calls[0]![2].rubric as unknown as { points: { part: string | null }[] }).points
    expect(points.map((point) => point.part)).toEqual(['conclusion', 'construction', 'reasoning', 'conclusion', null])
  })
})



