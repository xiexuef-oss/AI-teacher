import { describe, expect, it } from 'vitest'
import {
  bodyFromDetail,
  canonical,
  formFromDetail,
  isUnchanged,
  requestFromForm,
} from '../src/editing'
import { detail, experimentDetail, FAST, proofDetail, solution, writtenDetail } from './fixtures'
import type { AdminQuestionDetail } from '../src/api/types'

/** 契约里 type: object 且没有 properties 的字段，生成的类型是 Record<string, never>。 */
const obj = (value: object) => value as Record<string, never>

/** 一道填空题：空位、判定规则、单位规则、图解、两种解法、额外的泄题标记，什么都有。 */
export function fillDetail(): AdminQuestionDetail {
  return detail({
    answer_mode: 'fill',
    type: 'fill_blank',
    title: '光滑斜面上物块的加速度',
    content: {
      stem: '质量为 $2\\ \\text{kg}$ 的物块沿光滑斜面下滑，加速度的大小为 ____。',
      options: [],
      blanks: [{ key: 'b1', label: null, unit_hint: '需要写单位', placeholder: '数值和单位' }],
      subquestions: [],
      attachments: [],
      data_tables: [],
      safety: null, proof: null,
    },
    answer: {
      value: { b1: '5' },
      equivalence_rules: obj({ b1: { type: 'numeric', rel_tol: 0.001 } }),
      units: obj({ b1: { required: true, accepted: ['m/s²', 'm/s^2'] } }),
    },
    teaching: {
      concept: '牛顿第二定律',
      hints: ['先画受力图。', '沿斜面方向列方程。'],
      concept_rephrase: '合力决定加速度。',
      option_analysis: {},
      visual: { template_id: 'force_diagram', params: { angle_deg: 30, mass: 2, mu: 0, g: 10 }, caption: '拖动倾角。' },
      leak_markers: ['gsinθ'],
    },
    solutions: [solution({ final_answer: '$5\\ \\text{m/s}^2$' }), { ...FAST, final_answer: '$5$', key_points: [] }],
    rubric: obj({ multi_choice_rule: 'all_or_nothing' }),
  })
}

describe('表单与修改请求', () => {
  it.each([
    ['选择题', detail()],
    ['填空题（带规则、单位、图解、快速解法、额外标记）', fillDetail()],
    ['解答题（小问、参考答案、自查要点）', writtenDetail()],
    ['实验题（数据表、安全提示、格子的参考值、小问、自查要点）', experimentDetail()],
  ])('%s：原样放进表单再取出，和"题目详情原样还原"完全一致', (_name, source) => {
    const built = requestFromForm(formFromDetail(source), source)

    expect(built.ok).toBe(true)
    if (built.ok) {
      expect(canonical(built.body)).toBe(canonical(bodyFromDetail(source)))
      expect(isUnchanged(built.body, source)).toBe(true)
    }
  })

  it('改了标题就算有改动；修改说明不算内容，写不写都不影响"有没有改动"', () => {
    const source = detail()
    const form = formFromDetail(source)
    form.comment = '只写了说明'
    const same = requestFromForm(form, source)
    expect(same.ok && isUnchanged(same.body, source)).toBe(true)
    expect(same.ok && same.body.comment).toBe('只写了说明')

    form.title = '新标题'
    const changed = requestFromForm(form, source)
    expect(changed.ok && isUnchanged(changed.body, source)).toBe(false)
    expect(changed.ok && changed.body.title).toBe('新标题')
  })

  it('没有写修改说明时请求里没有 comment 字段', () => {
    const source = detail()
    const built = requestFromForm(formFromDetail(source), source)
    expect(built.ok && 'comment' in built.body).toBe(false)
  })

  it('选择题：勾选的集合没变就沿用原来的顺序；变了就按选项的顺序', () => {
    const source = detail({
      content: {
        stem: '多选',
        options: [
          { key: 'A', text: 'a' },
          { key: 'B', text: 'b' },
          { key: 'C', text: 'c' },
        ],
        blanks: [],
        subquestions: [],
        attachments: [],
        data_tables: [],
        safety: null, proof: null,
      },
      answer: { value: ['C', 'A'], equivalence_rules: {}, units: {} },
    })
    const form = formFromDetail(source)
    const same = requestFromForm(form, source)
    expect(same.ok && same.body.answer.value).toEqual(['C', 'A'])

    form.options[1]!.correct = true
    const more = requestFromForm(form, source)
    expect(more.ok && more.body.answer.value).toEqual(['A', 'B', 'C'])
  })

  it('填空题：每个空位的答案，来自表单里的那一行', () => {
    const source = fillDetail()
    const form = formFromDetail(source)
    form.blanks[0]!.answer = '10'

    const built = requestFromForm(form, source)

    expect(built.ok && built.body.answer.value).toEqual({ b1: '10' })
  })

  it('空行会被丢掉；知识点按逗号、空格、顿号分隔', () => {
    const source = detail()
    const form = formFromDetail(source)
    form.hints = ['第一层', '   ', '第二层']
    form.knowledge = 'math.function.monotonicity， math.function.concept  math.quadratic.graph'

    const built = requestFromForm(form, source)

    expect(built.ok && built.body.teaching.hints).toEqual(['第一层', '第二层'])
    expect(built.ok && built.body.knowledge).toEqual([
      'math.function.monotonicity',
      'math.function.concept',
      'math.quadratic.graph',
    ])
  })

  it('不能保存的输入给出具体的原因，而不是悄悄丢掉', () => {
    const source = fillDetail()
    const form = formFromDetail(source)
    form.title = '  '
    form.stem = ''
    form.rulesJson = '{坏了'
    form.unitsJson = '[1, 2]'
    form.rubricJson = '"不是对象"'
    form.visualParamsJson = '{"angle_deg": "三十"}'

    const built = requestFromForm(form, source)

    expect(built.ok).toBe(false)
    const errors = built.ok ? [] : built.errors
    expect(errors).toEqual(
      expect.arrayContaining([
        '标题不能为空',
        '题干不能为空',
        '判定规则不是合法的 JSON',
        '单位规则必须是 JSON 对象（花括号包起来的）',
        '评分细则必须是 JSON 对象（花括号包起来的）',
        '图解参数 angle_deg 必须是数字',
      ]),
    )
  })

  it('取消勾选"带图解"，请求里图解就是 null；取消"快速解法"，请求里只剩标准解法', () => {
    const source = fillDetail()
    const form = formFromDetail(source)
    form.visualOn = false
    form.fast.on = false

    const built = requestFromForm(form, source)

    expect(built.ok && built.body.teaching.visual).toBeNull()
    expect(built.ok && built.body.solutions.map((item) => item.kind)).toEqual(['standard'])
  })

  it('快速解法带着适用条件和边界；标准解法的这两项一定是 null', () => {
    const source = fillDetail()
    const built = requestFromForm(formFromDetail(source), source)

    expect(built.ok).toBe(true)
    if (built.ok) {
      const [standard, fast] = built.body.solutions
      expect([standard!.conditions, standard!.boundary]).toEqual([null, null])
      expect(fast!.conditions).toEqual(['斜面光滑'])
      expect(fast!.boundary).toBe('粗糙斜面不能用')
    }
  })

  it('canonical 不受对象键顺序影响，但受数组顺序影响', () => {
    expect(canonical({ a: 1, b: { c: 2, d: 3 } })).toBe(canonical({ b: { d: 3, c: 2 }, a: 1 }))
    expect(canonical([1, 2])).not.toBe(canonical([2, 1]))
  })
})

describe('解答题的表单', () => {
  it('小问、参考答案、自查要点各是一行；针对整份解答的要点没有小问（表单里是空字符串）', () => {
    const form = formFromDetail(writtenDetail())

    expect(form.subquestions).toEqual([
      { key: '1', stem: '若 $f(x)$ 在区间 $[1,+\\infty)$ 上单调递增，求 $a$ 的取值范围；', answer: '$a\\le 1$' },
      { key: '2', stem: '当 $a=2$ 时，求 $f(x)$ 在区间 $[0,3]$ 上的最大值和最小值。', answer: '最大值 $3$，最小值 $-1$' },
    ])
    expect(form.points.map((row) => [row.key, row.part])).toEqual([
      ['p1', '1'],
      ['p2', '1'],
      ['p3', '2'],
      ['p4', ''],
    ])
    expect(form.options).toEqual([])
    expect(form.blanks).toEqual([])
  })

  it('改小问的题干和参考答案：请求里的小问是 written，参考答案按键对应', () => {
    const source = writtenDetail()
    const form = formFromDetail(source)
    form.subquestions[0]!.stem = '（改）求 $a$ 的取值范围；'
    form.subquestions[1]!.answer = '最小值 $-1$，最大值 $3$'

    const built = requestFromForm(form, source)

    expect(built.ok).toBe(true)
    if (!built.ok) return
    expect(built.body.content.subquestions[0]).toEqual({
      key: '1',
      stem: '（改）求 $a$ 的取值范围；',
      answer_mode: 'written',
      options: [],
      blanks: [],
    })
    expect(built.body.answer.value).toEqual({ '1': '$a\\le 1$', '2': '最小值 $-1$，最大值 $3$' })
    expect(built.body.answer.equivalence_rules).toEqual({})
    expect(isUnchanged(built.body, source)).toBe(false)
  })

  it('加一个小问：多一个小问和一条参考答案；删掉一个小问：它的参考答案也跟着没了', () => {
    const source = writtenDetail()
    const form = formFromDetail(source)
    form.subquestions.push({ key: '3', stem: '再求……', answer: '略' })
    const added = requestFromForm(form, source)
    expect(added.ok && added.body.content.subquestions.map((item) => item.key)).toEqual(['1', '2', '3'])
    expect(added.ok && added.body.answer.value).toMatchObject({ '3': '略' })

    form.subquestions.splice(0, 1)
    const removed = requestFromForm(form, source)
    expect(removed.ok && removed.body.content.subquestions.map((item) => item.key)).toEqual(['2', '3'])
    expect(removed.ok && Object.keys(removed.body.answer.value as object)).toEqual(['2', '3'])
  })

  it('空行（没有键也没有题干）会被丢掉，不会变成一个空的小问', () => {
    const source = writtenDetail()
    const form = formFromDetail(source)
    form.subquestions.push({ key: '', stem: '', answer: '' })
    form.points.push({ key: '', part: '', text: '' })

    const built = requestFromForm(form, source)

    expect(built.ok && isUnchanged(built.body, source)).toBe(true)
  })

  it('自查要点：改文字、改归属的小问、加一条针对整份解答的要点（part 是 null）', () => {
    const source = writtenDetail()
    const form = formFromDetail(source)
    form.points[0]!.text = '（改）指出开口方向和对称轴'
    form.points[1]!.part = '2'
    form.points.push({ key: 'p5', part: '', text: '步骤完整' })

    const built = requestFromForm(form, source)

    expect(built.ok).toBe(true)
    if (!built.ok) return
    const points = (built.body.rubric as unknown as { points: unknown[] }).points
    expect(points).toEqual([
      { key: 'p1', part: '1', text: '（改）指出开口方向和对称轴' },
      { key: 'p2', part: '2', text: '列出关于 $a$ 的不等式并得出范围' },
      { key: 'p3', part: '2', text: '求出最小值，并写明在哪一点取得' },
      { key: 'p4', part: null, text: '每一步写出依据，书写清楚' },
      { key: 'p5', part: null, text: '步骤完整' },
    ])
    // 要点只有 key、part、text 三样：表单里没有"分值"这种东西
    for (const point of points) expect(Object.keys(point as object).sort()).toEqual(['key', 'part', 'text'])
  })

  it('评分细则里除了 points 之外的内容原样保留', () => {
    const source = writtenDetail({
      rubric: obj({ points: [{ key: 'p1', part: '1', text: '写出对称轴' }], note: '工程样例' }),
    })
    const form = formFromDetail(source)
    form.points[0]!.text = '写出对称轴和开口方向'

    const built = requestFromForm(form, source)

    expect(built.ok && built.body.rubric).toEqual({
      points: [{ key: 'p1', part: '1', text: '写出对称轴和开口方向' }],
      note: '工程样例',
    })
  })

  it('选择题和填空题的小问不经过表单：原样带回', () => {
    const source = fillDetail()

    const built = requestFromForm(formFromDetail(source), source)

    expect(built.ok && built.body.content.subquestions).toEqual(source.content.subquestions)
    expect(built.ok && 'points' in built.body.rubric).toBe(false)
  })
})

describe('实验题的表单', () => {
  const built = (source: AdminQuestionDetail, change: (form: ReturnType<typeof formFromDetail>) => void) => {
    const form = formFromDetail(source)
    change(form)
    return requestFromForm(form, source)
  }

  it('安全提示、数据表、留空格子的参考值、小问各是表单里的一块', () => {
    const source = experimentDetail()
    const form = formFromDetail(source)

    expect(form.safetyOn).toBe(true)
    expect(form.safetyLevel).toBe('low')
    expect(form.safetyNotes).toEqual(source.content.safety!.notes)
    expect(JSON.parse(form.dataTablesJson)).toEqual(source.content.data_tables)
    // 键带点的是留空格子的参考值；小问的参考答案在小问那一行里
    expect(JSON.parse(form.referenceCellsJson)).toEqual({ 't1.r1.v': '0.400', 't1.r2.v': '0.600' })
    expect(form.subquestions).toEqual([
      { key: '1', stem: '写出算平均速度的方法；', answer: '平均速度等于距离除以时间间隔' },
    ])
    expect(form.points.map((row) => [row.key, row.part])).toEqual([
      ['p1', 't1'],
      ['p2', '1'],
      ['p3', ''],
    ])
  })

  it('改一条安全提示：请求里只有安全提示变了，数据表和参考值原样带回', () => {
    const source = experimentDetail()

    const result = built(source, (form) => {
      form.safetyNotes[1] = '（改）这是纸面练习，不是操作指导。'
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.body.content.safety).toEqual({
      level: 'low',
      notes: [source.content.safety!.notes[0], '（改）这是纸面练习，不是操作指导。'],
    })
    expect(result.body.content.data_tables).toEqual(source.content.data_tables)
    expect(result.body.answer.value).toEqual(source.answer.value)
    expect(isUnchanged(result.body, source)).toBe(false)
  })

  it('取消"安全提示"：请求里 safety 就是 null（程序校验会拦住它，不能上线）', () => {
    const result = built(experimentDetail(), (form) => {
      form.safetyOn = false
    })

    expect(result.ok && result.body.content.safety).toBeNull()
  })

  it('改风险等级；空的安全提示行会被丢掉', () => {
    const result = built(experimentDetail(), (form) => {
      form.safetyLevel = 'high'
      form.safetyNotes.push('   ')
    })

    expect(result.ok && result.body.content.safety).toEqual({
      level: 'high',
      notes: experimentDetail().content.safety!.notes,
    })
  })

  it('改数据表里一个给定的格子：请求里的表跟着变', () => {
    const source = experimentDetail()
    const tables = JSON.parse(formFromDetail(source).dataTablesJson)
    tables[0].rows[0].cells[1].text = '4.10'

    const result = built(source, (form) => {
      form.dataTablesJson = JSON.stringify(tables)
    })

    expect(result.ok && result.body.content.data_tables[0]!.rows[0]!.cells[1]!.text).toBe('4.10')
  })

  it('小问的参考答案和格子的参考值合在 answer.value 一个对象里', () => {
    const result = built(experimentDetail(), (form) => {
      form.subquestions[0]!.answer = '（改）除以时间间隔'
      form.referenceCellsJson = JSON.stringify({ 't1.r1.v': '0.410', 't1.r2.v': '0.600' })
    })

    expect(result.ok && result.body.answer.value).toEqual({
      '1': '（改）除以时间间隔',
      't1.r1.v': '0.410',
      't1.r2.v': '0.600',
    })
  })

  it('自查要点可以针对一张数据表：part 就是表的键', () => {
    const result = built(experimentDetail(), (form) => {
      form.points[0]!.text = '（改）先换算单位'
    })

    const points = (result.ok && (result.body.rubric as unknown as { points: { part: string | null }[] }).points) || []
    expect(points.map((point) => point.part)).toEqual(['t1', '1', null])
    for (const point of points) expect(Object.keys(point).sort()).toEqual(['key', 'part', 'text'])
  })

  it('不能保存的输入给出具体的原因', () => {
    const result = built(experimentDetail(), (form) => {
      form.dataTablesJson = '[{坏了'
      form.referenceCellsJson = '[1, 2]'
    })

    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.errors).toEqual(
      expect.arrayContaining(['数据表不是合法的 JSON', '留空格子的参考值必须是 JSON 对象（花括号包起来的）']),
    )
  })

  it('数据表不是数组、参考值不是字符串，也给出原因', () => {
    const result = built(experimentDetail(), (form) => {
      form.dataTablesJson = '{"key": "t1"}'
      form.referenceCellsJson = JSON.stringify({ 't1.r1.v': 0.4 })
    })

    expect(result.ok).toBe(false)
    if (result.ok) return
    expect(result.errors).toEqual(
      expect.arrayContaining(['数据表必须是 JSON 数组（方括号包起来的）', '留空格子 t1.r1.v 的参考值必须是字符串']),
    )
  })

  it('选择题、填空题、解答题的数据表和安全提示不经过表单：原样带回（一直是空和 null）', () => {
    for (const source of [detail(), fillDetail(), writtenDetail()]) {
      const result = built(source, () => {})
      expect(result.ok && result.body.content.data_tables).toEqual([])
      expect(result.ok && result.body.content.safety).toBeNull()
    }
  })
})

describe('证明题的表单', () => {
  const built = (source: AdminQuestionDetail, change: (form: ReturnType<typeof formFromDetail>) => void) => {
    const form = formFromDetail(source)
    change(form)
    return requestFromForm(form, source)
  }

  it('已知、求证、参考证明、自查要点各是表单里的一块', () => {
    const source = proofDetail()
    const form = formFromDetail(source)

    expect(form.givens).toEqual(['$a>b>0$', '$c>d>0$'])
    expect(form.claim).toBe('$ac>bd$。')
    expect(form.proofSteps.map((row) => row.stage)).toEqual(['premise', 'construction', 'reasoning', 'conclusion'])
    expect(form.proofSteps[1]).toEqual({
      stage: 'construction',
      text: '引入中间量 $bc$：因为 $a>b$，$c>0$，所以 $ac>bc$。',
      reason: '不等式两边同乘正数，方向不变',
    })
    expect(form.points.map((row) => [row.key, row.part])).toEqual([
      ['p1', 'premise'],
      ['p2', 'construction'],
      ['p3', 'reasoning'],
      ['p4', 'conclusion'],
      ['p5', ''],
    ])
    expect(form.subquestions).toEqual([])
  })

  it('表单没改动：请求和题目详情一模一样，不算有改动', () => {
    const source = proofDetail()

    const result = built(source, () => {})

    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(isUnchanged(result.body, source)).toBe(true)
    expect(result.body.content.proof).toEqual(source.content.proof)
    expect(result.body.answer.value).toEqual(source.answer.value)
    expect(result.body.content.subquestions).toEqual([])
  })

  it('改求证、加一条已知：请求里的已知和求证跟着变，参考证明原样带回', () => {
    const source = proofDetail()

    const result = built(source, (form) => {
      form.claim = '（改）$ac>bd$'
      form.givens.push('$a,b,c,d$ 都是实数')
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.body.content.proof).toEqual({
      givens: ['$a>b>0$', '$c>d>0$', '$a,b,c,d$ 都是实数'],
      claim: '（改）$ac>bd$',
    })
    expect(result.body.answer.value).toEqual(source.answer.value)
    expect(isUnchanged(result.body, source)).toBe(false)
  })

  it('空的已知会被丢掉（已知可以一条都没有）', () => {
    const result = built(proofDetail(), (form) => {
      form.givens = ['  ', '']
    })

    expect(result.ok && result.body.content.proof).toEqual({ givens: [], claim: '$ac>bd$。' })
  })

  it('改参考证明的一步：阶段、文字、依据各自带回，顺序不变', () => {
    const source = proofDetail()

    const result = built(source, (form) => {
      form.proofSteps[2]!.stage = 'construction'
      form.proofSteps[2]!.reason = '（改）依据'
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return
    const steps = (result.body.answer.value as { steps: { stage: string; text: string; reason: string }[] }).steps
    expect(steps.map((step) => step.stage)).toEqual(['premise', 'construction', 'construction', 'conclusion'])
    expect(steps[2]!.reason).toBe('（改）依据')
    expect(steps[2]!.text).toBe('因为 $c>d$，$b>0$，所以 $bc>bd$。')
    expect(Object.keys(steps[0]!).sort()).toEqual(['reason', 'stage', 'text'])
  })

  it('加一步、删一步、挪一步：参考证明的顺序就是表单里的顺序；整行都是空的会被丢掉', () => {
    const source = proofDetail()
    const original = (source.answer.value as { steps: { text: string }[] }).steps.map((step) => step.text)

    const result = built(source, (form) => {
      form.proofSteps.push({ stage: 'reasoning', text: '', reason: '  ' }) // 空行
      const [first] = form.proofSteps.splice(0, 1) // 把第一步挪到第三位
      form.proofSteps.splice(2, 0, first!)
      form.proofSteps.splice(0, 1) // 删掉现在的第一步（原来的第二步）
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return
    const steps = (result.body.answer.value as { steps: { text: string }[] }).steps
    expect(steps.map((step) => step.text)).toEqual([original[2], original[0], original[3]])
  })

  it('自查要点：part 是证明阶段，整份证明的要点没有阶段（part 是 null），不带分值', () => {
    const result = built(proofDetail(), (form) => {
      form.points[0]!.part = 'reasoning'
      form.points[0]!.text = '（改）要点'
    })

    const points = (result.ok && (result.body.rubric as unknown as { points: { key: string; part: string | null }[] }).points) || []
    expect(points.map((point) => point.part)).toEqual(['reasoning', 'construction', 'reasoning', 'conclusion', null])
    for (const point of points) expect(Object.keys(point).sort()).toEqual(['key', 'part', 'text'])
  })

  it('参考证明里阶段不认识：表单里按 reasoning 显示，保存时是 reasoning（程序校验不会再报阶段无效）', () => {
    const source = proofDetail({
      answer: { value: { steps: [{ stage: 'intro', text: 'x', reason: 'y' }] }, equivalence_rules: {}, units: {} },
    })

    const form = formFromDetail(source)

    expect(form.proofSteps).toEqual([{ stage: 'reasoning', text: 'x', reason: 'y' }])
  })

  it('参考答案不是 {steps: [...]} 时表单里没有步骤，不崩溃', () => {
    const source = proofDetail({ answer: { value: ['A'], equivalence_rules: {}, units: {} } })

    expect(formFromDetail(source).proofSteps).toEqual([])
    expect(formFromDetail(proofDetail({ answer: { value: { steps: 'x' }, equivalence_rules: {}, units: {} } })).proofSteps).toEqual([])
  })

  it('其他题型没有已知和求证：proof 一直是 null，原样带回', () => {
    for (const source of [detail(), fillDetail(), writtenDetail(), experimentDetail()]) {
      const result = built(source, () => {})
      expect(result.ok && result.body.content.proof).toBeNull()
    }
  })

  it('证明题没有小问：subquestions 一直是空，不会因为表单而多出小问', () => {
    const result = built(proofDetail(), (form) => {
      form.subquestions.push({ key: '1', stem: '偷偷加的小问', answer: '答案' })
    })

    expect(result.ok && result.body.content.subquestions).toEqual([])
    expect(result.ok && result.body.answer.value).toEqual(proofDetail().answer.value)
  })
})
