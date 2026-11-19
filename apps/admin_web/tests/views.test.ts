import {installBrowserStorage,flushRecovery as flushPromises} from './support/browser-storage'
import { mount,enableAutoUnmount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../src/api/admin'
import { ApiError } from '../src/api/client'
import { clearSession, setSession } from '../src/session'
import LoginView from '../src/views/LoginView.vue'
import QueueView from '../src/views/QueueView.vue'
import QuestionView from '../src/views/QuestionView.vue'
import {
  AUTHOR,
  detail,
  experimentDetail,
  proofDetail,
  FAST,
  ME,
  page,
  QUESTION_ID,
  solution,
  summary,
  writtenDetail,
} from './fixtures'

enableAutoUnmount(afterEach)

vi.mock('../src/api/admin', () => ({
  getHealth: vi.fn(),
  createLocalIdentity: vi.fn(),
  listQuestions: vi.fn(),
  getQuestion: vi.fn(),
  reviewQuestion: vi.fn(),
}))

const mocked = vi.mocked(api)

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      { path: '/', name: 'queue', component: QueueView },
      { path: '/import', name: 'import', component: { template: '<div />' } },
      { path: '/questions/:id', name: 'question', component: QuestionView },
      { path: '/questions/:id/compare', name: 'compare', component: { template: '<div />' } },
    ],
  })
}

async function mountAt(path: string) {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  installBrowserStorage()
  vi.resetAllMocks()
  clearSession()
  setSession({ token: 'tok', userId: ME, role: 'reviewer' })
})

// ---------------------------------------------------------------- 登录

describe('登录页', () => {
  it('后端开着本地身份 Mock：点按钮拿到审核员身份并进入队列', async () => {
    mocked.getHealth.mockResolvedValue({ local_identity_mock: true } as never)
    mocked.createLocalIdentity.mockResolvedValue({
      user_id: ME,
      role: 'reviewer',
      access_token: 'x'.repeat(40),
      token_type: 'Bearer',
    })
    mocked.listQuestions.mockResolvedValue(page([]))
    clearSession()

    const { wrapper, router } = await mountAt('/login')
    await wrapper.get('[data-testid="sign-in-reviewer"]').trigger('click')
    await flushPromises()

    expect(mocked.createLocalIdentity).toHaveBeenCalledWith('reviewer')
    expect(router.currentRoute.value.name).toBe('queue')
  })

  it('没开本地身份 Mock：不给登录按钮，说明原因', async () => {
    mocked.getHealth.mockResolvedValue({ local_identity_mock: false } as never)
    clearSession()

    const { wrapper } = await mountAt('/login')

    expect(wrapper.find('[data-testid="sign-in-reviewer"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Q-03')
  })

  it('服务端拒绝时显示原因，不进入后台', async () => {
    mocked.getHealth.mockResolvedValue({ local_identity_mock: true } as never)
    mocked.createLocalIdentity.mockRejectedValue(new ApiError(404, 'not_found', '资源不存在'))
    clearSession()

    const { wrapper, router } = await mountAt('/login')
    await wrapper.get('[data-testid="sign-in-admin"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="login-error"]').text()).toContain('本地身份 Mock')
    expect(router.currentRoute.value.name).toBe('login')
  })
})

// ---------------------------------------------------------------- 队列

describe('审核队列', () => {
  it('默认看待审的题，页签上有每种状态的数量', async () => {
    mocked.listQuestions.mockResolvedValue(page([summary(), summary({ id: 'b', title: '识别电解质' })]))

    const { wrapper } = await mountAt('/')

    expect(mocked.listQuestions).toHaveBeenCalledWith('tok', {
      status: 'draft',
      subject: undefined,
      cursor: undefined,
      limit: 20,
    })
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0]!.text()).toContain('绝对值函数的单调递减区间')
    expect(rows[0]!.text()).toContain('自编工程样题 · 未经学科审校')
    expect(wrapper.get('[data-testid="tab-draft"]').text()).toContain('2')
    expect(wrapper.get('[data-testid="tab-published"]').text()).toContain('17')
    expect(wrapper.get('[data-testid="tab-all"]').text()).toContain('20')
  })

  it('切页签和学科会带着筛选重新请求', async () => {
    mocked.listQuestions.mockResolvedValue(page([summary()]))
    const { wrapper } = await mountAt('/')

    await wrapper.get('[data-testid="tab-reviewed"]').trigger('click')
    await flushPromises()
    expect(mocked.listQuestions).toHaveBeenLastCalledWith('tok', expect.objectContaining({ status: 'reviewed' }))

    await wrapper.get('[data-testid="subject"]').setValue('physics')
    await flushPromises()
    expect(mocked.listQuestions).toHaveBeenLastCalledWith(
      'tok',
      expect.objectContaining({ status: 'reviewed', subject: 'physics' }),
    )

    await wrapper.get('[data-testid="tab-all"]').trigger('click')
    await flushPromises()
    expect(mocked.listQuestions).toHaveBeenLastCalledWith('tok', expect.objectContaining({ status: undefined }))
  })

  it('还有下一页就显示"加载更多"，点了带上游标并接在后面', async () => {
    mocked.listQuestions
      .mockResolvedValueOnce(page([summary()], { next_cursor: 'cursor-2' }))
      .mockResolvedValueOnce(page([summary({ id: 'second', title: '第二页的题' })]))
    const { wrapper } = await mountAt('/')

    await wrapper.get('[data-testid="more"]').trigger('click')
    await flushPromises()

    expect(mocked.listQuestions).toHaveBeenLastCalledWith('tok', expect.objectContaining({ cursor: 'cursor-2' }))
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.find('[data-testid="more"]').exists()).toBe(false)
  })

  it('没有题时说明情况；加载失败时显示原因', async () => {
    mocked.listQuestions.mockResolvedValueOnce(page([]))
    const { wrapper } = await mountAt('/')
    expect(wrapper.get('[data-testid="empty"]').text()).toContain('没有待审的题')

    mocked.listQuestions.mockRejectedValueOnce(new ApiError(0, 'network_error', '连不上服务器，请确认后端已经启动'))
    await wrapper.get('[data-testid="tab-published"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('连不上服务器')
  })

  it('登录失效（401）：清掉会话回到登录页', async () => {
    mocked.listQuestions.mockRejectedValue(new ApiError(401, 'unauthenticated', '未认证'))
    const router = makeRouter()
    const { setUnauthorizedHandler } = await import('../src/api/guard')
    setUnauthorizedHandler(() => void router.replace({ name: 'login' }))
    await router.push('/')
    await router.isReady()
    mount({ template: '<RouterView />' }, { global: { plugins: [router] } })
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('login')
    const { useSession } = await import('../src/session')
    expect(useSession().session).toBeNull()
  })

  it('点一行进入这道题的审核页', async () => {
    mocked.listQuestions.mockResolvedValue(page([summary()]))
    mocked.getQuestion.mockResolvedValue(detail())
    const { wrapper, router } = await mountAt('/')

    await wrapper.get('tbody tr').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe(`/questions/${QUESTION_ID}`)
  })
})

// ---------------------------------------------------------------- 题目与决策

describe('题目审核页', () => {
  it('展示审核需要的全部内容：题面、答案、解法、提示、校验、历史', async () => {
    mocked.getQuestion.mockResolvedValue(
      detail({
        solutions: [solution(), FAST],
        history: [
          {
            id: 'h1',
            action: 'reject',
            actor_id: AUTHOR,
            from_status: 'reviewed',
            to_status: 'draft',
            version: 1,
            comment: '第二步缺少前提',
            changes: null,
            created_at: '2026-11-11T09:00:00Z',
          },
        ],
      }),
    )

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(mocked.getQuestion).toHaveBeenCalledWith('tok', QUESTION_ID)
    expect(wrapper.text()).toContain('绝对值函数的单调递减区间')
    expect(wrapper.get('[data-testid="source"]').text()).toContain('未经学科审校')
    expect(wrapper.find('.stem .katex').exists()).toBe(true)
    expect(wrapper.text()).toContain('正确选项')
    expect(wrapper.get('[data-testid="solution-standard"]').text()).toContain('未审核')
    expect(wrapper.get('[data-testid="solution-fast"]').text()).toContain('适用条件')
    expect(wrapper.get('[data-testid="solution-fast"]').text()).toContain('粗糙斜面不能用')
    expect(wrapper.get('[data-testid="checks"]').text()).toContain('通过')
    expect(wrapper.get('[data-testid="history"]').text()).toContain('第二步缺少前提')
    expect(wrapper.text()).toContain('分层提示')
  })

  it('解答题：题面里有小问，参考答案按小问列出，自查要点按小问分组、不带分值', async () => {
    mocked.getQuestion.mockResolvedValue(writtenDetail())

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.text()).toContain('解答题')
    const parts = wrapper.get('[data-testid="subquestions-view"]')
    expect(parts.findAll('li')).toHaveLength(2)
    expect(parts.text()).toContain('（1）')
    expect(parts.text()).toContain('（2）')
    expect(wrapper.find('[data-testid="subquestions-view"] .katex').exists()).toBe(true)
    const answers = wrapper.get('dl.kv')
    expect(answers.text()).toContain('第 1 问')
    expect(answers.text()).toContain('第 2 问')
    expect(answers.text()).not.toContain('空 1')
    const points = wrapper.get('[data-testid="rubric-points"]')
    expect(points.findAll('li')).toHaveLength(4)
    expect(points.text()).toContain('第 1 问')
    expect(points.text()).toContain('整份解答')
    expect(points.text()).toContain('提交后给学生对照自查')
    expect(points.text()).toContain('不是评分')
  })

  it('实验题：安全提示、数据表（留空的格子标出"学生填写"和参考值）、自查要点按小问和数据表分组', async () => {
    mocked.getQuestion.mockResolvedValue(experimentDetail())

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.text()).toContain('实验题')
    const safety = wrapper.get('[data-testid="safety-view"]')
    expect(safety.text()).toContain('风险等级 low')
    expect(safety.text()).toContain('不是操作指导')
    const table = wrapper.get('[data-testid="table-t1"]')
    expect(table.text()).toContain('表 1  相邻计数点间的距离与平均速度')
    expect(table.findAll('thead th').map((th) => th.text())).toEqual(['计数点间', '距离 x（cm）', '平均速度（m/s）'])
    expect(table.findAll('tbody tr')).toHaveLength(2)
    expect(table.text()).toContain('4.00')
    const blank = wrapper.get('[data-testid="blank-t1-r1-v"]')
    expect(blank.text()).toContain('学生填写')
    expect(blank.text()).toContain('0.400')
    const answers = wrapper.get('dl.kv')
    expect(answers.text()).toContain('第 1 问')
    expect(answers.text()).toContain('格子 t1.r1.v')
    const points = wrapper.get('[data-testid="rubric-points"]')
    expect(points.text()).toContain('数据表 t1')
    expect(points.text()).toContain('第 1 问')
    expect(points.text()).toContain('整份解答')
    expect(points.text()).toContain('实验题不自动评分')
  })

  it('实验题没有安全提示：审核页上没有那一块，程序校验的问题照样列出', async () => {
    const source = experimentDetail()
    mocked.getQuestion.mockResolvedValue(
      experimentDetail({
        content: { ...source.content, safety: null },
        check_problems: ['phys-tape: content.safety 必须有 level 和 notes'],
      }),
    )

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.find('[data-testid="safety-view"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="checks"]').text()).toContain('content.safety')
  })

  it('证明题：已知（编号）、求证、参考证明（阶段、文字、依据）、自查要点按证明阶段分组', async () => {
    mocked.getQuestion.mockResolvedValue(proofDetail())

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.text()).toContain('证明题')
    const statement = wrapper.get('[data-testid="proof-view"]')
    expect(statement.findAll('li')).toHaveLength(2)
    expect(wrapper.get('[data-testid="given-0"]').text()).toContain('①')
    expect(wrapper.get('[data-testid="given-1"]').text()).toContain('②')
    expect(wrapper.find('[data-testid="claim-view"]').exists()).toBe(true)
    // 参考证明：一步一行，阶段用中文
    const steps = wrapper.get('[data-testid="reference-steps"]')
    expect(steps.findAll('tbody tr')).toHaveLength(4)
    expect(steps.findAll('thead th').map((th) => th.text())).toEqual(['步', '阶段', '这一步', '依据'])
    expect(wrapper.get('[data-testid="ref-step-0"]').text()).toContain('前提')
    expect(wrapper.get('[data-testid="ref-step-1"]').text()).toContain('构造')
    expect(wrapper.get('[data-testid="ref-step-3"]').text()).toContain('结论')
    expect(wrapper.get('[data-testid="ref-step-3"]').text()).toContain('不等式的传递性')
    // 答案那一块里不会出现"[object Object]"
    expect(wrapper.text()).not.toContain('[object Object]')
    // 自查要点：按阶段分组，整份证明的放在最后
    const points = wrapper.get('[data-testid="rubric-points"]')
    const headings = points.findAll('h3').map((h) => h.text())
    expect(headings).toEqual(['前提', '构造', '推理', '结论', '整份证明'])
    expect(points.text()).toContain('证明题不自动评分')
    expect(points.text()).toContain('不是评分')
    // 没有小问、没有安全提示和数据表
    expect(wrapper.find('[data-testid="subquestions-view"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="safety-view"]').exists()).toBe(false)
    expect(wrapper.find('.table-block').exists()).toBe(false)
  })

  it('证明题的已知可以是空的：只有求证', async () => {
    const source = proofDetail()
    mocked.getQuestion.mockResolvedValue(
      proofDetail({ content: { ...source.content, proof: { givens: [], claim: '$x>0$' } } }),
    )

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    const statement = wrapper.get('[data-testid="proof-view"]')
    expect(statement.text()).not.toContain('已知')
    expect(statement.text()).toContain('求证')
  })

  it('证明题的要点按证明的先后排，哪怕库里是乱序存的', async () => {
    const source = proofDetail()
    const points = (source.rubric as unknown as { points: unknown[] }).points
    mocked.getQuestion.mockResolvedValue(proofDetail({ rubric: { points: [...points].reverse() } as never }))

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    const headings = wrapper.get('[data-testid="rubric-points"]').findAll('h3').map((h) => h.text())
    expect(headings).toEqual(['前提', '构造', '推理', '结论', '整份证明'])
  })

  it('证明题没有参考证明：审核页明说，程序校验的问题照样列出', async () => {
    const source = proofDetail()
    mocked.getQuestion.mockResolvedValue(
      proofDetail({
        answer: { ...source.answer, value: {} },
        check_problems: ['math-ineq-mul-proof: answer.value 必须是 {steps: [...]}'],
      }),
    )

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.get('[data-testid="reference-steps"]').text()).toContain('还没有参考证明')
    expect(wrapper.get('[data-testid="checks"]').text()).toContain('answer.value')
  })

  it('其他题型的审核页里没有已知与求证和参考证明', async () => {
    for (const source of [detail(), writtenDetail(), experimentDetail()]) {
      mocked.getQuestion.mockResolvedValue(source)

      const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

      expect(wrapper.find('[data-testid="proof-view"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="reference-steps"]').exists()).toBe(false)
    }
  })

  it('选择题的审核页里没有数据表和安全提示', async () => {
    mocked.getQuestion.mockResolvedValue(detail())

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.find('[data-testid="safety-view"]').exists()).toBe(false)
    expect(wrapper.find('.data-table').exists()).toBe(false)
  })

  it('选择题的审核页里没有小问和自查要点这两块', async () => {
    mocked.getQuestion.mockResolvedValue(detail())

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.find('[data-testid="subquestions-view"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="rubric-points"]').exists()).toBe(false)
  })

  it('程序校验有问题时逐条列出，并且二审按钮不可用', async () => {
    mocked.getQuestion.mockResolvedValue(detail({ check_problems: ['answer.value 含有不存在的选项'] }))

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.get('[data-testid="checks"]').text()).toContain('answer.value 含有不存在的选项')
    expect(wrapper.get('[data-testid="blocked"]').text()).toContain('1 个问题')
    expect(wrapper.get('[data-testid="submit-decision"]').attributes('disabled')).toBeDefined()
  })

  it('题不存在：说明，没有决策面板', async () => {
    mocked.getQuestion.mockRejectedValue(new ApiError(404, 'not_found', '资源不存在'))

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.get('[data-testid="load-error"]').text()).toContain('没有这道题')
    expect(wrapper.find('[data-testid="decision-panel"]').exists()).toBe(false)
  })

  it('二审通过：只带上确认过的解法和当前版本，成功后刷新并提示', async () => {
    mocked.getQuestion
      .mockResolvedValueOnce(detail({ solutions: [solution(), FAST] }))
      .mockResolvedValueOnce(detail({ status: 'reviewed', reviewed_by: ME, solutions: [solution({ reviewed: true, reviewed_by: ME }), FAST] }))
    mocked.reviewQuestion.mockResolvedValue({
      question_id: QUESTION_ID,
      status: 'reviewed',
      version: 1,
      reviewed_by: ME,
      updated_at: '2026-11-11T09:00:00Z',
    })
    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    await wrapper.get('[data-testid="confirm-fast"]').setValue(true)
    await wrapper.get('[data-testid="comment"]').setValue('  解法没问题  ')
    await wrapper.get('[data-testid="submit-decision"]').trigger('click')
    await flushPromises()

    expect(mocked.reviewQuestion).toHaveBeenCalledTimes(1)
    const [token, id, body, key] = mocked.reviewQuestion.mock.calls[0]!
    expect([token, id]).toEqual(['tok', QUESTION_ID])
    expect(body).toEqual({
      decision: 'approve',
      expected_version: 1,
      expected_review_revision: 1,
      comment: '解法没问题',
      solution_kinds: ['standard', 'fast'],
    })
    expect(key.length).toBeGreaterThanOrEqual(8)
    expect(wrapper.get('[data-testid="done"]').text()).toContain('二审通过')
    expect(mocked.getQuestion).toHaveBeenCalledTimes(2)
    // 刷新之后进入 reviewed：可以上线
    expect(wrapper.get('[data-testid="submit-decision"]').text()).toBe('上线')
  })

  it('不勾选快速解法时只确认标准解法', async () => {
    mocked.getQuestion.mockResolvedValue(detail({ solutions: [solution(), FAST] }))
    mocked.reviewQuestion.mockResolvedValue({
      question_id: QUESTION_ID,
      status: 'reviewed',
      version: 1,
      reviewed_by: ME,
      updated_at: '2026-11-11T09:00:00Z',
    })
    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    await wrapper.get('[data-testid="submit-decision"]').trigger('click')
    await flushPromises()

    expect(mocked.reviewQuestion.mock.calls[0]![2]).toEqual({
      decision: 'approve',
      expected_version: 1,
      expected_review_revision: 1,
      solution_kinds: ['standard'],
    })
  })

  it('自己提交的题：二审按钮不可用并说明原因', async () => {
    mocked.getQuestion.mockResolvedValue(detail({ created_by: ME }))

    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    expect(wrapper.get('[data-testid="blocked"]').text()).toContain('提交者')
    expect(wrapper.get('[data-testid="submit-decision"]').attributes('disabled')).toBeDefined()
    expect(mocked.reviewQuestion).not.toHaveBeenCalled()
  })

  it('退回修改必须写原因：没写按钮不可用，写了之后带上原因', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.reviewQuestion.mockResolvedValue({
      question_id: QUESTION_ID,
      status: 'draft',
      version: 1,
      reviewed_by: null,
      updated_at: '2026-11-11T09:00:00Z',
    })
    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    await wrapper.findAll('input[name="decision"]')[1]!.setValue(true) // 退回修改
    expect(wrapper.get('[data-testid="submit-decision"]').attributes('disabled')).toBeDefined()

    await wrapper.get('[data-testid="comment"]').setValue('第二步缺少前提')
    await wrapper.get('[data-testid="submit-decision"]').trigger('click')
    await flushPromises()

    expect(mocked.reviewQuestion.mock.calls[0]![2]).toEqual({
      decision: 'reject',
      expected_version: 1,
      expected_review_revision: 1,
      comment: '第二步缺少前提',
    })
  })

  it('已上线的题只能下线；下线后是终态，没有任何决策可选', async () => {
    mocked.getQuestion.mockResolvedValueOnce(detail({ status: 'published' }))
    const first = await mountAt(`/questions/${QUESTION_ID}`)
    expect(first.wrapper.findAll('input[name="decision"]')).toHaveLength(1)
    expect(first.wrapper.get('[data-testid="submit-decision"]').text()).toBe('下线（撤回）')

    mocked.getQuestion.mockResolvedValueOnce(detail({ status: 'withdrawn' }))
    const second = await mountAt(`/questions/${QUESTION_ID}`)
    expect(second.wrapper.findAll('input[name="decision"]')).toHaveLength(0)
    expect(second.wrapper.get('[data-testid="decision-panel"]').text()).toContain('终态')
  })

  it('服务端拒绝时显示翻译后的原因；程序校验的问题逐条列出', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.reviewQuestion.mockRejectedValue(
      new ApiError(422, 'content_checks_failed', '程序校验发现 1 个问题', { problems: ['teaching.hints[0] 可能泄题'] }),
    )
    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    await wrapper.get('[data-testid="submit-decision"]').trigger('click')
    await flushPromises()

    const shown = wrapper.get('[data-testid="decision-error"]')
    expect(shown.text()).toContain('程序校验没有通过')
    expect(shown.text()).toContain('teaching.hints[0] 可能泄题')
  })

  it('版本已经变了（409）：提示刷新，点了就重新加载', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.reviewQuestion.mockRejectedValue(
      new ApiError(409, 'version_conflict', '题目已经是第 2 版', { current_version: 2 }),
    )
    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)

    await wrapper.get('[data-testid="submit-decision"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-testid="decision-error"]').text()).toContain('版本已经变了')

    await wrapper.get('[data-testid="decision-error"] button.link').trigger('click')
    await flushPromises()
    expect(mocked.getQuestion).toHaveBeenCalledTimes(2)
  })

  it('网络失败后重试同一个动作：复用同一个幂等键；内容变了就换一个', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.reviewQuestion
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '连不上服务器'))
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '连不上服务器'))
      .mockRejectedValueOnce(new ApiError(0, 'network_error', '连不上服务器'))
    const { wrapper } = await mountAt(`/questions/${QUESTION_ID}`)
    const submit = wrapper.get('[data-testid="submit-decision"]')

    await submit.trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="review-retry"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="comment"]').setValue('补充一句备注')
    await wrapper.get('[data-testid="review-release"]').trigger('click')
    await flushPromises()
    await submit.trigger('click')
    await flushPromises()

    const keys = mocked.reviewQuestion.mock.calls.map((call) => call[3])
    expect(keys[0]).toBe(keys[1])
    expect(keys[2]).not.toBe(keys[0])
  })
})


