import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../src/api/admin'
import { ApiError } from '../src/api/client'
import { clearSession, setSession } from '../src/session'
import QuestionCompareView from '../src/views/QuestionCompareView.vue'
import QuestionView from '../src/views/QuestionView.vue'
import { AUTHOR, detail, ME, QUESTION_ID, snapshot } from './fixtures'

vi.mock('../src/api/admin', () => ({
  getHealth: vi.fn(),
  createLocalIdentity: vi.fn(),
  listQuestions: vi.fn(),
  getQuestion: vi.fn(),
  getQuestionVersion: vi.fn(),
  reviewQuestion: vi.fn(),
  createQuestionVersion: vi.fn(),
}))

const mocked = vi.mocked(api)

const TWO_VERSIONS = detail({
  version: 2,
  versions: [
    { version: 1, created_by: AUTHOR, created_at: '2026-11-11T08:00:00Z' },
    { version: 2, created_by: ME, created_at: '2026-11-11T09:00:00Z' },
  ],
})

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'queue', component: { template: '<div />' } },
      { path: '/questions/:id', name: 'question', component: QuestionView },
      { path: '/questions/:id/compare', name: 'compare', component: QuestionCompareView },
    ],
  })
}

async function open(path: string) {
  const router = makeRouter()
  await router.push(path)
  await router.isReady()
  const wrapper = mount({ template: '<RouterView />' }, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}

/** 第 1 版和第 2 版：标题、题干、难度不同，其余一样。 */
function twoSnapshots() {
  const first = snapshot({ version: 1, is_current: false })
  const second = snapshot({
    version: 2,
    is_current: true,
    created_by: ME,
    created_at: '2026-11-11T09:00:00Z',
    title: '改过的标题',
    difficulty: 4,
    content: { ...first.content, stem: '函数 $f(x)=|x+1|$ 的单调递减区间是（　）' },
  })
  mocked.getQuestionVersion.mockImplementation(async (_token, _id, version) => (version === 1 ? first : second))
  return { first, second }
}

beforeEach(() => {
  vi.resetAllMocks()
  clearSession()
  setSession({ token: 'tok', userId: ME, role: 'reviewer' })
})

describe('版本对比页', () => {
  it('没带参数：默认对比"上一版"和"当前版本"，只显示有改动的部分', async () => {
    mocked.getQuestion.mockResolvedValue(TWO_VERSIONS)
    twoSnapshots()

    const { wrapper } = await open(`/questions/${QUESTION_ID}/compare`)

    expect(mocked.getQuestionVersion).toHaveBeenCalledWith('tok', QUESTION_ID, 1)
    expect(mocked.getQuestionVersion).toHaveBeenCalledWith('tok', QUESTION_ID, 2)
    expect(wrapper.get('[data-testid="summary"]').text()).toBe('改动了：基本信息、题面')
    expect(wrapper.find('[data-testid="section-basic"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="section-content"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="section-answer"]').exists()).toBe(false) // 没改的部分不显示
    expect(wrapper.find('[data-testid="field-grade"]').exists()).toBe(false) // 同一部分里没改的字段也不显示
    expect(wrapper.find('[data-testid="field-title"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="from"]').element).toHaveProperty('value', '1')
    expect(wrapper.get('[data-testid="to"]').element).toHaveProperty('value', '2')
  })

  it('字段里：左边标出删掉的、右边标出新加的，题干里的公式另外渲染出来', async () => {
    mocked.getQuestion.mockResolvedValue(TWO_VERSIONS)
    twoSnapshots()

    const { wrapper } = await open(`/questions/${QUESTION_ID}/compare`)

    const stem = wrapper.get('[data-testid="field-stem"]')
    expect(stem.findAll('.seg-del').map((node) => node.text())).toContain('-')
    expect(stem.findAll('.seg-add').map((node) => node.text())).toContain('+')
    expect(stem.find('.rendered .katex').exists()).toBe(true)
    expect(wrapper.get('[data-testid="field-title"]').text()).toContain('改过的标题')
  })

  it('打开"显示没有改动的部分"：所有部分和字段都出来，改动的仍然标着"有改动"', async () => {
    mocked.getQuestion.mockResolvedValue(TWO_VERSIONS)
    twoSnapshots()
    const { wrapper, router } = await open(`/questions/${QUESTION_ID}/compare`)

    await wrapper.get('[data-testid="show-all"]').setValue(true)
    await flushPromises()

    expect(router.currentRoute.value.query.all).toBe('1')
    expect(wrapper.find('[data-testid="section-answer"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="field-grade"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="field-title"]').text()).toContain('有改动')
    expect(wrapper.get('[data-testid="field-grade"]').text()).not.toContain('有改动')
  })

  it('换要对比的版本：地址里的参数变了，重新取两个版本', async () => {
    mocked.getQuestion.mockResolvedValue(
      detail({
        version: 3,
        versions: [
          { version: 1, created_by: AUTHOR, created_at: '2026-11-11T08:00:00Z' },
          { version: 2, created_by: ME, created_at: '2026-11-11T09:00:00Z' },
          { version: 3, created_by: ME, created_at: '2026-11-11T10:00:00Z' },
        ],
      }),
    )
    mocked.getQuestionVersion.mockImplementation(async (_t, _id, version) => snapshot({ version, title: `第 ${version} 版` }))
    const { wrapper, router } = await open(`/questions/${QUESTION_ID}/compare?from=2&to=3`)
    expect(wrapper.get('[data-testid="from"]').element).toHaveProperty('value', '2')

    await wrapper.get('[data-testid="from"]').setValue('1')
    await flushPromises()

    expect(router.currentRoute.value.query).toMatchObject({ from: '1', to: '3' })
    expect(mocked.getQuestionVersion).toHaveBeenLastCalledWith('tok', QUESTION_ID, 3)
    expect(mocked.getQuestionVersion.mock.calls.some((call) => call[2] === 1)).toBe(true)
    expect(mocked.getQuestion).toHaveBeenCalledTimes(1) // 题目详情只取一次
  })

  it('两个版本没有区别：直接说明', async () => {
    mocked.getQuestion.mockResolvedValue(TWO_VERSIONS)
    mocked.getQuestionVersion.mockImplementation(async (_t, _id, version) => snapshot({ version }))

    const { wrapper } = await open(`/questions/${QUESTION_ID}/compare?from=1&to=2`)

    expect(wrapper.get('[data-testid="summary"]').text()).toBe('这两个版本没有任何区别。')
    expect(wrapper.findAll('section.card')).toHaveLength(0)
  })

  it('选同一个版本（回看某一版的完整内容）：说明这一点，并且显示全部内容', async () => {
    mocked.getQuestion.mockResolvedValue(TWO_VERSIONS)
    twoSnapshots()

    const { wrapper } = await open(`/questions/${QUESTION_ID}/compare?from=1&to=1&all=1`)

    expect(wrapper.get('[data-testid="summary"]').text()).toContain('同一个版本')
    expect(wrapper.find('[data-testid="section-answer"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="show-all"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('绝对值函数的单调递减区间')
  })

  it('版本不存在（404）：说明，不报错崩溃', async () => {
    mocked.getQuestion.mockResolvedValue(TWO_VERSIONS)
    mocked.getQuestionVersion.mockRejectedValue(new ApiError(404, 'not_found', '资源不存在'))

    const { wrapper } = await open(`/questions/${QUESTION_ID}/compare?from=1&to=9`)

    expect(wrapper.get('[data-testid="compare-error"]').text()).toContain('没有这个版本')
  })

  it('网址里的版本号乱写：回退到默认的两个版本', async () => {
    mocked.getQuestion.mockResolvedValue(TWO_VERSIONS)
    twoSnapshots()

    const { wrapper } = await open(`/questions/${QUESTION_ID}/compare?from=abc&to=-3`)

    expect(wrapper.get('[data-testid="from"]').element).toHaveProperty('value', '1')
    expect(wrapper.get('[data-testid="to"]').element).toHaveProperty('value', '2')
  })
})

describe('进入对比的入口（题目页）', () => {
  it('只有一个版本：版本是链接，可以看完整内容；没有"对比最近两个版本"', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    const { wrapper, router } = await open(`/questions/${QUESTION_ID}`)

    expect(wrapper.find('[data-testid="compare-latest"]').exists()).toBe(false)
    await wrapper.get('[data-testid="version-1"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('compare')
    expect(router.currentRoute.value.query).toMatchObject({ from: '1', to: '1', all: '1' })
  })

  it('有多个版本：可以直接对比最近两个，"修改"的历史条目里有"与上一版对比"', async () => {
    mocked.getQuestion.mockResolvedValue({
      ...TWO_VERSIONS,
      history: [
        {
          id: 'e1',
          action: 'edit',
          actor_id: ME,
          from_status: 'draft',
          to_status: 'draft',
          version: 2,
          comment: null,
          changes: ['title'],
          created_at: '2026-11-11T09:00:00Z',
        },
      ],
    })
    const { wrapper, router } = await open(`/questions/${QUESTION_ID}`)

    await wrapper.get('[data-testid="compare-entry-2"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('compare')
    expect(router.currentRoute.value.query).toMatchObject({ from: '1', to: '2' })
    expect(mocked.getQuestion).toHaveBeenCalled()
  })

  it('保存新版本之后，提示条里有"查看这次改了什么"', async () => {
    mocked.getQuestion.mockResolvedValue(detail())
    mocked.createQuestionVersion.mockResolvedValue(TWO_VERSIONS)
    const { wrapper } = await open(`/questions/${QUESTION_ID}`)
    await wrapper.get('[data-testid="edit"]').trigger('click')
    await wrapper.get('[data-testid="title"]').setValue('新标题')

    await wrapper.get('[data-testid="save"]').trigger('click')
    await flushPromises()

    const link = wrapper.get('[data-testid="saved-compare"]')
    expect(link.text()).toBe('查看这次改了什么')
    expect(link.attributes('href')).toContain('from=1')
    expect(link.attributes('href')).toContain('to=2')
  })
})
