// 编辑表单与"修改"请求之间的转换。全部是纯函数，好测：
//   formFromDetail   题目详情 → 表单（文本框里的字符串）
//   requestFromForm  表单 → AdminQuestionEdit 请求（或者一组错误）
//   bodyFromDetail   题目详情原样还原成请求；表单没改动时 requestFromForm 的结果必须与它一致
import type {
  AdminQuestionDetail,
  AdminQuestionEdit,
  AdminSolutionInput,
  Grade,
  ProofStage,
  SolutionKind,
} from './api/types'

/** Fields shared by a persisted question and an import candidate. */
export type EditorDetail = Pick<AdminQuestionDetail,
  'id' | 'version' | 'review_revision' | 'answer_mode' | 'title' | 'difficulty' | 'grade' | 'content' | 'answer' | 'teaching' | 'rubric'> & {
  solutions: AdminSolutionInput[]
  knowledge: Array<{ code: string }>
}

export interface OptionRow {
  key: string
  text: string
  analysis: string
  correct: boolean
}

export interface BlankRow {
  key: string
  label: string
  unitHint: string
  placeholder: string
  answer: string
}

/** 解答题的一个小问：题干和它的参考答案（参考答案只用来对照，不参与自动判定）。 */
export interface SubquestionRow {
  key: string
  stem: string
  answer: string
}

/** 证明题参考证明里的一步：阶段、这一步写了什么、依据。参考证明只用来给学生对照，不参与任何判定。 */
export interface ProofStepRow {
  stage: ProofStage
  text: string
  reason: string
}

/** 解答题、实验题、证明题的一条自查要点。part 是它针对的小问（证明题是证明阶段）的键，空字符串表示针对整份作答。不带分值：这不是评分。 */
export interface PointRow {
  key: string
  part: string
  text: string
}

export interface SolutionForm {
  on: boolean
  steps: string[]
  finalAnswer: string
  keyPoints: string[]
  conditions: string[]
  boundary: string
}

/** 实验题的风险分级。high（高风险）现在不收录：程序校验会拦住，这里只是让审校员能看到、能改。 */
export type SafetyLevel = 'low' | 'medium' | 'high'

type DataTables = AdminQuestionEdit['content']['data_tables']

export interface EditorForm {
  attachments: AdminQuestionEdit['content']['attachments']
  title: string
  difficulty: number
  grade: Grade | ''
  stem: string
  options: OptionRow[]
  blanks: BlankRow[]
  subquestions: SubquestionRow[]
  points: PointRow[]
  /** 实验题的安全提示（每道实验题必须有，上线前要审校员确认）。 */
  safetyOn: boolean
  safetyLevel: SafetyLevel
  safetyNotes: string[]
  /** 实验题的数据表（JSON 数组）：value 为 null 的格子由学生填写。 */
  dataTablesJson: string
  /** 实验题留空格子的参考值（JSON 对象，键是"表键.行键.列键"）；小问的参考答案在小问那几行里。 */
  referenceCellsJson: string
  /** 证明题的已知条件（界面上编号成 ①②③）。 */
  givens: string[]
  /** 证明题的求证。 */
  claim: string
  /** 证明题的参考证明：一行一步，顺序就是证明的顺序。 */
  proofSteps: ProofStepRow[]
  rulesJson: string
  unitsJson: string
  concept: string
  hints: string[]
  conceptRephrase: string
  visualOn: boolean
  visualTemplate: string
  visualParamsJson: string
  visualCaption: string
  leakMarkers: string[]
  /** 保留原审核坐标；留空文本不等于明确删除。旧草稿缺字段沿用来源版本。 */
  referenceLinksJson?: string
  standard: SolutionForm
  fast: SolutionForm
  knowledge: string
  rubricJson: string
  comment: string
}

/** Internal form projection, also used by unpublished import candidates; never send directly. */
export type EditorBody = Omit<AdminQuestionEdit, 'expected_review_revision'>
export type Built = { ok: true; body: EditorBody } | { ok: false; errors: string[] }

const CHOICE_MODES = new Set(['single_choice', 'multiple_choice'])
const FILL_MODES = new Set(['fill'])
const WRITTEN_MODES = new Set(['written'])
const EXPERIMENT_MODES = new Set(['experiment'])
const PROOF_MODES = new Set(['proof'])
const STAGES: ProofStage[] = ['premise', 'construction', 'reasoning', 'conclusion']

const pretty = (value: unknown): string => JSON.stringify(value ?? {}, null, 2)
const orNull = (text: string): string | null => (text === '' ? null : text)

/** 对象键排序后的 JSON，用来比较"内容有没有变"（文本框里解析出来的对象键顺序可能变）。 */
export function canonical(value: unknown): string {
  const sort = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(sort)
    if (node && typeof node === 'object') {
      return Object.fromEntries(
        Object.entries(node as Record<string, unknown>)
          .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
          .map(([key, inner]) => [key, sort(inner)]),
      )
    }
    return node
  }
  return JSON.stringify(sort(value))
}

interface RubricPoint {
  key: string
  part: string | null
  text: string
}

/** 评分细则里的自查要点；不是数组或形状不对的项一律忽略。 */
function rubricPoints(rubric: unknown): RubricPoint[] {
  const points = (rubric as { points?: unknown } | null)?.points
  if (!Array.isArray(points)) return []
  return points.filter(
    (point): point is RubricPoint =>
      !!point && typeof point === 'object' && typeof point.key === 'string' && typeof point.text === 'string',
  )
}

const isBlankRow = (...texts: string[]): boolean => texts.every((text) => text.trim() === '')

/** 留空格子的参考值的键是"表键.行键.列键"（表、行、列的键里不会有点）；小问的键没有点。 */
const isCellKey = (key: string): boolean => key.split('.').length === 3

/** 参考证明里的步骤；不是数组或形状不对的项一律忽略，阶段不认识的按 reasoning 显示（程序校验会指出来）。 */
function referenceSteps(answers: Record<string, unknown>): ProofStepRow[] {
  const steps = answers.steps
  if (!Array.isArray(steps)) return []
  return steps
    .filter(
      (step): step is { stage?: unknown; text: string; reason: string } =>
        !!step && typeof step === 'object' && typeof step.text === 'string' && typeof step.reason === 'string',
    )
    .map((step) => ({
      stage: STAGES.includes(step.stage as ProofStage) ? (step.stage as ProofStage) : 'reasoning',
      text: step.text,
      reason: step.reason,
    }))
}

function solutionForm(detail: EditorDetail, kind: SolutionKind): SolutionForm {
  const found = detail.solutions.find((solution) => solution.kind === kind)
  return {
    on: found !== undefined,
    steps: [...(found?.steps ?? [])],
    finalAnswer: found?.final_answer ?? '',
    keyPoints: [...(found?.key_points ?? [])],
    conditions: [...(found?.conditions ?? [])],
    boundary: found?.boundary ?? '',
  }
}

export function formFromDetail(detail: EditorDetail): EditorForm {
  const correct = new Set(Array.isArray(detail.answer.value) ? detail.answer.value.map(String) : [])
  const answers =
    detail.answer.value && !Array.isArray(detail.answer.value) && typeof detail.answer.value === 'object'
      ? (detail.answer.value as Record<string, unknown>)
      : {}
  const visual = detail.teaching.visual
  const safety = detail.content.safety
  const cellReferences = Object.fromEntries(Object.entries(answers).filter(([key]) => isCellKey(key)))
  return {
    attachments: detail.content.attachments.map(item => ({...item})),
    title: detail.title,
    difficulty: detail.difficulty,
    grade: detail.grade ?? '',
    stem: detail.content.stem,
    options: detail.content.options.map((option) => ({
      key: option.key,
      text: option.text,
      analysis: detail.teaching.option_analysis[option.key] ?? '',
      correct: correct.has(option.key),
    })),
    blanks: detail.content.blanks.map((blank) => ({
      key: blank.key,
      label: blank.label ?? '',
      unitHint: blank.unit_hint ?? '',
      placeholder: blank.placeholder ?? '',
      answer: answers[blank.key] === undefined ? '' : String(answers[blank.key]),
    })),
    subquestions: detail.content.subquestions.map((sub) => ({
      key: sub.key,
      stem: sub.stem,
      answer: answers[sub.key] === undefined ? '' : String(answers[sub.key]),
    })),
    points: rubricPoints(detail.rubric).map((point) => ({
      key: point.key,
      part: point.part ?? '',
      text: point.text,
    })),
    safetyOn: safety !== null,
    safetyLevel: safety?.level ?? 'low',
    safetyNotes: [...(safety?.notes ?? [])],
    dataTablesJson: JSON.stringify(detail.content.data_tables, null, 2),
    referenceCellsJson: pretty(cellReferences),
    givens: [...(detail.content.proof?.givens ?? [])],
    claim: detail.content.proof?.claim ?? '',
    proofSteps: referenceSteps(answers),
    rulesJson: pretty(detail.answer.equivalence_rules),
    unitsJson: pretty(detail.answer.units),
    concept: detail.teaching.concept ?? '',
    hints: [...detail.teaching.hints],
    conceptRephrase: detail.teaching.concept_rephrase ?? '',
    visualOn: visual !== null,
    visualTemplate: visual?.template_id ?? '',
    visualParamsJson: pretty(visual?.params),
    visualCaption: visual?.caption ?? '',
    leakMarkers: [...detail.teaching.leak_markers],
    referenceLinksJson: detail.teaching.reference_links === undefined
      ? undefined : JSON.stringify(detail.teaching.reference_links, null, 2),
    standard: solutionForm(detail, 'standard'),
    fast: solutionForm(detail, 'fast'),
    knowledge: detail.knowledge.map((node) => node.code).join(', '),
    rubricJson: pretty(detail.rubric),
    comment: '',
  }
}

function solutionInput(kind: SolutionKind, form: SolutionForm): AdminSolutionInput {
  const keep = (items: string[]) => items.filter((item) => item.trim() !== '')
  const fast = kind === 'fast'
  return {
    kind,
    steps: keep(form.steps),
    final_answer: form.finalAnswer,
    key_points: keep(form.keyPoints),
    conditions: fast ? keep(form.conditions) : null,
    boundary: fast ? orNull(form.boundary) : null,
  }
}

/** 题目详情原样还原成一次"修改"请求（不含修改说明）。 */
export function bodyFromDetail(detail: EditorDetail): EditorBody {
  return {
    expected_version: detail.version,
    title: detail.title,
    difficulty: detail.difficulty,
    grade: detail.grade,
    content: detail.content,
    answer: detail.answer,
    teaching: detail.teaching,
    solutions: detail.solutions.map((solution) => ({
      kind: solution.kind,
      steps: solution.steps,
      final_answer: solution.final_answer,
      key_points: solution.key_points,
      conditions: solution.conditions,
      boundary: solution.boundary,
    })),
    knowledge: detail.knowledge.map((node) => node.code),
    rubric: detail.rubric,
  }
}

/** 契约里 type: object 且没有 properties 的字段，生成出来是 Record<string, never>。 */
type Obj = Record<string, never>

type ReferenceLinks = NonNullable<AdminQuestionEdit['teaching']['reference_links']>
const sourceBlock = /^(stem|subquestion:[1-9][0-9]{0,2}:stem|option:[1-9][0-9]{0,2}|subquestion:[1-9][0-9]{0,2}:option:[1-9][0-9]{0,2}|proof:given:[1-9][0-9]{0,2}|proof:claim|hint:[1-9][0-9]{0,2}|rephrase|solution:(standard|fast):(step:[1-9][0-9]{0,2}|final_answer|condition:[1-9][0-9]{0,2}|boundary|key_point:[1-9][0-9]{0,2})|visual:(caption|static_fallback)|rubric:point:[1-9][0-9]{0,2}|reference_cell:[1-9][0-9]{0,2}:[1-9][0-9]{0,2}:[1-9][0-9]{0,2}|reference_step:[1-9][0-9]{0,2}:(text|reason))$/
const targetBlock = /^(hint:[1-9][0-9]{0,2}|rephrase|solution:(standard|fast):step:[1-9][0-9]{0,2}|visual:caption)$/
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
const exactKeys = (value: Record<string, unknown>, keys: string[]) =>
  Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))

function parseReferenceLinks(text: string, errors: string[]): ReferenceLinks {
  try {
    const parsed: unknown = JSON.parse(text)
    if (!Array.isArray(parsed) || parsed.length > 64) throw new Error()
    const seen = new Set<string>(), counts = new Map<string, number>()
    for (const item of parsed) {
      if (!record(item) || !exactKeys(item, ['target_block_id', 'source_span', 'independent_safe']) ||
        typeof item.target_block_id !== 'string' || targetBlock.exec(item.target_block_id)?.[0] !== item.target_block_id ||
        typeof item.independent_safe !== 'boolean' || !record(item.source_span)) throw new Error()
      const span = item.source_span
      if (!exactKeys(span, ['block_id', 'block_sha256', 'start', 'end']) ||
        typeof span.block_id !== 'string' || span.block_id.length > 64 || sourceBlock.exec(span.block_id)?.[0] !== span.block_id ||
        typeof span.block_sha256 !== 'string' || span.block_sha256.length !== 64 || !/^[a-f0-9]{64}$/.test(span.block_sha256) ||
        typeof span.start !== 'number' || !Number.isInteger(span.start) || span.start < 0 || span.start > 3999 ||
        typeof span.end !== 'number' || !Number.isInteger(span.end) || span.end <= span.start || span.end > 4000) throw new Error()
      const identity = canonical([item.target_block_id, span.block_id, span.block_sha256, span.start, span.end])
      if (seen.has(identity)) throw new Error()
      seen.add(identity)
      const count = (counts.get(item.target_block_id) ?? 0) + 1
      if (count > 8) throw new Error()
      counts.set(item.target_block_id, count)
    }
    return parsed as ReferenceLinks
  } catch {
    errors.push('引用注记必须是有效的 JSON 数组，包含正确的内容块、摘要和整数范围；不能重复或添加未知字段')
    return []
  }
}

function parseObject(label: string, text: string, errors: string[]): Obj {
  if (text.trim() === '') return {}
  try {
    const parsed: unknown = JSON.parse(text)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Obj
    }
    errors.push(`${label}必须是 JSON 对象（花括号包起来的）`)
  } catch {
    errors.push(`${label}不是合法的 JSON`)
  }
  return {}
}

function parseTables(text: string, errors: string[]): DataTables {
  if (text.trim() === '') return []
  try {
    const parsed: unknown = JSON.parse(text)
    if (Array.isArray(parsed)) return parsed as DataTables
    errors.push('数据表必须是 JSON 数组（方括号包起来的）')
  } catch {
    errors.push('数据表不是合法的 JSON')
  }
  return []
}

function parseReferenceCells(text: string, errors: string[]): Record<string, string> {
  const parsed = parseObject('留空格子的参考值', text, errors) as unknown as Record<string, unknown>
  const cells: Record<string, string> = {}
  for (const [key, value] of Object.entries(parsed)) {
    if (typeof value === 'string') cells[key] = value
    else errors.push(`留空格子 ${key} 的参考值必须是字符串`)
  }
  return cells
}

export function requestFromForm(form: EditorForm, detail: EditorDetail): Built {
  const errors: string[] = []
  const keep = (items: string[]) => items.filter((item) => item.trim() !== '')

  if (form.title.trim() === '') errors.push('标题不能为空')
  if (form.stem.trim() === '') errors.push('题干不能为空')

  const rules = parseObject('判定规则', form.rulesJson, errors)
  const units = parseObject('单位规则', form.unitsJson, errors)
  const written = WRITTEN_MODES.has(detail.answer_mode)
  const experiment = EXPERIMENT_MODES.has(detail.answer_mode)
  const proof = PROOF_MODES.has(detail.answer_mode)
  // 解答题、实验题、证明题都有自查要点，它们的评分细则由"自查要点"那几行生成，其余题型是一段 JSON；
  // 解答题和实验题还分小问，证明题没有小问
  const subjective = written || experiment || proof
  const withParts = written || experiment
  const rubric = subjective ? ({} as Obj) : parseObject('评分细则', form.rubricJson, errors)
  const referenceText = form.referenceLinksJson ?? (detail.teaching.reference_links === undefined
    ? undefined : JSON.stringify(detail.teaching.reference_links))
  const referenceLinks = referenceText === undefined ? undefined : parseReferenceLinks(referenceText, errors)

  let visual: AdminQuestionEdit['teaching']['visual'] = null
  if (form.visualOn) {
    const params = parseObject('图解参数', form.visualParamsJson, errors)
    const numbers: Record<string, number> = {}
    for (const [name, value] of Object.entries(params as Record<string, unknown>)) {
      if (typeof value === 'number' && Number.isFinite(value)) numbers[name] = value
      else errors.push(`图解参数 ${name} 必须是数字`)
    }
    if (form.visualTemplate.trim() === '') errors.push('图解要选一个模板')
    visual = {
      template_id: form.visualTemplate.trim(),
      params: numbers,
      caption: form.visualCaption,
    }
  }

  // 答案：选择题是勾选的选项键（选中的集合没变就沿用原来的顺序），填空题是每个空位的值
  let value: unknown = detail.answer.value
  if (CHOICE_MODES.has(detail.answer_mode)) {
    const selected = new Set(form.options.filter((row) => row.correct).map((row) => row.key))
    const original = Array.isArray(detail.answer.value) ? detail.answer.value.map(String) : []
    const sameSet = original.length === selected.size && original.every((key) => selected.has(key))
    value = sameSet ? original : form.options.filter((row) => row.correct).map((row) => row.key)
  } else if (FILL_MODES.has(detail.answer_mode)) {
    value = Object.fromEntries(form.blanks.map((row) => [row.key, row.answer]))
  }

  // 解答题、实验题：小问和它们的参考答案是同一批行；整行都是空的就是没填，丢掉
  const subquestionRows = form.subquestions.filter((row) => !isBlankRow(row.key, row.stem, row.answer))
  const subquestions = withParts
    ? subquestionRows.map((row) => ({
        key: row.key,
        stem: row.stem,
        answer_mode: 'written' as const,
        options: [],
        blanks: [],
      }))
    : detail.content.subquestions
  if (withParts) value = Object.fromEntries(subquestionRows.map((row) => [row.key, row.answer]))

  // 证明题：已知、求证，以及参考证明（一行一步；整行都是空的就是没填，丢掉）
  let proofStatement = detail.content.proof
  if (proof) {
    proofStatement = { givens: keep(form.givens), claim: form.claim }
    value = {
      steps: form.proofSteps
        .filter((row) => !isBlankRow(row.text, row.reason))
        .map((row) => ({ stage: row.stage, text: row.text, reason: row.reason })),
    }
  }

  // 实验题：数据表、安全提示，以及留空格子的参考值（和小问的参考答案放在同一个对象里）
  let dataTables = detail.content.data_tables
  let safety = detail.content.safety
  if (experiment) {
    dataTables = parseTables(form.dataTablesJson, errors)
    safety = form.safetyOn ? { level: form.safetyLevel, notes: keep(form.safetyNotes) } : null
    value = { ...(value as Record<string, string>), ...parseReferenceCells(form.referenceCellsJson, errors) }
  }

  let writtenRubric: Obj = rubric
  if (subjective) {
    const { points: _previous, ...others } = detail.rubric as unknown as Record<string, unknown>
    const points = form.points
      .filter((row) => !isBlankRow(row.key, row.text))
      .map((row) => ({ key: row.key, part: row.part === '' ? null : row.part, text: row.text }))
    const hadPoints = 'points' in (detail.rubric as object)
    writtenRubric = (points.length === 0 && !hadPoints ? others : { ...others, points }) as unknown as Obj
  }

  const optionAnalysis = Object.fromEntries(
    form.options.filter((row) => row.analysis.trim() !== '').map((row) => [row.key, row.analysis]),
  )

  const solutions: AdminSolutionInput[] = []
  if (form.standard.on) solutions.push(solutionInput('standard', form.standard))
  if (form.fast.on) solutions.push(solutionInput('fast', form.fast))

  if (errors.length > 0) return { ok: false, errors }
  return {
    ok: true,
    body: {
      expected_version: detail.version,
      title: form.title,
      difficulty: form.difficulty,
      grade: form.grade === '' ? null : form.grade,
      content: {
        stem: form.stem,
        options: form.options.map((row) => ({ key: row.key, text: row.text })),
        blanks: form.blanks.map((row) => ({
          key: row.key,
          label: orNull(row.label),
          unit_hint: orNull(row.unitHint),
          placeholder: orNull(row.placeholder),
        })),
        subquestions,
        attachments: form.attachments,
        data_tables: dataTables,
        safety,
        proof: proofStatement,
      },
      answer: { value, equivalence_rules: rules, units },
      teaching: {
        ...(referenceLinks === undefined ? {} : { reference_links: referenceLinks }),
        concept: orNull(form.concept),
        hints: keep(form.hints),
        concept_rephrase: orNull(form.conceptRephrase),
        option_analysis: optionAnalysis,
        visual,
        leak_markers: keep(form.leakMarkers),
      },
      solutions,
      knowledge: form.knowledge
        .split(/[\s,，、]+/)
        .map((code) => code.trim())
        .filter((code) => code !== ''),
      rubric: writtenRubric,
      ...(form.comment.trim() === '' ? {} : { comment: form.comment.trim() }),
    },
  }
}

/** 表单现在的内容与题目详情相比有没有改动（不看修改说明）。 */
export function isUnchanged(body: EditorBody, detail: EditorDetail): boolean {
  const { comment: _comment, ...rest } = body
  return canonical(rest) === canonical(bodyFromDetail(detail))
}
