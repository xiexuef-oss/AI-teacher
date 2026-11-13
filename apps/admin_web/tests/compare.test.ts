import { describe, expect, it } from 'vitest'
import { compareSnapshots, jsonLines, type FieldDiff } from '../src/compare'
import { FAST, snapshot, solution, writtenDetail } from './fixtures'

const field = (comparison: ReturnType<typeof compareSnapshots>, key: string): FieldDiff => {
  for (const section of comparison.sections) {
    const found = section.fields.find((item) => item.key === key)
    if (found) return found
  }
  throw new Error(`没有字段 ${key}`)
}

const obj = (value: object) => value as Record<string, never>

describe('compareSnapshots', () => {
  it('两个版本完全一样：没有任何改动，每个字段都是没变', () => {
    const comparison = compareSnapshots(snapshot(), snapshot({ version: 2, is_current: false }))

    expect(comparison.changed).toBe(false)
    expect(comparison.changedTitles).toEqual([])
    expect(comparison.sections.flatMap((item) => item.fields).every((item) => !item.changed)).toBe(true)
  })

  it('改了标题、难度、年级：只有"基本信息"有改动，年级用中文名，null 是"不限"', () => {
    const comparison = compareSnapshots(snapshot(), snapshot({ title: '新标题', difficulty: 4, grade: null }))

    expect(comparison.changedTitles).toEqual(['基本信息'])
    expect(field(comparison, 'title')).toMatchObject({ changed: true, left: '绝对值函数的单调递减区间', right: '新标题' })
    expect(field(comparison, 'difficulty')).toMatchObject({ left: '2', right: '4', changed: true })
    expect(field(comparison, 'grade')).toMatchObject({ left: '高一', right: '不限', changed: true })
  })

  it('改了题干：带文本级差异，题干里有公式就标出来', () => {
    const base = snapshot()
    const comparison = compareSnapshots(
      base,
      snapshot({ content: { ...base.content, stem: '函数 $f(x)=|x+1|$ 的单调递减区间是（　）' } }),
    )

    const stem = field(comparison, 'stem')
    expect(stem.changed).toBe(true)
    expect(stem.math).toBe(true)
    expect(stem.leftSegs!.some((seg) => seg.kind === 'del' && seg.text.includes('-'))).toBe(true)
    expect(stem.rightSegs!.some((seg) => seg.kind === 'add' && seg.text.includes('+'))).toBe(true)
    expect(comparison.changedTitles).toEqual(['题面'])
  })

  it('选项：改了一个选项的文字，只有那一行是 changed', () => {
    const base = snapshot()
    const options = [...base.content.options]
    options[1] = { key: 'B', text: '$[1,\\,+\\infty]$' }

    const comparison = compareSnapshots(base, snapshot({ content: { ...base.content, options } }))

    expect(field(comparison, 'options').rows.map((row) => row.kind)).toEqual(['same', 'changed'])
  })

  it('答案：选择题的正确选项变了；填空题每个空位一行', () => {
    const choice = compareSnapshots(
      snapshot(),
      snapshot({ answer: { value: ['A', 'C'], equivalence_rules: obj({}), units: obj({}) } }),
    )
    expect(field(choice, 'answer').rows.map((row) => [row.kind, row.left, row.right])).toEqual([['changed', 'A', 'A、C']])

    const fill = compareSnapshots(
      snapshot({ answer: { value: { b1: '5', b2: '7' }, equivalence_rules: obj({}), units: obj({}) } }),
      snapshot({ answer: { value: { b1: '5', b2: '8' }, equivalence_rules: obj({}), units: obj({}) } }),
    )
    expect(field(fill, 'answer').rows.map((row) => row.kind)).toEqual(['same', 'changed'])
  })

  it('判定规则：JSON 逐行对比，只有改动的那一行不同', () => {
    const rules = (tol: number) => obj({ b1: { type: 'numeric', rel_tol: tol } })
    const comparison = compareSnapshots(
      snapshot({ answer: { value: { b1: '5' }, equivalence_rules: rules(0.001), units: obj({}) } }),
      snapshot({ answer: { value: { b1: '5' }, equivalence_rules: rules(0.01), units: obj({}) } }),
    )

    const rows = field(comparison, 'rules').rows
    expect(rows.filter((row) => row.kind === 'changed')).toHaveLength(1)
    expect(rows.filter((row) => row.kind === 'changed')[0]!.left).toContain('0.001')
    expect(field(comparison, 'units').changed).toBe(false)
  })

  it('解法：右边多了快速解法，整个快速解法都是新加的；审核标记也会比较', () => {
    const comparison = compareSnapshots(
      snapshot({ solutions: [solution({ reviewed: true, reviewed_by: 'r' })] }),
      snapshot({ solutions: [solution({ reviewed: false }), FAST] }),
    )

    expect(field(comparison, 'standard.review')).toMatchObject({ left: '已审核', right: '未审核', changed: true })
    expect(field(comparison, 'fast.review')).toMatchObject({ left: '没有这种解法', right: '未审核', changed: true })
    expect(field(comparison, 'fast.steps').rows.every((row) => row.kind === 'added')).toBe(true)
    expect(field(comparison, 'fast.conditions').rows.map((row) => row.right)).toEqual(['斜面光滑'])
    expect(field(comparison, 'fast.boundary')).toMatchObject({ left: '', right: '粗糙斜面不能用' })
    expect(comparison.changedTitles).toContain('解法')
  })

  it('分层提示：多了一层、改了一层', () => {
    const base = snapshot()
    const comparison = compareSnapshots(
      base,
      snapshot({ teaching: { ...base.teaching, hints: ['先去掉绝对值，分段看。', '分别看每一段的斜率。', '注意端点。'] } }),
    )

    expect(field(comparison, 'hints').rows.map((row) => row.kind)).toEqual(['changed', 'same', 'added'])
    expect(field(comparison, 'hints').math).toBe(false)
  })

  it('图解有无、知识点、评分细则、额外标记都能比较', () => {
    const base = snapshot()
    const comparison = compareSnapshots(
      base,
      snapshot({
        teaching: {
          ...base.teaching,
          visual: { template_id: 'quadratic_graph', params: { a: 1, b: -2, c: -3 }, caption: '拖动系数。' },
          leak_markers: ['gsinθ'],
        },
        knowledge: ['math.function.concept', 'math.function.monotonicity'],
        rubric: obj({ multi_choice_rule: 'all_or_nothing' }),
      }),
    )

    expect(field(comparison, 'visual').rows.every((row) => row.kind === 'added')).toBe(true)
    expect(field(comparison, 'markers').rows.map((row) => row.kind)).toEqual(['added'])
    expect(field(comparison, 'knowledge').rows.map((row) => row.kind)).toEqual(['added', 'same'])
    expect(field(comparison, 'rubric').changed).toBe(true)
    expect(comparison.changedTitles).toEqual(['教学辅助', '知识点', '评分细则'])
  })

  it('没有小问和附件时这两项没有行；附件按 JSON 对比', () => {
    const none = compareSnapshots(snapshot(), snapshot())
    expect(field(none, 'subquestions').rows).toEqual([])
    expect(field(none, 'attachments').rows).toEqual([])

    const base = snapshot()
    const withAttachment = snapshot({
      content: { ...base.content, attachments: [{ kind: 'image', media_id: null, alt: '受力图' }] },
    })
    expect(field(compareSnapshots(base, withAttachment), 'attachments').changed).toBe(true)
    expect(field(compareSnapshots(base, withAttachment), 'subquestions').changed).toBe(false)
  })
})

/** 解答题的快照：内容取自 writtenDetail()。 */
function writtenSnapshot(overrides: Parameters<typeof snapshot>[0] = {}) {
  const base = writtenDetail()
  return snapshot({
    title: base.title,
    content: base.content,
    answer: base.answer,
    teaching: base.teaching,
    solutions: base.solutions,
    rubric: base.rubric,
    ...overrides,
  })
}

describe('解答题的对比', () => {
  it('小问、参考答案、自查要点逐行对比：改了哪一条一眼就能看出', () => {
    const left = writtenSnapshot()
    const [first, second] = left.content.subquestions
    const right = writtenSnapshot({
      version: 2,
      is_current: false,
      content: { ...left.content, subquestions: [{ ...first!, stem: '（改）求 $a$ 的取值范围；' }, second!] },
      answer: { ...left.answer, value: { '1': '$a\\le 1$', '2': '最小值 $-1$' } },
      rubric: obj({
        points: [
          { key: 'p1', part: '1', text: '指出图像开口向上，对称轴是直线 $x=a$' },
          { key: 'p2', part: '1', text: '（改）列出不等式并得出范围' },
          { key: 'p3', part: '2', text: '求出最小值，并写明在哪一点取得' },
          { key: 'p4', part: null, text: '每一步写出依据，书写清楚' },
          { key: 'p5', part: '2', text: '比较端点，得出最大值' },
        ],
      }),
    })

    const comparison = compareSnapshots(left, right)

    expect(field(comparison, 'subquestions').rows.map((row) => row.kind)).toEqual(['changed', 'same'])
    expect(field(comparison, 'answer').rows.map((row) => row.kind)).toEqual(['same', 'changed'])
    expect(field(comparison, 'rubric').rows.map((row) => row.kind)).toEqual([
      'same',
      'changed',
      'same',
      'same',
      'added',
    ])
    expect(comparison.changedTitles).toEqual(['题面', '答案', '评分细则'])
  })

  it('小问行有键和题干；参考答案行是"键 = 答案"；要点行有键、所属小问、文字，没有分值', () => {
    const shot = writtenSnapshot()

    const comparison = compareSnapshots(shot, shot)

    const subquestions = field(comparison, 'subquestions').rows.map((row) => row.left)
    expect(subquestions[0]).toMatch(/^1｜.*求 \$a\$ 的取值范围/)
    expect(field(comparison, 'answer').rows.map((row) => row.left)).toEqual([
      '1 = $a\\le 1$',
      '2 = 最大值 $3$，最小值 $-1$',
    ])
    const points = field(comparison, 'rubric').rows.map((row) => row.left)
    expect(points).toEqual([
      'p1｜第 1 问｜指出图像开口向上，对称轴是直线 $x=a$',
      'p2｜第 1 问｜列出关于 $a$ 的不等式并得出范围',
      'p3｜第 2 问｜求出最小值，并写明在哪一点取得',
      'p4｜整份解答｜每一步写出依据，书写清楚',
    ])
  })

  it('评分细则里除了要点之外的内容仍按 JSON 逐行对比', () => {
    const left = writtenSnapshot()
    const right = writtenSnapshot({
      rubric: obj({ ...(left.rubric as object), note: '工程样例' }),
    })

    const rows = field(compareSnapshots(left, right), 'rubric').rows

    expect(rows.filter((row) => row.kind === 'added').length).toBeGreaterThan(0)
    expect(rows.slice(0, 4).every((row) => row.kind === 'same')).toBe(true)
  })
})

describe('jsonLines', () => {
  it('键排好序再缩进；空对象、空数组、null 没有行', () => {
    expect(jsonLines({ b: 1, a: { d: 2, c: 3 } })).toEqual(['{', '  "a": {', '    "c": 3,', '    "d": 2', '  },', '  "b": 1', '}'])
    expect(jsonLines({})).toEqual([])
    expect(jsonLines([])).toEqual([])
    expect(jsonLines(null)).toEqual([])
  })
})
