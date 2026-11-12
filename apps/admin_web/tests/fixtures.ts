// 测试数据按契约里的类型来写：契约改了（字段增减、改名），这里编译不过，测试也就先红了。
import type {
  AdminQuestionDetail,
  AdminQuestionPage,
  AdminQuestionSummary,
  AdminSolution,
  AdminVersionSnapshot,
} from '../src/api/types'

export const ME = '11111111-1111-4111-8111-111111111111'
export const AUTHOR = '22222222-2222-4222-8222-222222222222'
export const QUESTION_ID = '33333333-3333-4333-8333-333333333333'

const source = {
  source_type: 'self_authored',
  source_category: 'foundation',
  source_name: '自编工程样题',
  source_year: null,
  source_license: 'internal-engineering-sample',
  source_url: null,
  is_engineering_sample: true,
  label: '自编工程样题 · 未经学科审校',
} as const

export function summary(overrides: Partial<AdminQuestionSummary> = {}): AdminQuestionSummary {
  return {
    id: QUESTION_ID,
    subject: 'math',
    type: 'single_choice',
    answer_mode: 'single_choice',
    difficulty: 2,
    title: '绝对值函数的单调递减区间',
    status: 'draft',
    version: 1,
    source,
    created_by: AUTHOR,
    reviewed_by: null,
    published_at: null,
    updated_at: '2026-11-11T08:00:00Z',
    ...overrides,
  }
}

export function page(
  items: AdminQuestionSummary[],
  overrides: Partial<AdminQuestionPage> = {},
): AdminQuestionPage {
  return {
    items,
    next_cursor: null,
    status_counts: { draft: items.length, reviewed: 1, published: 17, withdrawn: 0 },
    ...overrides,
  }
}

export function solution(overrides: Partial<AdminSolution> = {}): AdminSolution {
  return {
    kind: 'standard',
    steps: ['去绝对值：$x\\ge 1$ 时 $f(x)=x-1$。', '所以递减区间是 $(-\\infty,\\,1]$。'],
    final_answer: 'A',
    key_points: ['分段函数要分段判断'],
    conditions: null,
    boundary: null,
    reviewed: false,
    reviewed_by: null,
    ...overrides,
  }
}

export const FAST: AdminSolution = solution({
  kind: 'fast',
  steps: ['直接套公式。'],
  conditions: ['斜面光滑'],
  boundary: '粗糙斜面不能用',
})

export function detail(overrides: Partial<AdminQuestionDetail> = {}): AdminQuestionDetail {
  return {
    id: QUESTION_ID,
    subject: 'math',
    type: 'single_choice',
    answer_mode: 'single_choice',
    difficulty: 2,
    grade: 'G10',
    title: '绝对值函数的单调递减区间',
    status: 'draft',
    version: 1,
    source,
    variant_of: null,
    created_by: AUTHOR,
    reviewed_by: null,
    published_at: null,
    updated_at: '2026-11-11T08:00:00Z',
    content: {
      stem: '函数 $f(x)=|x-1|$ 的单调递减区间是（　）',
      options: [
        { key: 'A', text: '$(-\\infty,\\,1]$' },
        { key: 'B', text: '$[1,\\,+\\infty)$' },
      ],
      blanks: [],
      subquestions: [],
      attachments: [],
    },
    answer: { value: ['A'], equivalence_rules: {}, units: {} },
    teaching: {
      concept: '函数的单调性',
      hints: ['先去掉绝对值。', '分别看每一段的斜率。'],
      concept_rephrase: null,
      option_analysis: { A: '斜率为负，递减。', B: '这是递增的一段。' },
      visual: null,
      leak_markers: [],
    },
    solutions: [solution()],
    rubric: {},
    knowledge: [{ id: '44444444-4444-4444-8444-444444444444', code: 'math.function.monotonicity', title: '函数的单调性' }],
    region_tags: [],
    check_problems: [],
    versions: [{ version: 1, created_by: AUTHOR, created_at: '2026-11-11T08:00:00Z' }],
    history: [],
    ...overrides,
  }
}

/** 一个版本的快照；默认就是 detail() 的第 1 版内容。 */
export function snapshot(overrides: Partial<AdminVersionSnapshot> = {}): AdminVersionSnapshot {
  const base = detail()
  return {
    question_id: QUESTION_ID,
    version: 1,
    is_current: true,
    created_by: AUTHOR,
    created_at: '2026-11-11T08:00:00Z',
    title: base.title,
    difficulty: base.difficulty,
    grade: base.grade,
    content: base.content,
    answer: base.answer,
    teaching: base.teaching,
    solutions: base.solutions,
    knowledge: base.knowledge.map((node) => node.code),
    rubric: base.rubric,
    ...overrides,
  }
}
