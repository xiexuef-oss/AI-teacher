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

/** 契约里 type: object 且没有 properties 的字段，生成的类型是 Record<string, never>。 */
const obj = (value: object) => value as Record<string, never>

/** 一道解答题：两个小问、各自的参考答案、自查要点（含一条针对整份解答的），只有标准解法。 */
export function writtenDetail(overrides: Partial<AdminQuestionDetail> = {}): AdminQuestionDetail {
  return detail({
    type: 'solution',
    answer_mode: 'written',
    title: '含参二次函数的单调性与最值',
    content: {
      stem: '已知二次函数 $f(x)=x^2-2ax+3$（$a$ 为常数）。',
      options: [],
      blanks: [],
      subquestions: [
        {
          key: '1',
          stem: '若 $f(x)$ 在区间 $[1,+\\infty)$ 上单调递增，求 $a$ 的取值范围；',
          answer_mode: 'written',
          options: [],
          blanks: [],
        },
        {
          key: '2',
          stem: '当 $a=2$ 时，求 $f(x)$ 在区间 $[0,3]$ 上的最大值和最小值。',
          answer_mode: 'written',
          options: [],
          blanks: [],
        },
      ],
      attachments: [],
    },
    answer: {
      value: { '1': '$a\\le 1$', '2': '最大值 $3$，最小值 $-1$' },
      equivalence_rules: {},
      units: {},
    },
    teaching: {
      concept: '二次函数的单调性与最值',
      hints: ['先看开口方向。', '再看对称轴的位置。'],
      concept_rephrase: null,
      option_analysis: {},
      visual: null,
      leak_markers: ['a≤1', '最大值为3'],
    },
    solutions: [solution({ final_answer: '（1）$a\\le 1$；（2）最大值 $3$，最小值 $-1$' })],
    rubric: obj({
      points: [
        { key: 'p1', part: '1', text: '指出图像开口向上，对称轴是直线 $x=a$' },
        { key: 'p2', part: '1', text: '列出关于 $a$ 的不等式并得出范围' },
        { key: 'p3', part: '2', text: '求出最小值，并写明在哪一点取得' },
        { key: 'p4', part: null, text: '每一步写出依据，书写清楚' },
      ],
    }),
    ...overrides,
  })
}
